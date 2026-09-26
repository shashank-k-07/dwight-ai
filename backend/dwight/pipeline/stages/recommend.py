"""Stage: recommend (ticket 09).

Recommendation engine: findings + RecurringDiscoveries + Practice Library + Infra Profile ->
Recommendations. GLM picks the Practice and writes the wording; code validates it and prices it
(see dwight/recommend/engine.py).

Reads:  waste_findings, recurring_discoveries, initiatives, sessions, calls, trail_entries,
        data/company/practices.yaml, data/company/infra_profile.yaml
Writes: recommendations (usd + kind attached by code, never by GLM)
        - one set per Initiative with findings or RecurringDiscoveries (target_type=initiative)
        - one set per Team with Model Overkill findings: a Policy (target_type=policy, with
          suggested_models for the Policy screen) plus optionally a target_type=team one
Output without a real, eligible practice_id and >= 1 real Infra Profile ref, or with a dollar
figure in it, is rejected and retried.

Idempotent: each processed target's rows are deleted and re-inserted. Recommendation ids are
stable (r-<target>-<practice_id>), and a Draft already attached by the draft stage (12) keeps
its draft_id, usd and kind across a re-run.

  run recommend                         every Initiative + every Team with Model Overkill
  run recommend --initiative ID [...]   only these Initiatives (no Teams)
  run recommend --no-teams              skip the Team / Policy pass
  run recommend --no-glm                write the plain Practice-text fallback (offline dev)
  run recommend --tier standard --workers 4
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor

from dwight import db
from dwight.db import dumps
from dwight.recommend import engine

ORDER = 60
TICKET = "09"
DESCRIPTION = "Recommendation engine: findings + RecurringDiscoveries + Practice Library + Infra Profile -> Recommendations (GLM writes, code prices)"


def _glm_chat_json():
    from dwight import glm
    return glm.chat_json


def run(conn, args):
    p = argparse.ArgumentParser(prog="recommend")
    p.add_argument("--initiative", nargs="+", default=None)
    p.add_argument("--no-teams", action="store_true")
    p.add_argument("--no-glm", action="store_true")
    p.add_argument("--tier", default=None)
    p.add_argument("--workers", type=int, default=4)
    ns = p.parse_args(args)

    targets = engine.collect_initiatives(conn, ns.initiative)
    full_run = ns.initiative is None
    if full_run and not ns.no_teams:
        targets += engine.collect_teams(conn)
    chat_json = None if ns.no_glm else _glm_chat_json()

    def work(t):
        return t, *engine.write_recommendations(t, chat_json=chat_json, tier=ns.tier)

    with ThreadPoolExecutor(max_workers=max(1, ns.workers)) as pool:
        results = list(pool.map(work, targets))

    n_recs = n_fallback = n_rejected = 0
    for target, rows, stats in results:
        store(conn, target, rows)
        n_recs += len(rows)
        n_fallback += stats["fallbacks"]
        n_rejected += stats["rejected"]
    if full_run:
        _delete_stale(conn, [t for t, _, _ in results], teams=not ns.no_teams)
    conn.commit()
    n_ini = sum(1 for t in targets if t.target_type == "initiative")
    msg = (f"{n_recs} Recommendations for {n_ini} Initiatives and {len(targets) - n_ini} Teams; "
           f"{n_rejected} GLM outputs rejected and retried; {n_fallback} fallback Recommendations")
    return msg + (" (--no-glm)" if ns.no_glm else "")


def _target_where(target) -> tuple[str, tuple]:
    if target.target_type == "team":
        return "target_type IN ('team', 'policy') AND target_id = ?", (target.target_id,)
    return "target_type = 'initiative' AND target_id = ?", (target.target_id,)


def store(conn, target, rows: list[dict]) -> None:
    """Replace one target's Recommendations. Keeps a Draft attached by stage 12."""
    where, params = _target_where(target)
    kept = {r["recommendation_id"]: r for r in db.rows(
        conn, f"SELECT recommendation_id, draft_id, usd, kind FROM recommendations WHERE {where} "
              f"AND draft_id IS NOT NULL", params)}
    conn.execute(f"DELETE FROM recommendations WHERE {where}", params)
    rows = sorted(rows, key=lambda r: -r["usd"])
    for rank, r in enumerate(rows):
        rid = engine.recommendation_id(r)
        draft_id, usd, kind = None, r["usd"], r["kind"]
        if rid not in kept:  # a Draft that already points at this id (12 writes drafts.recommendation_id)
            d = conn.execute("SELECT draft_id FROM drafts WHERE recommendation_id = ?", (rid,)).fetchone()
            draft_id = d[0] if d else None
        else:
            draft_id, usd, kind = kept[rid]["draft_id"], kept[rid]["usd"], kept[rid]["kind"]
        conn.execute(
            "INSERT INTO recommendations (recommendation_id, target_type, target_id, practice_id, title, body, "
            "infra_refs_json, usd, kind, draft_id, recurring_discovery_id, suggested_models_json, rank) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, r["target_type"], r["target_id"], r["practice_id"], r["title"], r["body"], dumps(r["infra_refs"]),
             usd, kind, draft_id, r["recurring_discovery_id"],
             dumps(r["suggested_models"]) if r["suggested_models"] is not None else None, rank))


def _delete_stale(conn, targets, teams: bool) -> None:
    """On a full run, drop Recommendations for targets that no longer have anything to fix."""
    inis = [t.target_id for t in targets if t.target_type == "initiative"]
    conn.execute(f"DELETE FROM recommendations WHERE target_type = 'initiative' "
                 f"AND target_id NOT IN ({','.join('?' * len(inis))})", inis)
    if teams:
        tms = [t.target_id for t in targets if t.target_type == "team"]
        conn.execute(f"DELETE FROM recommendations WHERE target_type IN ('team', 'policy') "
                     f"AND target_id NOT IN ({','.join('?' * len(tms))})", tms)
