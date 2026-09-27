"""Initiative detail: Recurring Discovery panel (both forms). Owner: 10.

Serves every recurring_discoveries row of the Initiative from the store: the
common_path rows (stage common_paths, ticket 10) and the repeated_discovery rows
(stage repeated_discoveries, ticket 11). Both costs are Measured; the repeated
Discovery's is labelled a conservative upper bound (build-spec §4.6.2).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from dwight import db
from dwight.api.contract import RecurringDiscoveries
from dwight.api.serving import Endpoint, get_conn, money
from dwight.pipeline.stages.common_paths import analysed_session_ids

router = APIRouter()

UPPER_BOUND = "conservative upper bound"


def _from_store(conn, initiative_id: str) -> dict:
    sessions = analysed_session_ids(conn, initiative_id)
    rows = db.rows(conn, "SELECT * FROM recurring_discoveries WHERE initiative_id=? "
                         "ORDER BY form='repeated_discovery', session_count DESC, recurring_discovery_id",
                   (initiative_id,))
    return {
        "initiative_id": initiative_id,
        "initiative_session_count": len(sessions),
        "items": [_item(r, _mean_tokens_per_read(conn, sessions, r)) for r in rows],
    }


def _mean_tokens_per_read(conn, sessions: list[str], row: dict) -> dict[str, int]:
    ids = row.get("resource_ids") or []
    if row["form"] != "common_path" or not ids or not sessions:
        return {}
    got = conn.execute(
        f"SELECT resource_id, AVG(tokens) FROM trail_entries WHERE resource_id IN ({','.join('?' * len(ids))}) "
        f"AND session_id IN ({','.join('?' * len(sessions))}) GROUP BY resource_id", (*ids, *sessions)).fetchall()
    return {rid: round(avg) for rid, avg in got}


def _item(r: dict, tokens_by_resource: dict[str, int]) -> dict:
    common = r["form"] == "common_path"
    return {
        "recurring_discovery_id": r["recurring_discovery_id"],
        "form": r["form"],
        "resources": [{"resource_id": rid, "tokens": tokens_by_resource.get(rid)}
                      for rid in (r.get("resource_ids") or [])] if common else [],
        "statement": r["statement"],
        "tokens": r["tokens"],
        "session_count": r["session_count"],
        "session_share": r["session_share"],
        "cost": money(r["spend_usd"], "measured", None if common else UPPER_BOUND),
        "evidence": r.get("evidence") or [],
    }


initiative_recurring = Endpoint("initiative_recurring_discoveries", RecurringDiscoveries, real=_from_store)


@router.get("/api/initiatives/{initiative_id}/recurring-discoveries", response_model=RecurringDiscoveries)
def get_recurring_discoveries(initiative_id: str, conn=Depends(get_conn)):
    return initiative_recurring.serve(conn, key=initiative_id, initiative_id=initiative_id)
