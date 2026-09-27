"""OTLP JSON -> Sessions, Calls, tool calls (+ raw content into staging).

Accepts the OTLP/HTTP JSON trace shape: {"resourceSpans": [{"resource": {...},
"scopeSpans": [{"spans": [...]}]}]}. One Session = all spans sharing a
gen_ai.conversation.id (falling back to traceId). Each chat span is a Call;
each execute_tool span is a tool call of the chat span that is its parent (or,
if its parent isn't a chat span, of the latest chat span started before it).

Pricing happens here: calls.spend_usd = tokens x prices.yaml, sessions.spend_usd
= sum. Re-ingesting a Session replaces its Calls but keeps its derived fields.

Raw content (messages, tool arguments/results) goes ONLY into staging_content,
which the classify stage deletes after classification (ADRs 0005, 0008).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dwight import pricing
from dwight.db import dumps
from dwight.ingest import attributes as A


def _value(v: dict) -> Any:
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        return int(v["intValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "boolValue" in v:
        return bool(v["boolValue"])
    if "arrayValue" in v:
        return [_value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return {kv["key"]: _value(kv["value"]) for kv in v["kvlistValue"].get("values", [])}
    return None


def _attrs(items: list[dict] | None) -> dict[str, Any]:
    return {kv["key"]: _value(kv.get("value", {})) for kv in (items or [])}


def _iso(nanos: str | int | None) -> str | None:
    if nanos in (None, "", 0, "0"):
        return None
    return datetime.fromtimestamp(int(nanos) / 1e9, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _as_text(v: Any) -> str:
    return v if isinstance(v, str) else json.dumps(v, sort_keys=True)


def _hash(v: Any) -> str:
    return hashlib.sha256(_as_text(v).encode()).hexdigest()[:16]


def _first(attrs: dict, *keys: str, default=None):
    for k in keys:
        if k in attrs and attrs[k] is not None:
            return attrs[k]
    return default


def _collect(payload: dict) -> dict[str, dict]:
    """Group spans into sessions: {session_id: {"resource": {...}, "spans": [...]}}."""
    sessions: dict[str, dict] = {}
    for rs in payload.get("resourceSpans", []):
        resource = _attrs(rs.get("resource", {}).get("attributes"))
        for ss in rs.get("scopeSpans", []):
            for span in ss.get("spans", []):
                attrs = _attrs(span.get("attributes"))
                sid = attrs.get(A.CONVERSATION_ID) or resource.get(A.CONVERSATION_ID) or span.get("traceId")
                s = sessions.setdefault(sid, {"resource": {}, "spans": []})
                s["resource"].update(resource)
                s["spans"].append({**span, "_attrs": attrs})
    return sessions


def ingest_payload(conn: sqlite3.Connection, payload: dict) -> list[str]:
    """Ingest one OTLP JSON payload. Returns the Session IDs written."""
    written = []
    for sid, s in _collect(payload).items():
        _ingest_session(conn, sid, s["resource"], s["spans"])
        written.append(sid)
    conn.commit()
    return written


def ingest_file(conn: sqlite3.Connection, path: Path | str) -> list[str]:
    """A file may hold one OTLP payload, a list of payloads, or JSON lines."""
    text = Path(path).read_text()
    try:
        data = json.loads(text)
        payloads = data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        payloads = [json.loads(line) for line in text.splitlines() if line.strip()]
    out: list[str] = []
    for p in payloads:
        out += ingest_payload(conn, p)
    return out


def _ingest_session(conn: sqlite3.Connection, sid: str, resource: dict, spans: list[dict]) -> None:
    session_attrs = dict(resource)
    for sp in spans:
        if sp["_attrs"].get(A.OPERATION) == "invoke_agent":
            session_attrs.update(sp["_attrs"])

    chats = [sp for sp in spans if sp["_attrs"].get(A.OPERATION) in A.CHAT_OPERATIONS
             or (A.OPERATION not in sp["_attrs"] and A.INPUT_TOKENS in sp["_attrs"])]
    tools = [sp for sp in spans if sp["_attrs"].get(A.OPERATION) == "execute_tool"]
    chats.sort(key=lambda sp: (sp["_attrs"].get(A.CALL_SEQ, 1e18), int(sp.get("startTimeUnixNano") or 0)))

    starts = [int(sp["startTimeUnixNano"]) for sp in spans if sp.get("startTimeUnixNano")]
    ends = [int(sp["endTimeUnixNano"]) for sp in spans if sp.get("endTimeUnixNano")]
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    success = _first(session_attrs, A.EXPERIMENT_TASK_SUCCESS)
    if isinstance(success, str):
        success = success.lower() in ("true", "1", "pass", "passed", "success")

    # Wipe previous ingest of this Session (calls, tool calls, staging), keep derived fields.
    old_calls = [r[0] for r in conn.execute("SELECT call_id FROM calls WHERE session_id=?", (sid,))]
    conn.executemany("DELETE FROM tool_calls WHERE call_id=?", [(c,) for c in old_calls])
    conn.execute("DELETE FROM calls WHERE session_id=?", (sid,))
    conn.execute("DELETE FROM staging_content WHERE session_id=?", (sid,))

    session_row = {
        "session_id": sid,
        "member_id": _first(session_attrs, A.MEMBER_ID, "enduser.id", "user.id", default="unknown"),
        "team": _first(session_attrs, A.TEAM, default="unknown"),
        "business_function": _first(session_attrs, A.BUSINESS_FUNCTION, default="unknown"),
        "agent": _first(session_attrs, A.AGENT_NAME, A.SERVICE_NAME, default="unknown"),
        "started_at": _iso(min(starts)) if starts else now,
        "ended_at": _iso(max(ends)) if ends else now,
        "dataset": _first(session_attrs, A.DATASET, default="real"),
        "experiment": _first(session_attrs, A.EXPERIMENT),
        "experiment_task_id": _first(session_attrs, A.EXPERIMENT_TASK_ID),
        "task_success": None if success is None else int(bool(success)),
        "ingested_at": now,
    }
    cols = ", ".join(session_row)
    ph = ", ".join(f":{k}" for k in session_row)
    upd = ", ".join(f"{k}=excluded.{k}" for k in session_row if k != "session_id")
    conn.execute(f"INSERT INTO sessions ({cols}) VALUES ({ph}) ON CONFLICT(session_id) DO UPDATE SET {upd}",
                 session_row)

    span_to_call: dict[str, tuple[str, int]] = {}
    chat_starts: list[tuple[int, str, int]] = []
    total_spend = total_in = total_out = 0
    for seq, sp in enumerate(chats):
        a = sp["_attrs"]
        seq = int(a.get(A.CALL_SEQ, seq))
        call_id = f"{sid}:{seq}"
        model = pricing.normalise_model(_first(a, A.REQUEST_MODEL, A.RESPONSE_MODEL, default="unknown"))
        inp = int(a.get(A.INPUT_TOKENS, 0))
        out = int(a.get(A.OUTPUT_TOKENS, 0))
        cr = int(a.get(A.CACHE_READ_TOKENS, 0))
        cw = int(_first(a, *A.CACHE_WRITE_TOKENS, default=0))
        spend = pricing.call_spend(model, inp, out, cr, cw)
        conn.execute(
            "INSERT INTO calls (call_id, session_id, seq, model, input_tokens, output_tokens, cache_read_tokens,"
            " cache_write_tokens, prompt_prefix_hash, prompt_prefix_tokens, started_at, spend_usd)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (call_id, sid, seq, model, inp, out, cr, cw, a.get(A.PROMPT_PREFIX_HASH),
             a.get(A.PROMPT_PREFIX_TOKENS), _iso(sp.get("startTimeUnixNano")), spend))
        total_spend += spend
        total_in += inp
        total_out += out
        span_to_call[sp.get("spanId", "")] = (call_id, seq)
        chat_starts.append((int(sp.get("startTimeUnixNano") or 0), call_id, seq))
        for kind, key in (("system_instructions", A.SYSTEM_INSTRUCTIONS),
                          ("input_messages", A.INPUT_MESSAGES), ("output_messages", A.OUTPUT_MESSAGES)):
            if a.get(key) is not None:
                conn.execute("INSERT INTO staging_content (session_id, call_id, seq, kind, content) VALUES (?,?,?,?,?)",
                             (sid, call_id, seq, kind, _as_text(a[key])))

    chat_starts.sort()
    tool_idx: dict[str, int] = {}
    for sp in sorted(tools, key=lambda sp: int(sp.get("startTimeUnixNano") or 0)):
        a = sp["_attrs"]
        owner = span_to_call.get(sp.get("parentSpanId", ""))
        if owner is None:
            t = int(sp.get("startTimeUnixNano") or 0)
            before = [c for c in chat_starts if c[0] <= t]
            if not before:
                continue
            owner = (before[-1][1], before[-1][2])
        call_id, seq = owner
        idx = tool_idx.get(call_id, 0)
        tool_idx[call_id] = idx + 1
        args, result = a.get(A.TOOL_ARGUMENTS), a.get(A.TOOL_RESULT)
        result_tokens = a.get(A.TOOL_RESULT_TOKENS)
        if result_tokens is None:  # estimate when the emitter didn't count them
            result_tokens = len(_as_text(result)) // 4 if result is not None else 0
        name = a.get(A.TOOL_NAME, "unknown")
        conn.execute(
            "INSERT INTO tool_calls (call_id, idx, tool_call_id, name, args_hash, result_hash, result_tokens)"
            " VALUES (?,?,?,?,?,?,?)",
            (call_id, idx, a.get(A.TOOL_CALL_ID), name,
             a.get(A.TOOL_ARGS_HASH) or (_hash(args) if args is not None else None),
             a.get(A.TOOL_RESULT_HASH) or (_hash(result) if result is not None else None),
             int(result_tokens)))
        for kind, v in (("tool_arguments", args), ("tool_result", result)):
            if v is not None:
                conn.execute("INSERT INTO staging_content (session_id, call_id, seq, kind, tool_idx, tool_name, content)"
                             " VALUES (?,?,?,?,?,?,?)", (sid, call_id, seq, kind, idx, name, _as_text(v)))

    conn.execute("UPDATE sessions SET spend_usd=?, total_input_tokens=?, total_output_tokens=?, call_count=? "
                 "WHERE session_id=?", (total_spend, total_in, total_out, len(chats), sid))
