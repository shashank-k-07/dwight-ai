"""The Agent loop: one SessionSpec in, one Session of OTel GenAI telemetry out.

    result = run_session(spec)          # live: calls the model through dwight.glm
    result.payload                      # OTLP JSON (SessionBuilder shape), ready for ingest

One model per Session: `glm.model_for()` is called once and the returned
model string is sent on every Call and recorded in `gen_ai.request.model`.

Telemetry recorded per Call (chat span), all from the API response:
  * input_tokens = usage.prompt_tokens, output_tokens = usage.completion_tokens
  * cache_read_tokens only if the API reports it (usage.prompt_tokens_details
    .cached_tokens, or DeepSeek's prompt_cache_hit_tokens). If it doesn't, the
    attribute is left out (ingest stores 0). Nothing is invented.
  * dwight.prompt.prefix_hash = hash of the stable prompt prefix: the system
    instructions (incl. any context files) + tool definitions, WITHOUT the
    volatile header of the Cache Miss variant. dwight.prompt.prefix_tokens =
    that prefix's size, estimated from its characters and the Session's
    measured tokens-per-character on Call 0.
  * gen_ai.input.messages = only the messages new since the previous Call;
    gen_ai.system_instructions on Call 0 and whenever it changes.
Each tool the model requests is an execute_tool span under that chat span.
"""
from __future__ import annotations

import hashlib
import json
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dwight import config, glm
from dwight.harness.tools import READ_TOOLS, Toolbox
from dwight.harness.workspace import Workspace
from dwight.ingest import attributes as A
from dwight.ingest.builder import SessionBuilder

AGENT_NAME = "kestrel-devagent"
VARIANTS = ("clean", "redundant_read", "cache_miss", "runaway_loop")
MAX_TOKENS_PER_CALL = 4096
LENGTH_CONTINUE = ("[kestrel-devagent] Your last reply hit the output token limit before you called a tool or "
                   "answered. Continue the task: keep your reasoning short and make the next tool call.")
API_ATTEMPTS = 5            # on top of the openai client's own 3 retries


@dataclass
class SessionSpec:
    session_id: str
    prompt: str
    system_prompt: str
    member_id: str
    team: str                          # org.yaml display name
    business_function: str             # org.yaml display name
    make_workspace: Callable[[str], Workspace]
    task_id: str | None = None
    variant: str = "clean"             # clean | redundant_read | cache_miss | runaway_loop
    experiment: str | None = None      # before | after
    tag_task_id: bool = False          # set dwight.experiment.task_id even without an experiment
    context_files: list[Path] = field(default_factory=list)
    docs: dict[str, Path] = field(default_factory=dict)
    tools: tuple[str, ...] | None = None
    max_calls: int = 16
    retry_prompt: str | None = None    # Runaway Loop: re-prompt when the Agent stops while the last command failed
    reread_reminder: str | None = None # Redundant Read: after each turn, remind the Agent to re-read {files}
    check: Callable[[Path], tuple[bool, list[str]]] | None = None
    model: str | None = None           # None = glm.model_for() once per Session
    temperature: float = 0.2
    max_tokens: int = MAX_TOKENS_PER_CALL
    continue_on_length: bool = False   # a reply cut off by max_tokens (no tool call) gets LENGTH_CONTINUE, not "done"
    agent: str = AGENT_NAME


@dataclass
class SessionResult:
    session_id: str
    model: str
    payload: dict
    task_success: bool | None
    check_notes: list[str]
    calls: int
    input_tokens: int
    output_tokens: int
    cache_read_reported: bool
    tool_calls: list[dict]             # [{seq, name, args_hash, result_hash, result_tokens}]
    stop_reason: str                   # final_answer | max_calls
    workspace: Path
    final_answer: str = ""


class _TimedBuilder(SessionBuilder):
    """SessionBuilder with real wall-clock span times."""

    def timed_call(self, start_ns: int, end_ns: int, **kw) -> str:
        self.t, self.gap = start_ns, max(2 * (end_ns - start_ns), 2)
        return self.call(**kw)

    def timed_tool(self, start_ns: int, end_ns: int, call_span: str, name: str, args: Any, result: str,
                   result_tokens: int) -> None:
        self.t, self.gap = start_ns, max(2 * (end_ns - start_ns), 2)
        self.tool(call_span, name, args, result, result_tokens=result_tokens)


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def canonical_args(args: Any) -> str:
    return args if isinstance(args, str) else json.dumps(args, sort_keys=True)


def volatile_header() -> str:
    """The Cache Miss plant: a fresh timestamp + request id at the very top of the prompt."""
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    return f"[kestrel-devagent session header] generated {now} request {uuid.uuid4().hex[:12]}\n\n"


def build_system(base: str, context_files: list[Path]) -> str:
    """Stable system instructions, with context files (e.g. a Draft and memory file, ticket 16) appended."""
    parts = [base.strip()]
    if context_files:
        parts.append("# Context files\nThe following files were loaded into your context at session start.")
        for p in context_files:
            parts.append(f"## {Path(p).name}\n\n{Path(p).read_text().strip()}")
    return "\n\n".join(parts)


def _cached_tokens(usage: Any) -> int | None:
    """What the API reports as cache-read input tokens, or None if it reports nothing."""
    if usage is None:
        return None
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        v = details.get("cached_tokens") if isinstance(details, dict) else getattr(details, "cached_tokens", None)
        if v is not None:
            return int(v)
    extra = getattr(usage, "model_extra", None) or {}
    for key in ("prompt_cache_hit_tokens", "cached_tokens", "cache_read_input_tokens"):
        v = extra.get(key) if isinstance(extra, dict) else None
        if v is None:
            v = getattr(usage, key, None) if not isinstance(usage, dict) else usage.get(key)
        if v is not None:
            return int(v)
    return None


def _extra_body() -> dict:
    return {"thinking": {"type": config.GLM_THINKING}} if config.GLM_THINKING else {}


def complete(client: Any, *, model: str, messages: list[dict], tools: list[dict], temperature: float,
             max_tokens: int = MAX_TOKENS_PER_CALL, sleep: Callable[[float], None] = time.sleep) -> Any:
    """One Chat Completions request, retried with backoff on API errors (not on 4xx other than 408/409/429)."""
    from openai import APIError, APIStatusError

    for attempt in range(API_ATTEMPTS):
        try:
            return client.chat.completions.create(
                model=model, messages=messages, tools=tools or None, temperature=temperature,
                max_tokens=max_tokens, extra_body=_extra_body())
        except APIError as e:
            status = getattr(e, "status_code", None) if isinstance(e, APIStatusError) else None
            if status is not None and 400 <= status < 500 and status not in (408, 409, 429):
                raise
            if attempt == API_ATTEMPTS - 1:
                raise
            sleep(min(2 ** attempt * 2, 30) + random.random())
    raise AssertionError("unreachable")


def _tool_call_fields(tc: Any) -> tuple[str, str, str]:
    fn = tc.function if not isinstance(tc, dict) else tc["function"]
    tc_id = tc.id if not isinstance(tc, dict) else tc["id"]
    name = fn.name if not isinstance(fn, dict) else fn["name"]
    args = fn.arguments if not isinstance(fn, dict) else fn["arguments"]
    return tc_id, name, args or "{}"


def run_session(spec: SessionSpec, *, client: Any = None, sleep: Callable[[float], None] = time.sleep) -> SessionResult:
    client = client or glm.client()
    model = spec.model or glm.model_for()
    ws = spec.make_workspace(spec.session_id)
    tb = Toolbox(ws, docs=spec.docs, tools=spec.tools)
    tools = tb.specs()

    stable_system = build_system(spec.system_prompt, spec.context_files)
    prefix_text = stable_system + "\n" + json.dumps(tools, sort_keys=True)
    prefix_hash = _h(prefix_text)

    b = _TimedBuilder(spec.session_id, member_id=spec.member_id, team=spec.team,
                      business_function=spec.business_function, agent=spec.agent, dataset="real",
                      experiment=spec.experiment,
                      task_id=spec.task_id if (spec.experiment or spec.tag_task_id) else None)

    messages: list[dict] = [{"role": "user", "content": spec.prompt}]
    new_otel: list[dict] = [{"role": "user", "parts": [{"type": "text", "content": spec.prompt}]}]
    last_system: str | None = None
    tokens_per_char: float | None = None
    prefix_tokens: int | None = None
    total_in = total_out = 0
    cache_reported = False
    tool_log: list[dict] = []
    last_exit_code: int | None = None
    opened: list[str] = []
    stop_reason, final_answer = "max_calls", ""

    for seq in range(spec.max_calls):
        system = (volatile_header() + stable_system) if spec.variant == "cache_miss" else stable_system
        request = [{"role": "system", "content": system}] + messages
        t0 = time.time_ns()
        resp = complete(client, model=model, messages=request, tools=tools, temperature=spec.temperature,
                        max_tokens=spec.max_tokens, sleep=sleep)
        t1 = time.time_ns()

        usage = resp.usage
        inp = int(getattr(usage, "prompt_tokens", 0) or 0)
        out = int(getattr(usage, "completion_tokens", 0) or 0)
        cached = _cached_tokens(usage)
        cache_reported = cache_reported or cached is not None
        if tokens_per_char is None:
            chars = len(prefix_text) + sum(len(m["content"] or "") for m in request)
            tokens_per_char = inp / chars if chars and inp else 0.25
            prefix_tokens = round(len(prefix_text) * tokens_per_char)
        total_in += inp
        total_out += out

        choice = resp.choices[0]
        msg = choice.message
        text = msg.content or ""
        reasoning = getattr(msg, "reasoning_content", None) or (getattr(msg, "model_extra", None) or {}).get(
            "reasoning_content")
        raw_calls = [_tool_call_fields(tc) for tc in (msg.tool_calls or [])]

        parts: list[dict] = []
        if reasoning:
            parts.append({"type": "reasoning", "content": reasoning})
        if text:
            parts.append({"type": "text", "content": text})
        parsed: list[tuple[str, str, Any, str | None]] = []
        for tc_id, name, arg_text in raw_calls:
            try:
                args = json.loads(arg_text) if arg_text.strip() else {}
                err = None if isinstance(args, dict) else "arguments must be a JSON object"
            except json.JSONDecodeError as e:
                args, err = arg_text, f"arguments were not valid JSON: {e}"
            parsed.append((tc_id, name, args, err))
            parts.append({"type": "tool_call", "id": tc_id, "name": name, "arguments": args})
        output_messages = [{"role": "assistant", "parts": parts, "finish_reason": choice.finish_reason}]

        span = b.timed_call(
            t0, t1, model=model, input_tokens=inp, output_tokens=out,
            cache_read_tokens=cached, cache_write_tokens=None,
            prefix_hash=prefix_hash, prefix_tokens=prefix_tokens,
            system_instructions=[{"type": "text", "content": system}] if system != last_system else None,
            input_messages=new_otel, output_messages=output_messages)
        last_system = system
        new_otel = []

        assistant: dict = {"role": "assistant", "content": text}
        if raw_calls:
            assistant["tool_calls"] = [{"id": i, "type": "function", "function": {"name": n, "arguments": a}}
                                       for i, n, a in raw_calls]
        messages.append(assistant)

        if parsed:
            for tc_id, name, args, err in parsed:
                s0 = time.time_ns()
                if err:
                    result_text, exit_code = f"Error: {err}", None
                else:
                    r = tb.execute(name, args)
                    result_text, exit_code = r.text, r.exit_code
                s1 = time.time_ns()
                if name in ("run_command", "run_tests"):
                    last_exit_code = exit_code
                rtok = max(1, round(len(result_text) * tokens_per_char))
                b.timed_tool(s0, s1, span, name, args, result_text, result_tokens=rtok)
                tool_log.append({"seq": seq, "name": name, "args_hash": _h(canonical_args(args)),
                                 "result_hash": _h(result_text), "result_tokens": rtok,
                                 "read_type": name in READ_TOOLS})
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": result_text})
                new_otel.append({"role": "tool", "parts": [
                    {"type": "tool_call_response", "id": tc_id, "response": result_text}]})
                if name == "read_file" and not err and isinstance(args, dict) and args.get("path") \
                        and not result_text.startswith("Error:") and args["path"] not in opened:
                    opened.append(args["path"])
            if spec.reread_reminder and opened:
                note = spec.reread_reminder.format(files=", ".join(opened))
                messages.append({"role": "user", "content": note})
                new_otel.append({"role": "user", "parts": [{"type": "text", "content": note}]})
            continue

        if spec.continue_on_length and choice.finish_reason == "length":   # cut off mid-thought, not finished
            messages.append({"role": "user", "content": LENGTH_CONTINUE})
            new_otel.append({"role": "user", "parts": [{"type": "text", "content": LENGTH_CONTINUE}]})
            continue
        final_answer = text
        if spec.retry_prompt and last_exit_code not in (None, 0):   # naive retry wrapper: no exit condition
            messages.append({"role": "user", "content": spec.retry_prompt})
            new_otel.append({"role": "user", "parts": [{"type": "text", "content": spec.retry_prompt}]})
            continue
        stop_reason = "final_answer"
        break

    success, notes = (None, [])
    if spec.check is not None:
        success, notes = spec.check(ws.root)
    b.session_attrs[A.EXPERIMENT_TASK_SUCCESS] = success
    return SessionResult(
        session_id=spec.session_id, model=model, payload=b.otlp(), task_success=success, check_notes=notes,
        calls=b.seq, input_tokens=total_in, output_tokens=total_out, cache_read_reported=cache_reported,
        tool_calls=tool_log, stop_reason=stop_reason, workspace=ws.root, final_answer=final_answer)


def observed_signals(result: SessionResult) -> dict:
    """What the harness itself saw in the run, for the label file. Independent of
    the detectors (05), which never read the label file."""
    seen: set[str] = set()
    dup_results = 0
    for t in result.tool_calls:
        if t["result_hash"] in seen:
            dup_results += 1
        seen.add(t["result_hash"])
    # Longest streak of consecutive Calls each requesting the same (tool, args) with the same result.
    by_seq: dict[int, set[tuple]] = {}
    for t in result.tool_calls:
        by_seq.setdefault(t["seq"], set()).add((t["name"], t["args_hash"], t["result_hash"]))
    streak = best = 0
    prev = None
    for seq in range(result.calls):
        cur = tuple(sorted(by_seq.get(seq, ())))
        if cur and len(cur) == 1 and cur == prev:
            streak += 1
        else:
            streak = 1 if cur else 0
        best = max(best, streak)
        prev = cur if cur else None
    return {"duplicate_tool_results": dup_results, "max_identical_consecutive_tool_calls": best}
