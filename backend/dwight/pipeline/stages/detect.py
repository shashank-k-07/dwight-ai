"""Stage: detect (ticket 05). Waste Pattern detectors, build-spec §4.2.

Reads:  calls, tool_calls, sessions.complexity, prices (dwight.pricing)
Writes: waste_findings (replaces all rows for the Sessions processed, so re-running is safe)

Tool calls on Call k are those it REQUESTED; their results enter the input of
Call k+1 onward. Never reads the planted-pattern label file.

  run detect                          every Session in the store
  run detect --session fx-rr-01 ...   only these Sessions
  run detect --loop-min 4             Runaway Loop needs >= N consecutive identical Calls (default 3)
  run detect --cache-miss-ratio 0.5   Cache Miss when cache_read < ratio x shared prefix (default 0.5)
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from dwight import pricing
from dwight.db import dumps

ORDER = 30
TICKET = "05"
DESCRIPTION = "Waste detectors: Redundant Read, Cache Miss, Runaway Loop (Measured), Model Overkill (Estimated)"


@dataclass(frozen=True)
class ToolCall:
    name: str
    args_hash: str | None
    result_hash: str | None
    result_tokens: int


@dataclass
class Call:
    call_id: str
    seq: int
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    prompt_prefix_hash: str | None = None
    prompt_prefix_tokens: int | None = None
    tools: list[ToolCall] = field(default_factory=list)  # requested by this Call, in order


@dataclass
class Finding:
    pattern: str   # redundant_read | cache_miss | runaway_loop | model_overkill
    kind: str      # measured | estimated
    usd: float
    evidence: list[str]  # Call IDs
    detail: str


CACHE_MISS_RATIO = 0.5  # "much smaller than the shared prefix": cache_read < ratio x prefix
LOOP_MIN = 3            # Runaway Loop: >= N consecutive identical Calls


def find_waste(calls: list[Call], complexity: str | None, *,
               loop_min: int = LOOP_MIN, cache_miss_ratio: float = CACHE_MISS_RATIO) -> list[Finding]:
    """All WasteFindings for one Session's Calls. Pure arithmetic on token counts
    and prices; Model Overkill additionally uses the classifier's `complexity`.

    A Call priced in full by a Runaway Loop is not priced again by Redundant Read or
    Cache Miss, and a loop's repeated results are not Redundant Reads, so Measured
    Waste never counts the same dollars twice."""
    calls = sorted(calls, key=lambda c: c.seq)
    loops = _runaway_loops(calls, loop_min)
    in_loop = {cid for f in loops for cid in f.evidence[1:]}  # the Calls a loop prices
    return (_redundant_reads(calls, in_loop) + _cache_misses(calls, cache_miss_ratio, in_loop) + loops
            + _model_overkill(calls, complexity))


def _cached(c: Call) -> bool:
    """Caching is on for this Call if it read anything from the prompt cache."""
    return c.cache_read_tokens > 0


def _redundant_reads(calls: list[Call], in_loop: set[str]) -> list[Finding]:
    """A tool result whose result_hash already appeared earlier in the Session. The
    duplicate copy is billed again on every Call from where it enters the context
    (Call k+1) to the end of the Session: at the uncached rate on the first of those
    Calls, and at the rate that Call actually paid (cache-read if caching is on)
    after that."""
    out: list[Finding] = []
    seen: dict[str, int] = {}  # result_hash -> seq of the Call that first requested it
    for i, c in enumerate(calls):
        for t in c.tools:
            if not t.result_hash:
                continue
            if t.result_hash not in seen:
                seen[t.result_hash] = c.seq
                continue
            if c.call_id in in_loop:
                continue  # a loop's repeat: the Runaway Loop finding prices it
            billed = [(j, b) for j, b in enumerate(calls[i + 1:]) if b.call_id not in in_loop]
            usd = sum(t.result_tokens * pricing.input_rate(b.model, cached=(j > 0 and _cached(b)))
                      for j, b in billed)
            if usd > 0:
                out.append(Finding(
                    "redundant_read", "measured", usd, [c.call_id] + [b.call_id for _, b in billed],
                    f"{t.name} result already seen on Call {seen[t.result_hash]} "
                    f"({t.result_tokens} tokens, re-sent on {len(billed)} Calls)"))
    return out


def _cache_misses(calls: list[Call], ratio: float, in_loop: set[str]) -> list[Finding]:
    """A Call whose prompt_prefix_hash matches the previous Call's (same model), but
    whose cache_read_tokens is much smaller than the shared prefix. Priced as
    (shared prefix - cache read) x (uncached - cached input price). One finding
    per Session, evidence = the Calls that missed. Skipped for models whose provider
    never reports cache reads (prices.yaml reports_cache_usage: false): a zero there is
    not evidence of a miss, so Cache Miss is not observable on them."""
    usd, missed = 0.0, []
    for prev, c in zip(calls, calls[1:]):
        prefix = c.prompt_prefix_tokens or 0
        if (not pricing.reports_cache_usage(c.model) or c.call_id in in_loop or not c.prompt_prefix_hash or c.prompt_prefix_hash != prev.prompt_prefix_hash
                or pricing.normalise_model(c.model) != pricing.normalise_model(prev.model)
                or prefix <= 0 or c.cache_read_tokens >= ratio * prefix):
            continue
        cost = (prefix - c.cache_read_tokens) * (pricing.input_rate(c.model, cached=False)
                                                 - pricing.input_rate(c.model, cached=True))
        if cost > 0:
            usd += cost
            missed.append(c.call_id)
    if not missed:
        return []
    return [Finding("cache_miss", "measured", usd, missed,
                    f"{len(missed)} Calls reused the previous Call's prompt prefix but missed the cache")]


def _action(c: Call) -> tuple | None:
    """What a Call asked for: the set of distinct (tool name, args hash) it requested,
    or None if it asked for nothing or we can't tell (a missing hash). A set, because
    models often repeat the same tool call inside one Call (ticket 03's real runs send
    1-3 identical run_tests per Call); that is still the same action."""
    if not c.tools or any(not t.args_hash or not t.result_hash for t in c.tools):
        return None
    return frozenset((t.name, t.args_hash) for t in c.tools)


def _runaway_loops(calls: list[Call], n: int) -> list[Finding]:
    """>= n consecutive Calls requesting the same tool name + args hash and getting
    no new result hash. The first Call of the run is legitimate work; the Spend of
    every Call after it is Waste. Evidence = every Call in the run."""
    out: list[Finding] = []
    i = 0
    while i < len(calls):
        action = _action(calls[i])
        j = i + 1
        if action is not None:
            results = {t.result_hash for t in calls[i].tools}
            while (j < len(calls) and _action(calls[j]) == action
                   and {t.result_hash for t in calls[j].tools} <= results):
                j += 1
        run = calls[i:j]
        if action is not None and len(run) >= max(n, 2):
            usd = sum(_spend(c) for c in run[1:])
            names = ", ".join(sorted({t.name for t in run[0].tools}))
            out.append(Finding("runaway_loop", "measured", usd, [c.call_id for c in run],
                               f"{len(run)} consecutive identical {names} calls with no new result"))
        i = j
    return out


def _model_overkill(calls: list[Call], complexity: str | None) -> list[Finding]:
    """The classifier judged the Session low complexity and it ran on the flagship
    tier: Session Spend minus the same tokens priced at the cheaper tier's model.
    Estimated (it rests on the classifier's judgement, ADR 0006). Calls on a model
    with no cheaper model (e.g. the light real-layer pool models) are not re-priced."""
    if complexity != "low":
        return []
    usd, evidence, targets = 0.0, [], set()
    for c in calls:
        cheaper = pricing.cheaper_model(c.model)
        if pricing.price(c.model).tier != "flagship" or cheaper is None:
            continue
        usd += _spend(c) - _spend(c, cheaper)
        evidence.append(c.call_id)
        targets.add((pricing.normalise_model(c.model), cheaper))
    if usd <= 0:
        return []
    detail = "; ".join(f"{m} re-priced at {ch}" for m, ch in sorted(targets))
    return [Finding("model_overkill", "estimated", usd, evidence, f"low-complexity Session: {detail}")]


def _spend(c: Call, model: str | None = None) -> float:
    return pricing.call_spend(model or c.model, c.input_tokens, c.output_tokens,
                              c.cache_read_tokens, c.cache_write_tokens)


def load_calls(conn, session_id: str) -> list[Call]:
    calls = {r["call_id"]: Call(
        call_id=r["call_id"], seq=r["seq"], model=r["model"], input_tokens=r["input_tokens"],
        output_tokens=r["output_tokens"], cache_read_tokens=r["cache_read_tokens"],
        cache_write_tokens=r["cache_write_tokens"], prompt_prefix_hash=r["prompt_prefix_hash"],
        prompt_prefix_tokens=r["prompt_prefix_tokens"])
        for r in conn.execute("SELECT * FROM calls WHERE session_id=? ORDER BY seq", (session_id,))}
    for t in conn.execute("SELECT t.* FROM tool_calls t JOIN calls c ON c.call_id = t.call_id "
                          "WHERE c.session_id=? ORDER BY c.seq, t.idx", (session_id,)):
        calls[t["call_id"]].tools.append(ToolCall(t["name"], t["args_hash"], t["result_hash"], t["result_tokens"]))
    return list(calls.values())


def run(conn, args):
    p = argparse.ArgumentParser(prog="detect")
    p.add_argument("--session", action="append", help="only this Session (repeatable); default: all")
    p.add_argument("--loop-min", type=int, default=LOOP_MIN, help=f"Runaway Loop length N (default {LOOP_MIN})")
    p.add_argument("--cache-miss-ratio", type=float, default=CACHE_MISS_RATIO,
                   help=f"Cache Miss when cache_read < ratio x shared prefix (default {CACHE_MISS_RATIO})")
    ns = p.parse_args(args)
    sessions = conn.execute("SELECT session_id, complexity FROM sessions ORDER BY session_id").fetchall()
    if ns.session:
        sessions = [s for s in sessions if s["session_id"] in set(ns.session)]
    totals = {"measured": 0.0, "estimated": 0.0}
    n = 0
    for s in sessions:
        sid = s["session_id"]
        found = find_waste(load_calls(conn, sid), s["complexity"],
                           loop_min=ns.loop_min, cache_miss_ratio=ns.cache_miss_ratio)
        conn.execute("DELETE FROM waste_findings WHERE session_id=?", (sid,))
        for k, f in enumerate(found):
            conn.execute("INSERT INTO waste_findings (finding_id, session_id, pattern, kind, usd, evidence_json, detail)"
                         " VALUES (?,?,?,?,?,?,?)",
                         (f"wf-{sid}-{k}", sid, f.pattern, f.kind, f.usd, dumps(f.evidence), f.detail))
            totals[f.kind] += f.usd
        n += len(found)
    conn.commit()
    return (f"{n} findings on {len(sessions)} Sessions: ${totals['measured']:.4f} Measured Waste, "
            f"${totals['estimated']:.4f} Estimated Saving")
