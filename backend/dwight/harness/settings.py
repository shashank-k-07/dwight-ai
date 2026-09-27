"""The storage-run settings file (tickets 04 / 16): one committed JSON file that
pins the model and every harness setting of the "before" batch, so the "after"
batch runs on exactly the same ones.

    python -m dwight.harness storage-settings --model M --out ../data/real_scr_settings.json
    python -m dwight.harness storage --settings ../data/real_scr_settings.json --experiment before ...

`params` are what the CLI takes from the file (model, max_calls, repeat, tasks,
workers). `fingerprint` is derived from the code and data at run time (system
prompt, tool schemas, sampling, task prompts + checks, company-docs, the
blobctl workspace, the provider). Loading the file recomputes the fingerprint
and refuses to run if anything drifted since the before batch, so an after run
can't silently compare against different settings. Context files (the Draft +
memory file) are deliberately NOT part of it: they are the one allowed
difference.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dwight import company, config
from dwight.harness import tasks
from dwight.harness.tasks import storage_specs as _storage_specs   # bound at import: the specs actually run
from dwight.harness.agent import LENGTH_CONTINUE, build_system
from dwight.harness.runner import MAX_WORKERS
from dwight.harness.tools import SPECS
from dwight.harness.workspace import KESTREL_WORKSPACE

DEFAULT_PATH = config.DATA_DIR / "real_scr_settings.json"
PARAM_KEYS = ("model", "max_calls", "repeat", "tasks", "workers")


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()[:16]


def _tree_sha(root: Path) -> str:
    h = hashlib.sha256()
    # Skip out/: the harness creates it as scratch per run (workspace.py), and a local
    # checkout may hold an ignored out/.keep that a fresh clone doesn't.
    for p in sorted(x for x in root.rglob("*") if x.is_file() and x.relative_to(root).parts[0] != "out"):
        h.update(str(p.relative_to(root)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def fingerprint() -> dict:
    """Everything that shapes a storage Session other than `params` and the context files."""
    tool_names = ("list_docs", "read_doc", "list_files", "read_file", "search", "write_file", "run_command")
    tool_specs = [{"type": "function", "function": {"name": n, **SPECS[n]}} for n in tool_names]
    all_tasks = (company.storage_tasks() or {}).get("tasks", [])
    spec = _storage_specs(experiment=None, session_prefix="fingerprint")[0]
    docs = spec.docs
    return {
        "system_prompt_sha": _sha(build_system(spec.system_prompt, [])),
        "tools": list(tool_names),
        "tool_specs_sha": _sha(json.dumps(tool_specs, sort_keys=True)),
        "temperature": spec.temperature,
        "max_tokens_per_call": spec.max_tokens,
        "continue_on_length": spec.continue_on_length,
        "length_continue_prompt_sha": _sha(LENGTH_CONTINUE),
        "thinking": config.GLM_THINKING or None,
        "base_url": config.GLM_BASE_URL,
        "task_ids": [t["id"] for t in all_tasks],
        "tasks_sha": _sha(json.dumps([{k: t.get(k) for k in ("id", "prompt", "check")} for t in all_tasks],
                                     sort_keys=True)),
        "docs": sorted(docs),
        "docs_sha": _sha(b"".join(docs[d].read_bytes() for d in sorted(docs))),
        "workspace_sha": _tree_sha(KESTREL_WORKSPACE),
    }


def build(*, model: str, max_calls: int = tasks.STORAGE_MAX_CALLS, repeat: int = 1,
          task_ids: list[str] | None = None, workers: int = MAX_WORKERS) -> dict:
    if not model:
        raise ValueError("pin a model: the settings file must name one model explicitly")
    return {
        "about": "Harness settings shared by the storage before (04) and after (16) runs. "
                 "Run with: python -m dwight.harness storage --settings <this file> ...",
        "params": {"model": model, "max_calls": max_calls, "repeat": repeat, "tasks": task_ids,
                   "workers": workers},
        "fingerprint": fingerprint(),
    }


def write(path: Path, **kw) -> dict:
    s = build(**kw)
    path.write_text(json.dumps(s, indent=1) + "\n")
    return s


def load(path: Path) -> dict:
    """The file's params, after checking its fingerprint against the current code and data."""
    s = json.loads(Path(path).read_text())
    params = s["params"]
    if not params.get("model"):
        raise ValueError(f"{path}: params.model is empty")
    now = fingerprint()
    drift = sorted(k for k in set(now) | set(s["fingerprint"]) if now.get(k) != s["fingerprint"].get(k))
    if drift:
        raise ValueError(f"{path}: harness settings changed since this file was written: {', '.join(drift)}. "
                         "Before and after runs would not be comparable.")
    return {k: params.get(k) for k in PARAM_KEYS}
