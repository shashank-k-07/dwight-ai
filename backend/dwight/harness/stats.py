"""Summary statistics of the real layer, for the synthetic generator (07) to calibrate against.

Computed by ingesting data/otlp/real/*.json into a throwaway in-memory store
(the normal ingest path, so the numbers are what Dwight itself sees), plus the
planted-pattern counts from the label file (pattern rates are generator inputs,
not detector inputs). Written to data/real_layer_stats.json.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

import yaml

from dwight import config, db
from dwight.harness.runner import LABELS_PATH, OTLP_REAL_DIR
from dwight.ingest.otlp import ingest_file

STATS_PATH = config.DATA_DIR / "real_layer_stats.json"


def _dist(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    s = sorted(xs)

    def q(p: float) -> float:
        return s[min(len(s) - 1, int(round(p * (len(s) - 1))))]

    return {"n": len(s), "min": s[0], "p10": q(0.10), "p50": q(0.50), "p90": q(0.90), "max": s[-1],
            "mean": round(statistics.fmean(s), 2)}


def compute(otlp_dir: Path = OTLP_REAL_DIR, labels_path: Path = LABELS_PATH) -> dict:
    conn = db.connect(":memory:")
    files = sorted(otlp_dir.glob("*.json"))
    for f in files:
        ingest_file(conn, f)
    labels = (yaml.safe_load(labels_path.read_text()) or {}).get("sessions", {}) if labels_path.exists() else {}

    sessions = db.rows(conn, "SELECT * FROM sessions")
    calls = db.rows(conn, "SELECT * FROM calls")
    tools = db.rows(conn, "SELECT t.*, c.session_id FROM tool_calls t JOIN calls c USING (call_id)")

    def group(rows: list[dict], key) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for r in rows:
            out.setdefault(key(r), []).append(r)
        return out

    def variant_of(sid: str) -> str:
        lab = labels.get(sid) or {}
        return lab.get("variant") or "unlabelled"

    def section(sids: set[str]) -> dict:
        ss = [s for s in sessions if s["session_id"] in sids]
        cs = [c for c in calls if c["session_id"] in sids]
        ts = [t for t in tools if t["session_id"] in sids]
        tools_per_call = Counter(t["call_id"] for t in ts)
        return {
            "sessions": len(ss),
            "calls_per_session": _dist([s["call_count"] for s in ss]),
            "input_tokens_per_call": _dist([c["input_tokens"] for c in cs]),
            "output_tokens_per_call": _dist([c["output_tokens"] for c in cs]),
            "input_tokens_per_session": _dist([s["total_input_tokens"] for s in ss]),
            "output_tokens_per_session": _dist([s["total_output_tokens"] for s in ss]),
            "prefix_tokens": _dist([c["prompt_prefix_tokens"] for c in cs if c["prompt_prefix_tokens"]]),
            "tool_calls_per_call": _dist([tools_per_call.get(c["call_id"], 0) for c in cs]),
            "tool_result_tokens": _dist([t["result_tokens"] for t in ts]),
            "tool_mix": dict(Counter(t["name"] for t in ts).most_common()),
            "spend_usd_per_session": _dist([round(s["spend_usd"], 6) for s in ss]),
            "spend_usd_total": round(sum(s["spend_usd"] for s in ss), 6),
        }

    all_ids = {s["session_id"] for s in sessions}
    by_variant = group(sessions, lambda s: variant_of(s["session_id"]))
    planted = Counter((labels.get(s["session_id"]) or {}).get("planted_pattern", "unlabelled") for s in sessions)
    n = len(sessions) or 1
    return {
        "source": f"{otlp_dir.relative_to(config.REPO_ROOT) if otlp_dir.is_relative_to(config.REPO_ROOT) else otlp_dir}"
                  f" ({len(files)} files), ingested with dwight.ingest.otlp",
        "models": dict(Counter(c["model"] for c in calls).most_common()),
        "cache": {
            "calls_with_cache_read": sum(1 for c in calls if c["cache_read_tokens"] > 0),
            "calls": len(calls),
            "note": "Sciforium's API returned no cached-token fields (usage.prompt_tokens_details is null), "
                    "so cache_read_tokens is 0 on every real Call. Do not calibrate cache-hit rates from this.",
        },
        "experiments": dict(Counter(s["experiment"] or "none" for s in sessions)),
        "pattern_rates": {k: {"sessions": v, "share": round(v / n, 3)} for k, v in sorted(planted.items())},
        "all": section(all_ids),
        "by_variant": {v: section({s["session_id"] for s in rows}) for v, rows in sorted(by_variant.items())},
    }


def write(path: Path = STATS_PATH, **kw) -> dict:
    stats = compute(**kw)
    path.write_text(json.dumps(stats, indent=1) + "\n")
    return stats
