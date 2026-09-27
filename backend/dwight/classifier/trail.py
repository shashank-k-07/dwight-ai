"""Trail: the ordered resources a Session's Agent read. Built by code, never by
the model (build-spec §4.3 step 2).

Source: `tool_calls` (name, result tokens, owning Call) joined with the staged
`tool_arguments` for each read-type tool call. Only the normalised resource id,
the result tokens and the Call seq are kept; arguments and results are content
and are discarded with the rest of staging (ADR 0008).

Resource id forms (ticket 02):
    company-docs/<doc_id>.md    a company doc read by doc id (read_doc) or path
    perch:<SPACE>/<slug>        a Perch wiki page (already an id, kept as is)
    repo:<repo>/<path>          a repository file (already an id, kept as is)
    <relative/path>             a workspace file, normalised
    https://host/path           a URL: lower-case scheme/host, no fragment,
                                no tracking params, no trailing slash
"""
from __future__ import annotations

import json
import posixpath
import re
import sqlite3
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Tools that read a resource into context. Matched on the lower-cased tool name:
# an exact name, or a verb-like prefix/suffix (read_doc, fetch_url, get_page,
# Read, view_file, open_url ...). Write/run/search tools are not reads.
READ_VERBS = ("read", "fetch", "get", "open", "view", "cat", "load", "browse", "download", "retrieve")
NOT_READ = ("write", "edit", "create", "delete", "remove", "run", "exec", "search", "list", "update", "patch", "apply")

# Argument keys that hold the resource identifier, in priority order.
DOC_KEYS = ("doc_id", "document_id", "page_id", "doc")
PATH_KEYS = ("path", "file_path", "filepath", "file", "filename", "target_file")
URL_KEYS = ("url", "uri", "href", "link")
OTHER_KEYS = ("resource_id", "resource", "id", "name")

_ID_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:(?!//)", re.I)  # perch:ENG/x, repo:kestrel/x (not http://)
_TRACKING = re.compile(r"^(utm_.*|ref|ref_src|fbclid|gclid)$", re.I)


@dataclass
class TrailEntry:
    position: int
    resource_id: str
    tokens: int
    call_seq: int


def is_read_tool(name: str | None) -> bool:
    n = (name or "").lower()
    words = re.split(r"[^a-z]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", name or "").lower())
    if any(w in NOT_READ for w in words):
        return False
    return any(w in READ_VERBS for w in words) or n in READ_VERBS


def normalise_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                             if not _TRACKING.match(k)))
    path = re.sub(r"/{2,}", "/", parts.path or "")
    if len(path) > 1:
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def normalise_path(path: str) -> str:
    p = path.strip().strip("'\"").replace("\\", "/")
    # An absolute path into a checkout of company-docs/ -> the repo-relative doc id.
    m = re.search(r"(?:^|/)(company-docs/.+)$", p)
    if m:
        p = m.group(1)
    p = posixpath.normpath(p) if p else p
    if p.startswith("./"):
        p = p[2:]
    return "" if p == "." else p


def normalise_doc_id(doc_id: str) -> str:
    d = doc_id.strip().strip("'\"")
    if _ID_SCHEME.match(d):          # perch:ENG/oidc-migration-plan, repo:kestrel/...
        scheme, _, rest = d.partition(":")
        return f"{scheme.lower()}:{rest.strip('/')}"
    if "://" in d:
        return normalise_url(d)
    d = normalise_path(d)
    if d.startswith("company-docs/"):
        return d if d.endswith(".md") else d + ".md"
    if "/" not in d:                 # a bare company doc id, e.g. storage-tiering-policy
        return f"company-docs/{d if d.endswith('.md') else d + '.md'}"
    return d


def resource_id(tool_name: str | None, args: object) -> str | None:
    """The normalised resource a read-type tool call read, or None."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            s = args.strip()
            return normalise_url(s) if "://" in s else (normalise_path(s) or None) if s else None
    if not isinstance(args, dict):
        return None
    for k in DOC_KEYS:
        if isinstance(args.get(k), str) and args[k].strip():
            return normalise_doc_id(args[k])
    for k in URL_KEYS:
        if isinstance(args.get(k), str) and args[k].strip():
            return normalise_url(args[k])
    for k in PATH_KEYS:
        if isinstance(args.get(k), str) and args[k].strip():
            v = args[k]
            if "://" in v:
                return normalise_url(v)
            if _ID_SCHEME.match(v):
                return normalise_doc_id(v)
            return normalise_path(v) or None
    for k in OTHER_KEYS:
        if isinstance(args.get(k), str) and args[k].strip():
            return normalise_doc_id(args[k])
    return None


_SHELL_TOOL = re.compile(r"(run|exec|bash|shell|terminal|command)", re.I)
_SHELL_READ = re.compile(r"^\s*(?:cat|less|more|head|tail)\s+(?:-\S+\s+)*([^\s|;&<>]+)\s*$")


def shell_read(tool_name: str | None, args: object) -> str | None:
    """`cat <file>` (or head/tail/less) run through a shell tool is a read too."""
    if not _SHELL_TOOL.search(tool_name or ""):
        return None
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {"cmd": args}
    cmd = next((args.get(k) for k in ("cmd", "command", "script") if isinstance(args, dict)
                and isinstance(args.get(k), str)), None)
    m = _SHELL_READ.match(cmd or "")
    return (normalise_path(m.group(1)) or None) if m else None


def build_trail(conn: sqlite3.Connection, session_id: str) -> list[TrailEntry]:
    """Read-type tool calls of a Session, in Call then tool order. Must run before
    the Session's staging rows are deleted (it needs the tool arguments)."""
    rows = conn.execute(
        "SELECT c.seq, t.idx, t.name, t.result_tokens, sc.content AS args "
        "FROM tool_calls t JOIN calls c ON c.call_id = t.call_id "
        "LEFT JOIN staging_content sc ON sc.session_id = c.session_id AND sc.call_id = t.call_id "
        "     AND sc.kind = 'tool_arguments' AND sc.tool_idx = t.idx "
        "WHERE c.session_id = ? ORDER BY c.seq, t.idx", (session_id,)).fetchall()
    trail: list[TrailEntry] = []
    for r in rows:
        if r["args"] is None:
            continue
        rid = resource_id(r["name"], r["args"]) if is_read_tool(r["name"]) else shell_read(r["name"], r["args"])
        if rid:
            trail.append(TrailEntry(len(trail), rid, int(r["result_tokens"] or 0), int(r["seq"])))
    return trail
