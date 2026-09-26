"""Stage: common_paths (ticket 10, build-spec §4.6.1).

Per Initiative, the share of its Sessions whose Trail contains each resource.
Resources in >= 60% of Sessions (configurable) form the common path: one
RecurringDiscovery(form='common_path') per Initiative. Single resources only;
resource-set itemsets are on the cut list.

Reads:  trail_entries, sessions (initiative_id, experiment), calls (model, cache reads)
Writes: recurring_discoveries WHERE form='common_path' (its own rows only; the
        repeated_discovery rows belong to ticket 11)

Only stored Trails, never prompt content (ADRs 0005, 0008): this stage does not
touch staging_content.

  run common_paths [--threshold 0.6] [--min-sessions 3] [--initiative ID ...]
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from dwight import db, pricing

ORDER = 40
TICKET = "10"
DESCRIPTION = "Per Initiative: resources read in >= 60% of Sessions -> RecurringDiscovery(form=common_path), Measured"

DEFAULT_THRESHOLD = 0.6
DEFAULT_MIN_SESSIONS = 3


def analysed_session_ids(conn, initiative_id: str) -> list[str]:
    """The Sessions cross-session analysis runs over: the Initiative's Sessions minus
    experiment='after' runs, which ran with the Draft loaded and would dilute the share.
    The API's `initiative_session_count` uses the same population."""
    return [r["session_id"] for r in db.rows(
        conn, "SELECT session_id FROM sessions WHERE initiative_id=? AND COALESCE(experiment, '') != 'after' "
              "ORDER BY session_id", (initiative_id,))]


def read_cost(calls: list[dict], call_seq: int, tokens: int) -> float:
    """Measured USD a read of `tokens` result tokens cost the Session. The same rule as
    Redundant Read (build-spec §4.2): the result is requested by Call `call_seq` and enters
    the context of every later Call, and each of those Calls is billed for it at the input
    rate that Call actually paid. That is the uncached rate on the first Call to carry it
    (the tokens are new there), then the cache-read rate on a later Call if caching was on
    for that Call (cache_read_tokens > 0), else the uncached rate again. Each Call is
    priced at its own model. A read requested by the last Call enters no billed Call.

    `calls`: the Session's Calls as dicts with seq, model, cache_read_tokens, in seq order."""
    carrying = [c for c in calls if c["seq"] > call_seq]
    usd = 0.0
    for i, c in enumerate(carrying):
        cached = i > 0 and c["cache_read_tokens"] > 0
        usd += tokens * pricing.input_rate(c["model"], cached=cached)
    return usd


def mean_tokens_per_read(trail: list[dict], resource_id: str) -> float:
    reads = [t["tokens"] for t in trail if t["resource_id"] == resource_id]
    return sum(reads) / len(reads) if reads else 0.0


def common_path_id(initiative_id: str) -> str:
    return f"rd-cp-{initiative_id}"


def run(conn, args):
    p = argparse.ArgumentParser(prog="common_paths")
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                   help="minimum share of the Initiative's Sessions whose Trail contains a resource (default 0.6)")
    p.add_argument("--min-sessions", type=int, default=DEFAULT_MIN_SESSIONS,
                   help="skip Initiatives with fewer analysed Sessions (default 3)")
    p.add_argument("--initiative", action="append", help="only this Initiative (repeatable); default all")
    ns = p.parse_args(args)

    initiatives = ns.initiative or [r["initiative_id"] for r in db.rows(
        conn, "SELECT DISTINCT initiative_id FROM sessions WHERE initiative_id IS NOT NULL ORDER BY 1")]
    if not ns.initiative:  # full run: also clears rows of Initiatives that no longer have Sessions
        conn.execute("DELETE FROM recurring_discoveries WHERE form='common_path'")
    written = []
    for iid in initiatives:
        conn.execute("DELETE FROM recurring_discoveries WHERE form='common_path' AND initiative_id=?", (iid,))
        row = _common_path(conn, iid, ns.threshold, ns.min_sessions)
        if row is None:
            continue
        conn.execute(
            "INSERT INTO recurring_discoveries (recurring_discovery_id, initiative_id, form, resource_ids_json, "
            "statement, tokens, session_count, session_share, spend_usd, evidence_json) "
            "VALUES (?, ?, 'common_path', ?, NULL, ?, ?, ?, ?, ?)",
            (row["recurring_discovery_id"], iid, db.dumps(row["resource_ids"]), row["tokens"],
             row["session_count"], row["session_share"], row["spend_usd"], db.dumps(row["evidence"])))
        written.append(f"{iid} ({len(row['resource_ids'])} resources, {row['session_count']} Sessions)")
    conn.commit()
    return f"{len(written)} common paths over {len(initiatives)} Initiatives" + (": " + "; ".join(written) if written else "")


def _common_path(conn, initiative_id: str, threshold: float, min_sessions: int) -> dict | None:
    sessions = analysed_session_ids(conn, initiative_id)
    if len(sessions) < max(min_sessions, 1):
        return None
    marks = ",".join("?" * len(sessions))
    trail = db.rows(conn, f"SELECT session_id, resource_id, tokens, call_seq FROM trail_entries "
                          f"WHERE session_id IN ({marks}) ORDER BY session_id, position", tuple(sessions))
    readers: dict[str, set[str]] = defaultdict(set)
    for t in trail:
        readers[t["resource_id"]].add(t["session_id"])
    common = sorted(r for r, ss in readers.items() if len(ss) / len(sessions) >= threshold)
    if not common:
        return None
    evidence = sorted(set.intersection(*(readers[r] for r in common)))

    calls: dict[str, list[dict]] = defaultdict(list)
    for c in db.rows(conn, f"SELECT session_id, seq, model, cache_read_tokens FROM calls "
                           f"WHERE session_id IN ({marks}) ORDER BY session_id, seq", tuple(sessions)):
        calls[c["session_id"]].append(c)
    # Σ over every analysed Session of every Trail read of a common-path resource
    # (including Sessions that read only part of the path, and re-reads).
    spend = sum(read_cost(calls[t["session_id"]], t["call_seq"], t["tokens"])
                for t in trail if t["resource_id"] in common)
    return {
        "recurring_discovery_id": common_path_id(initiative_id),
        "resource_ids": common,
        # one read of the whole path: sum of each resource's mean tokens per read
        "tokens": round(sum(mean_tokens_per_read(trail, r) for r in common)),
        "session_count": len(evidence),
        "session_share": len(evidence) / len(sessions),
        "spend_usd": spend,
        "evidence": evidence,
    }
