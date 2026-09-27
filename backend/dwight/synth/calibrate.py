"""Fit the generator's Session shapes to the real layer (ticket 03's harness runs).

Reads real-layer OTLP (default data/otlp/real/) through the normal ingest into a
throwaway store, measures call/tool/token distributions, and writes
data/synthetic/calibration.yaml. params.load() overlays its `overrides` on
params.yaml, so recalibrating is:

    python -m dwight.synth calibrate && python -m dwight.synth build --ingest

Waste Pattern rates can't be measured without 03's label file, so they are only
changed with `--rates-from <yaml>` ({redundant_read: 0.1, cache_miss: 0.2,
runaway_loop: 0.05}, applied as the kestrel-devagent rate, since the real
harness is a coding agent). Note that the real layer over-represents planted
runs, so its raw pattern rates are an upper bound, not a company-wide rate.
"""
from __future__ import annotations

import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from dwight import config, db
from dwight.ingest.otlp import ingest_file
from dwight.synth.params import CALIBRATION_PATH, REAL_OTLP_DIR

READ_HINTS = ("read", "get_page", "fetch", "cat", "open")


def _q(xs: list[float], q: float) -> int:
    if not xs:
        return 0
    xs = sorted(xs)
    return int(round(xs[min(len(xs) - 1, max(0, int(q * (len(xs) - 1) + 0.5)))]))


def _p(xs: list[float]) -> dict:
    return {"p10": _q(xs, .1), "p50": _q(xs, .5), "p90": _q(xs, .9)}


def _uniform(p: dict) -> list[int] | None:
    """A [min, max] range for uniform sampling whose mean is the real median:
    [p10, 2*p50 - p10] (the real distributions are right-skewed, so [p10, p90]
    would overstate the mean)."""
    if not p["p50"]:
        return None
    lo = max(1, p["p10"])
    return [lo, max(lo + 1, 2 * p["p50"] - lo)]


def measure(paths: list[Path]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        conn = db.connect(Path(tmp) / "calibrate.sqlite")
        files = [f for p in paths for f in ([p] if p.is_file() else sorted(p.rglob("*.json")) + sorted(p.rglob("*.jsonl")))]
        for f in files:
            ingest_file(conn, f)
        sessions = db.rows(conn, "SELECT session_id, call_count FROM sessions WHERE dataset='real'")
        calls = db.rows(conn, "SELECT c.call_id, c.session_id, c.seq, c.output_tokens, c.prompt_prefix_tokens, "
                              "c.cache_read_tokens, (SELECT COUNT(*) FROM tool_calls t WHERE t.call_id=c.call_id) AS n_tools "
                              "FROM calls c JOIN sessions s USING(session_id) WHERE s.dataset='real'")
        tools = db.rows(conn, "SELECT t.name, t.result_tokens, c.session_id FROM tool_calls t JOIN calls c USING(call_id) "
                              "JOIN sessions s USING(session_id) WHERE s.dataset='real'")
        conn.close()
    is_read = lambda name: any(h in name.lower() for h in READ_HINTS)  # noqa: E731
    work_per_session: dict[str, int] = {s["session_id"]: 0 for s in sessions}
    for t in tools:
        if not is_read(t["name"]):
            work_per_session[t["session_id"]] = work_per_session.get(t["session_id"], 0) + 1
    work = list(work_per_session.values())
    out_tool = [c["output_tokens"] for c in calls if c["n_tools"]]
    out_final = [c["output_tokens"] for c in calls if not c["n_tools"]]
    cmd_tokens = [t["result_tokens"] for t in tools if not is_read(t["name"])]
    prefix = [c["prompt_prefix_tokens"] for c in calls if c["prompt_prefix_tokens"]]
    return {
        "files": len(files), "sessions": len(sessions), "calls": len(calls), "tool_calls": len(tools),
        "calls_per_session": {"p10": _q([s["call_count"] for s in sessions], .1),
                              "p50": _q([s["call_count"] for s in sessions], .5),
                              "p90": _q([s["call_count"] for s in sessions], .9)},
        "work_steps_per_session": {q: _q(work, v) for q, v in (("p25", .25), ("p60", .6), ("p95", .95))},
        "output_tokens_tool_call": _p(out_tool),
        "output_tokens_final": _p(out_final),
        "command_result_tokens": _p(cmd_tokens),
        "prefix_tokens_median": int(statistics.median(prefix)) if prefix else None,
        "calls_with_cache_reads": round(sum(1 for c in calls if c["cache_read_tokens"]) / len(calls), 3) if calls else None,
    }


def overrides_from(stats: dict, rates: dict | None = None) -> dict:
    """Map real-layer stats onto params. The real harness runs med-complexity tasks
    against a small repo, so it sets the med Session length and the per-Call token
    shapes; low/high lengths and each agent's prompt prefix (the harness's ~0.7K
    system prompt is not kestrel-devagent's) keep their params.yaml defaults."""
    o: dict = {}
    if stats["sessions"] < 5:
        return o
    shapes: dict = {}
    w = stats["work_steps_per_session"]
    if w["p95"] > 0:
        shapes["med"] = {"work_steps": [max(2, w["p25"]), max(3, w["p95"])]}
    ot = {k: r for k, r in (("tool_call", _uniform(stats["output_tokens_tool_call"])),
                            ("final", _uniform(stats["output_tokens_final"]))) if r}
    if ot:
        shapes["output_tokens"] = ot
    cmd = _uniform(stats["command_result_tokens"])
    if cmd:
        shapes["result_tokens"] = {"command": cmd}
    if shapes:
        o["shapes"] = shapes
    for name, r in (rates or {}).items():
        o.setdefault("waste_rates", {})[name] = {"agents": {"kestrel-devagent": float(r)}}
    return o


def calibrate(paths: list[Path] | None = None, rates_from: Path | None = None,
              out: Path = CALIBRATION_PATH) -> dict:
    paths = paths or [REAL_OTLP_DIR]
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError(f"no real-layer OTLP at {missing}; run ticket 03's harness first")
    stats = measure(paths)
    rates = yaml.safe_load(Path(rates_from).read_text()) if rates_from else None
    rel = lambda p: str(Path(p).resolve().relative_to(config.REPO_ROOT)) if Path(p).resolve().is_relative_to(config.REPO_ROOT) else str(p)  # noqa: E731
    doc = {"source": {"paths": [rel(p) for p in paths], "measured_at": datetime.now(timezone.utc).isoformat(),
                      "rates_from": rel(rates_from) if rates_from else None},
           "stats": stats, "overrides": overrides_from(stats, rates)}
    out.write_text("# Written by `python -m dwight.synth calibrate`. Overlays params.yaml.\n"
                   + yaml.safe_dump(doc, sort_keys=False))
    return doc
