"""Build OTLP JSON Sessions in the shape ingest expects.

Used by the fixture generator, and meant for the harness (03) and the synthetic
generator (07) if they don't want to run a full OTel SDK exporter:

    b = SessionBuilder("sess-123", member_id="m-017", team="Platform",
                       business_function="Engineering", agent="dwight-harness",
                       dataset="real", experiment="before", task_id="scr-03", task_success=True)
    c = b.call(model="glm-4.7", input_tokens=5200, output_tokens=310, cache_read_tokens=4096,
               prefix_hash="p1", prefix_tokens=4096,
               input_messages=[{"role": "user", "parts": [{"type": "text", "content": "..."}]}],
               output_messages=[...])
    b.tool(c, "read_file", {"path": "company-docs/storage-tiers.md"}, "<file text>", result_tokens=4100)
    payload = b.otlp()        # dict, POST to /v1/traces or write to a file

Message JSON follows the semconv gen_ai.input.messages shape (role + parts).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from dwight.ingest import attributes as A


def _av(v: Any) -> dict:
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [_av(x) for x in v]}}
    if isinstance(v, dict):
        return {"stringValue": json.dumps(v)}
    return {"stringValue": str(v)}


def _kv(d: dict) -> list[dict]:
    return [{"key": k, "value": _av(v)} for k, v in d.items() if v is not None]


def _hex(seed: str, n: int) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:n]


class SessionBuilder:
    def __init__(self, session_id: str, *, member_id: str, team: str, business_function: str,
                 agent: str = "dwight-harness", dataset: str = "real", experiment: str | None = None,
                 task_id: str | None = None, task_success: bool | None = None,
                 start_ns: int = 1_788_000_000_000_000_000, call_gap_ns: int = 4_000_000_000):
        self.session_id = session_id
        self.resource = {A.SERVICE_NAME: agent, A.MEMBER_ID: member_id, A.TEAM: team,
                         A.BUSINESS_FUNCTION: business_function, A.DATASET: dataset}
        self.session_attrs = {A.OPERATION: "invoke_agent", A.AGENT_NAME: agent,
                              A.CONVERSATION_ID: session_id, A.EXPERIMENT: experiment,
                              A.EXPERIMENT_TASK_ID: task_id, A.EXPERIMENT_TASK_SUCCESS: task_success}
        self.trace_id = _hex(session_id, 32)
        self.root_span_id = _hex(session_id + ":root", 16)
        self.t = start_ns
        self.gap = call_gap_ns
        self.spans: list[dict] = []
        self.seq = 0

    def call(self, *, model: str, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0,
             cache_write_tokens: int = 0, prefix_hash: str | None = None, prefix_tokens: int | None = None,
             system_instructions: Any = None, input_messages: Any = None, output_messages: Any = None) -> str:
        span_id = _hex(f"{self.session_id}:call:{self.seq}", 16)
        attrs = {A.OPERATION: "chat", A.CONVERSATION_ID: self.session_id, A.REQUEST_MODEL: model,
                 A.CALL_SEQ: self.seq, A.INPUT_TOKENS: input_tokens, A.OUTPUT_TOKENS: output_tokens,
                 A.CACHE_READ_TOKENS: cache_read_tokens, A.CACHE_WRITE_TOKENS[0]: cache_write_tokens,
                 A.PROMPT_PREFIX_HASH: prefix_hash, A.PROMPT_PREFIX_TOKENS: prefix_tokens,
                 A.SYSTEM_INSTRUCTIONS: json.dumps(system_instructions) if system_instructions is not None else None,
                 A.INPUT_MESSAGES: json.dumps(input_messages) if input_messages is not None else None,
                 A.OUTPUT_MESSAGES: json.dumps(output_messages) if output_messages is not None else None}
        start = self.t
        self.t += self.gap // 2
        self.spans.append({"traceId": self.trace_id, "spanId": span_id, "parentSpanId": self.root_span_id,
                           "name": f"chat {model}", "kind": 3, "startTimeUnixNano": str(start),
                           "endTimeUnixNano": str(self.t), "attributes": _kv(attrs)})
        self.seq += 1
        return span_id

    def tool(self, call_span_id: str, name: str, arguments: Any, result: Any, *,
             result_tokens: int | None = None) -> None:
        n = len(self.spans)
        args_text = arguments if isinstance(arguments, str) else json.dumps(arguments, sort_keys=True)
        result_text = result if isinstance(result, str) else json.dumps(result, sort_keys=True)
        attrs = {A.OPERATION: "execute_tool", A.CONVERSATION_ID: self.session_id, A.TOOL_NAME: name,
                 A.TOOL_CALL_ID: f"tc-{n}", A.TOOL_ARGUMENTS: args_text, A.TOOL_RESULT: result_text,
                 A.TOOL_RESULT_TOKENS: result_tokens}
        start = self.t
        self.t += self.gap // 2
        self.spans.append({"traceId": self.trace_id, "spanId": _hex(f"{self.session_id}:tool:{n}", 16),
                           "parentSpanId": call_span_id, "name": f"execute_tool {name}", "kind": 1,
                           "startTimeUnixNano": str(start), "endTimeUnixNano": str(self.t),
                           "attributes": _kv(attrs)})

    def otlp(self) -> dict:
        root = {"traceId": self.trace_id, "spanId": self.root_span_id, "name": "invoke_agent",
                "kind": 1, "startTimeUnixNano": str(self.spans[0]["startTimeUnixNano"] if self.spans else self.t),
                "endTimeUnixNano": str(self.t), "attributes": _kv(self.session_attrs)}
        return {"resourceSpans": [{"resource": {"attributes": _kv(self.resource)},
                                   "scopeSpans": [{"scope": {"name": "dwight.builder"},
                                                   "spans": [root] + self.spans}]}]}
