"""The Agent's tools, sandboxed to one Workspace.

Read-type (they build the Trail, ticket 06): read_file, list_files, search,
list_docs, read_doc. Write/run: write_file, run_command.

Names and argument shapes match the fixtures (read_file {path}, read_doc
{doc_id}, run_command {cmd}, write_file {path, content}), so classify and the
detectors see the same shapes on real and fixture Sessions.

Tool results are deterministic for the same input (identical results must hash
identically for the Redundant Read and Runaway Loop detectors): the workspace
path is replaced by "." and pytest-style durations ("in 0.12s") are blanked.

Protection of the blobctl stub: `read_file` / `search` refuse the workspace's
deny list, and `run_command` refuses any command that mentions blobctl other
than as the program being run (so `bin/blobctl plan ...` works but
`cat bin/blobctl` does not). On macOS, commands also run under sandbox-exec
with writes limited to the workspace and no network.
"""
from __future__ import annotations

import fnmatch
import json
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from dwight.harness.workspace import Workspace

READ_TOOLS = frozenset({"read_file", "list_files", "search", "list_docs", "read_doc"})
WRITE_TOOLS = frozenset({"write_file", "run_command", "run_tests"})

MAX_READ_CHARS = 60_000
MAX_CMD_CHARS = 12_000
MAX_SEARCH_HITS = 80
MAX_LIST_ENTRIES = 200
COMMAND_TIMEOUT_S = 60

_DURATION = re.compile(r"\b(in|took|after) \d+(?:\.\d+)?s\b")


@dataclass
class ToolResult:
    text: str
    ok: bool = True
    exit_code: int | None = None   # run_command only


SPECS = {
    "list_files": {
        "description": "List the entries of a directory in the workspace (non-recursive). Directories end with '/'.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Directory relative to the workspace root. Default '.'"}},
            "required": []}},
    "read_file": {
        "description": "Read a text file from the workspace.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path relative to the workspace root"}},
            "required": ["path"]}},
    "search": {
        "description": "Search text files in the workspace for a regular expression. Returns path:line: text.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "Python regular expression"},
            "path": {"type": "string", "description": "Directory or file to search, relative to the root. Default '.'"}},
            "required": ["pattern"]}},
    "list_docs": {
        "description": "List the internal documents available to read_doc.",
        "parameters": {"type": "object", "properties": {}, "required": []}},
    "read_doc": {
        "description": "Read an internal document by its doc_id (see list_docs).",
        "parameters": {"type": "object", "properties": {
            "doc_id": {"type": "string", "description": "Document id, e.g. from list_docs"}},
            "required": ["doc_id"]}},
    "write_file": {
        "description": "Create or overwrite a text file in the workspace.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path relative to the workspace root"},
            "content": {"type": "string", "description": "Full new file content"}},
            "required": ["path", "content"]}},
    "run_tests": {
        "description": "Run the test suite (or one test file) with pytest. Returns the exit code and output.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Test file or directory, relative to the root. Default 'tests'"}},
            "required": []}},
    "run_command": {
        "description": "Run a shell command with the workspace root as the current directory. "
                       "Returns the exit code and combined stdout/stderr.",
        "parameters": {"type": "object", "properties": {
            "cmd": {"type": "string", "description": "Shell command line"}},
            "required": ["cmd"]}},
}


class Toolbox:
    def __init__(self, ws: Workspace, *, docs: dict[str, Path] | None = None,
                 tools: tuple[str, ...] | None = None, sandbox: bool = True,
                 timeout_s: int = COMMAND_TIMEOUT_S):
        self.ws = ws
        self.root = ws.root.resolve()
        self.docs = docs or {}
        default = ("list_files", "read_file", "search", "write_file", "run_command")
        if self.docs:
            default = ("list_docs", "read_doc") + default
        self.enabled = tuple(tools or default)
        self.timeout_s = timeout_s
        self.sandbox = sandbox and sys.platform == "darwin" and shutil.which("sandbox-exec") is not None

    # -- schema --------------------------------------------------------------
    def specs(self) -> list[dict]:
        return [{"type": "function", "function": {"name": n, **SPECS[n]}} for n in self.enabled]

    # -- dispatch ------------------------------------------------------------
    def execute(self, name: str, args: dict) -> ToolResult:
        if name not in self.enabled:
            return ToolResult(f"Error: unknown tool '{name}'", ok=False)
        try:
            return getattr(self, "_" + name)(**args)
        except TypeError as e:
            return ToolResult(f"Error: bad arguments for {name}: {e}", ok=False)

    # -- helpers -------------------------------------------------------------
    def normalise(self, text: str) -> str:
        text = text.replace(str(self.root) + "/", "").replace(str(self.root), ".")
        return _DURATION.sub(lambda m: f"{m.group(1)} <duration>", text)

    def _resolve(self, path: str | None) -> tuple[Path | None, str | None]:
        rel = (path or ".").strip() or "."
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            return None, f"Error: '{rel}' is outside the workspace"
        return p, None

    def _denied(self, p: Path) -> bool:
        rel = p.relative_to(self.root).as_posix() if p != self.root else "."
        for pat in self.ws.deny_read:
            if rel == pat or rel.startswith(pat.rstrip("/") + "/") or fnmatch.fnmatch(rel, pat):
                return True
        return False

    # -- read-type -----------------------------------------------------------
    def _list_files(self, path: str = ".") -> ToolResult:
        p, err = self._resolve(path)
        if err:
            return ToolResult(err, ok=False)
        if not p.is_dir():
            return ToolResult(f"Error: '{path}' is not a directory", ok=False)
        entries = sorted(p.iterdir(), key=lambda x: x.name)
        names = [e.name + ("/" if e.is_dir() else "") for e in entries
                 if e.name not in (".git", "__pycache__", ".tmp", ".pytest_cache")]
        more = f"\n... ({len(names) - MAX_LIST_ENTRIES} more)" if len(names) > MAX_LIST_ENTRIES else ""
        return ToolResult("\n".join(names[:MAX_LIST_ENTRIES]) + more if names else "(empty directory)")

    def _read_file(self, path: str) -> ToolResult:
        p, err = self._resolve(path)
        if err:
            return ToolResult(err, ok=False)
        if self._denied(p):
            return ToolResult(f"Error: permission denied: '{path}' can be executed with run_command "
                              "but not read", ok=False)
        if not p.is_file():
            return ToolResult(f"Error: no such file '{path}'", ok=False)
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            return ToolResult(f"Error: '{path}' is not a text file", ok=False)
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + f"\n... [truncated at {MAX_READ_CHARS} characters]"
        return ToolResult(text)

    def _search(self, pattern: str, path: str = ".") -> ToolResult:
        p, err = self._resolve(path)
        if err:
            return ToolResult(err, ok=False)
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return ToolResult(f"Error: bad regular expression: {e}", ok=False)
        files = [p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file())
        hits: list[str] = []
        for f in files:
            rel_parts = f.relative_to(self.root).parts
            if any(part in (".git", "__pycache__", ".tmp") for part in rel_parts) or self._denied(f):
                continue
            try:
                lines = f.read_text().splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for i, line in enumerate(lines, 1):
                if rx.search(line):
                    hits.append(f"{f.relative_to(self.root).as_posix()}:{i}: {line.strip()[:200]}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        return ToolResult("\n".join(hits) + f"\n... [stopped at {MAX_SEARCH_HITS} matches]")
        return ToolResult("\n".join(hits) if hits else "(no matches)")

    def _list_docs(self) -> ToolResult:
        lines = []
        for doc_id, path in self.docs.items():
            title = next((l.lstrip("# ").strip() for l in path.read_text().splitlines() if l.startswith("#")), doc_id)
            lines.append(f"{doc_id}: {title}")
        return ToolResult("\n".join(lines) or "(no documents)")

    def _read_doc(self, doc_id: str) -> ToolResult:
        key = doc_id.strip().removeprefix("company-docs/").removesuffix(".md")
        if key not in self.docs:
            return ToolResult(f"Error: no document '{doc_id}'. Use list_docs to see the available ids.", ok=False)
        return ToolResult(self.docs[key].read_text())

    # -- write / run ---------------------------------------------------------
    def _write_file(self, path: str, content: str) -> ToolResult:
        p, err = self._resolve(path)
        if err:
            return ToolResult(err, ok=False)
        if self._denied(p) or p.relative_to(self.root).parts[:1] == ("bin",):
            return ToolResult(f"Error: permission denied: '{path}' is read-only", ok=False)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return ToolResult(f"Wrote {len(content.encode())} bytes to {p.relative_to(self.root).as_posix()}")

    def _run_tests(self, path: str = "tests") -> ToolResult:
        p, err = self._resolve(path or "tests")
        if err:
            return ToolResult(err, ok=False)
        return self._run_command(f"python -m pytest -q --tb=short {shlex.quote(p.relative_to(self.root).as_posix())}")

    def _run_command(self, cmd: str) -> ToolResult:
        if protected_read(cmd):
            return ToolResult("Error: permission denied: bin/blobctl can be run (e.g. `bin/blobctl --help`) "
                              "but not read, copied or passed to another program", ok=False, exit_code=126)
        argv = ["/bin/sh", "-c", cmd]
        if self.sandbox:
            argv = ["sandbox-exec", "-p", _sandbox_profile(self.root)] + argv
        try:
            proc = subprocess.run(argv, cwd=self.root, env=self.ws.env, capture_output=True, text=True,
                                  timeout=self.timeout_s, stdin=subprocess.DEVNULL)
            out, rc = (proc.stdout or "") + (proc.stderr or ""), proc.returncode
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            out += f"\n[timed out after {self.timeout_s}s]"
            rc = 124
        out = self.normalise(out)
        if len(out) > MAX_CMD_CHARS:
            out = f"[... output truncated, last {MAX_CMD_CHARS} characters]\n" + out[-MAX_CMD_CHARS:]
        return ToolResult(f"exit code: {rc}\n{out}".rstrip(), ok=rc == 0, exit_code=rc)


# Wrappers that run the next word as a program.
_PREFIX_WORDS = {"env", "exec", "time", "nohup", "command", "builtin"}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def protected_read(cmd: str) -> bool:
    """True if the command mentions blobctl anywhere except as the program being
    executed (`bin/blobctl ...`, `STORAGE_ENV=x ./bin/blobctl ...`)."""
    if not _mentions_source(cmd):
        return False
    for part in re.split(r"\|\||&&|[;|&\n()`]|\$\(", cmd):
        try:
            words = shlex.split(part)
        except ValueError:
            words = part.split()
        i = 0
        while i < len(words) and (_ASSIGN.match(words[i]) or words[i] in _PREFIX_WORDS):
            i += 1
        rest = words[i + 1:]
        if any(_mentions_source(w) for w in words[:i]) or any(_mentions_source(w) for w in rest):
            return True
        if i < len(words) and _mentions_source(words[i]) and not words[i].endswith("blobctl"):
            return True
    return False


def _mentions_source(word: str) -> bool:
    """blobctl the program, not its state dir (.blobctl/ plans and ledger are fine to read)."""
    w = re.sub(r"\.blobctl\b|blobctl_state_dir", "", word.lower())
    return "blobctl" in w


def _sandbox_profile(root: Path) -> str:
    """macOS sandbox: allow everything except network and writes outside the workspace."""
    r = json.dumps(str(root))
    return ("(version 1)(allow default)(deny network*)(deny file-write*)"
            f"(allow file-write* (subpath {r}) (subpath \"/dev\") (subpath \"/private/var/folders\"))")
