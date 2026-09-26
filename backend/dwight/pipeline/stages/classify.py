"""Stage: classify (ticket 06).

The model reads each Session's staged prompt content and writes a redacted
one-line summary, an Initiative (picked from the known org.yaml Initiatives),
complexity and Discoveries; code builds the Trail from read-type tool calls.
Then the Session's raw content is DELETED from staging_content (ADRs 0005,
0008): Dwight keeps only the derived fields and the token metrics.

Reads:  sessions, calls, tool_calls, staging_content (the ONLY stage allowed to read it);
        data/company/org.yaml (Initiative ids, names, descriptions only)
Writes: sessions.{initiative_id, summary, complexity, classified_at}, trail_entries, discoveries,
        initiatives (every known Initiative, with session_count and spend_usd)
Never reads data/ground-truth/.

Idempotent: only Sessions that still have staged content are classified (staging is
deleted on success), each one's Trail and Discoveries are replaced, and the Initiative
totals are recomputed from sessions on every run.

  run classify                       every Session with staged content
  run classify --dataset synthetic   one dataset only (real | synthetic | fixture)
  run classify --session ID ...      only these Sessions (repeatable)
  run classify --limit 50            at most N Sessions (oldest first)
  run classify --workers 32          concurrent model calls (default 32, or DWIGHT_CLASSIFY_WORKERS)
  run classify --tier standard       model tier or name (default: round-robin over DWIGHT_GLM_MODEL_POOL)
  run classify --attempts 3          attempts per Session on API errors / invalid output
  run classify --thinking on         let the model reason first (default off, or DWIGHT_CLASSIFY_THINKING)
  run classify --totals-only         only recompute Initiative session_count / spend_usd

Model calls: 1 per Session (up to 3 if the JSON fails validation), plus retries on errors.
"""
from __future__ import annotations

import argparse

from dwight.classifier import run as runner
from dwight.classifier.model import candidates

ORDER = 20
TICKET = "06"
DESCRIPTION = ("Model reads staged prompt content -> summary, Initiative, complexity, Discoveries; "
               "code builds the Trail; then deletes staging")


def run(conn, args):
    p = argparse.ArgumentParser(prog="classify")
    p.add_argument("--session", action="append", dest="sessions", metavar="ID")
    p.add_argument("--dataset", choices=["real", "synthetic", "fixture"])
    p.add_argument("--limit", type=int)
    p.add_argument("--workers", type=int, default=runner.DEFAULT_WORKERS)
    p.add_argument("--tier")
    p.add_argument("--attempts", type=int, default=runner.DEFAULT_ATTEMPTS)
    p.add_argument("--totals-only", action="store_true")
    p.add_argument("--thinking", choices=["on", "off"], default="on" if runner.DEFAULT_THINKING else "off")
    ns = p.parse_args(args)

    cands = candidates()
    if ns.totals_only:
        runner.upsert_initiatives(conn, cands)
        runner.refresh_initiative_totals(conn)
        conn.commit()
        return f"recomputed totals for {len(cands)} Initiatives"
    ids = runner.pending_sessions(conn, session_ids=ns.sessions, dataset=ns.dataset, limit=ns.limit)
    stats = runner.classify_sessions(conn, ids, workers=ns.workers, tier=ns.tier, attempts=ns.attempts, cands=cands,
                                     thinking=ns.thinking == "on")
    return stats.line()
