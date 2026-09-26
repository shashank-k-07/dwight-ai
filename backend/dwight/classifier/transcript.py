"""Staged prompt content -> one compact, call-numbered transcript for the model.

Reads `staging_content` (only the classify stage may, ADRs 0005, 0008). The
transcript is built in memory, handed to the model and then dropped; nothing
here is written anywhere.

Each line is tagged with the Call it belongs to, so the model can say in which
Call a Discovery was established:

    [call 4] assistant -> run_command {"cmd": "bin/blobctl plan ..."}
    [call 5] tool result (run_command): error: STORAGE_ENV is not set ...
    [call 5] assistant: Retrying with STORAGE_ENV=staging.

Tool results arrive in the input of Call seq+1 (Dwight convention: a Call's
input carries only messages new since the previous Call), so a result is tagged
with the Call that first saw it.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

# Budgets (characters). Tool results are mostly doc and file bodies: the head is
# enough to tell what was read, while errors are short and kept whole.
TOOL_RESULT_CHARS = 500
TEXT_CHARS = 1500
ARGS_CHARS = 300
SYSTEM_CHARS = 800
TRANSCRIPT_CHARS = 16000


@dataclass
class StagedRow:
    seq: int
    kind: str
    tool_idx: int | None
    tool_name: str | None
    content: str


def load_staged(conn: sqlite3.Connection, session_id: str) -> list[StagedRow]:
    rows = conn.execute(
        "SELECT seq, kind, tool_idx, tool_name, content FROM staging_content WHERE session_id=? "
        "ORDER BY seq, CASE kind WHEN 'system_instructions' THEN 0 WHEN 'input_messages' THEN 1 "
        "WHEN 'output_messages' THEN 2 ELSE 3 END, tool_idx, rowid", (session_id,)).fetchall()
    return [StagedRow(r["seq"] if r["seq"] is not None else 0, r["kind"], r["tool_idx"], r["tool_name"], r["content"])
            for r in rows]


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + f" …[+{len(text) - limit} chars]"


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def _as_str(v: Any) -> str:
    return v if isinstance(v, str) else json.dumps(v, sort_keys=True, ensure_ascii=False)


def _parts(msg: dict) -> list[dict]:
    """Normalise one message to a list of parts. Accepts the OTel GenAI shape
    ({role, parts:[{type, content|name|arguments|response}]}) and the OpenAI chat
    shape ({role, content, tool_calls})."""
    if isinstance(msg.get("parts"), list):
        return [p for p in msg["parts"] if isinstance(p, dict)]
    parts: list[dict] = []
    content = msg.get("content")
    if isinstance(content, str) and content:
        if msg.get("role") == "tool":
            parts.append({"type": "tool_call_response", "response": content})
        else:
            parts.append({"type": "text", "content": content})
    elif isinstance(content, list):
        for c in content:
            if isinstance(c, dict):
                parts.append({"type": "text", "content": c.get("text") or c.get("content") or ""})
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", tc)
        parts.append({"type": "tool_call", "name": fn.get("name"), "arguments": fn.get("arguments")})
    return parts


def _message_lines(seq: int, payload: Any, tool_names: dict[str, str]) -> list[str]:
    msgs = payload if isinstance(payload, list) else [payload]
    lines = []
    for m in msgs:
        if not isinstance(m, dict):
            lines.append(f"[call {seq}] {_clip(_as_str(m), TEXT_CHARS)}")
            continue
        role = m.get("role", "?")
        for p in _parts(m):
            t = p.get("type")
            if t == "text":
                if p.get("content"):
                    lines.append(f"[call {seq}] {role}: {_clip(p['content'], TEXT_CHARS)}")
            elif t == "tool_call":
                if p.get("id") and p.get("name"):
                    tool_names[p["id"]] = p["name"]
                lines.append(f"[call {seq}] {role} -> {p.get('name')} {_clip(_as_str(p.get('arguments')), ARGS_CHARS)}")
            elif t == "tool_call_response":
                name = tool_names.get(p.get("id", ""), "tool")
                lines.append(f"[call {seq}] tool result ({name}): {_clip(_as_str(p.get('response')), TOOL_RESULT_CHARS)}")
            elif p.get("content"):
                lines.append(f"[call {seq}] {role}: {_clip(_as_str(p['content']), TEXT_CHARS)}")
    return lines


def _system_text(content: str) -> str:
    v = _json(content)
    items = v if isinstance(v, list) else [v]
    return " ".join(_as_str(p.get("content", p)) if isinstance(p, dict) else _as_str(p) for p in items)


def render_transcript(rows: list[StagedRow], limit: int = TRANSCRIPT_CHARS) -> str:
    """Render staged rows as call-numbered lines. Messages are the primary source;
    tool_arguments/tool_result rows are used only when a Session has no messages
    (an emitter that sends tool spans but not message content)."""
    tool_names: dict[str, str] = {}
    lines: list[str] = []
    seen_system: set[str] = set()
    has_messages = any(r.kind in ("input_messages", "output_messages") for r in rows)
    for r in rows:
        if r.kind == "system_instructions":
            text = _system_text(r.content)
            if text not in seen_system:  # the system prompt usually repeats on every Call
                seen_system.add(text)
                lines.append(f"[call {r.seq}] system: {_clip(text, SYSTEM_CHARS)}")
        elif r.kind in ("input_messages", "output_messages"):
            lines += _message_lines(r.seq, _json(r.content), tool_names)
        elif not has_messages and r.kind == "tool_arguments":
            lines.append(f"[call {r.seq}] assistant -> {r.tool_name} {_clip(r.content, ARGS_CHARS)}")
        elif not has_messages and r.kind == "tool_result":
            lines.append(f"[call {r.seq + 1}] tool result ({r.tool_name}): {_clip(r.content, TOOL_RESULT_CHARS)}")
    return _fit(lines, limit)


def _fit(lines: list[str], limit: int) -> str:
    """Keep the transcript under `limit` chars: the head (task, first steps) and
    the tail (where trial and error resolves) matter most, so drop the middle."""
    text = "\n".join(lines)
    if len(text) <= limit:
        return text
    head, tail, used = [], [], 0
    budget = limit - 60
    i, j = 0, len(lines) - 1
    while i <= j:
        take_head = len(head) <= len(tail)  # alternate, head first
        line = lines[i] if take_head else lines[j]
        if used + len(line) + 1 > budget:
            break
        used += len(line) + 1
        if take_head:
            head.append(line)
            i += 1
        else:
            tail.append(line)
            j -= 1
    omitted = j - i + 1
    return "\n".join(head + [f"… [{omitted} lines omitted] …"] + tail[::-1])
