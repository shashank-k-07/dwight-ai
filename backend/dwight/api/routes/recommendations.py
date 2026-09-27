"""Recommendations. Owner: 09 (12 sets draft_id, 13 fills measured_drop, 14 reads policy_prefill).
Real from the store (the recommend stage writes the rows; usd + kind come from code, never GLM)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from dwight import db
from dwight.api.contract import RecommendationList
from dwight.api.routes.before_after import attach_measured_drops
from dwight.api.serving import Endpoint, get_conn, money
from dwight.policy_export import prefill
from dwight.recommend.library import practice_title

router = APIRouter()

TARGET_TYPES = ("initiative", "team", "policy")


def overlap_group(r: dict, form: str | None) -> str:
    """Recommendations in one group remove the same Waste, so their savings don't add up (the
    simulation counts the largest one). A Recurring Discovery fix is grouped by its target and form:
    the memory-file Draft is priced on ALL of the Initiative's repeated Discoveries, which overlap
    any single-Discovery fix, and every common-path fix removes the same reads. Any other fix is
    grouped with the ones the engine priced as the same Waste (same target, kind and figure)."""
    if form:
        return f"{r['target_type']}:{r['target_id']}:{form}"
    return f"{r['target_type']}:{r['target_id']}:{r['kind']}:{round(r['usd'], 8)}"


def to_contract(conn, rows: list[dict]) -> list[dict]:
    """recommendations rows -> contract Recommendation dicts."""
    forms = dict(conn.execute("SELECT recurring_discovery_id, form FROM recurring_discoveries").fetchall())
    out, seen = [], set()
    for r in rows:
        notes = []
        if forms.get(r["recurring_discovery_id"]) == "repeated_discovery":
            notes.append("conservative upper bound")
        # Recommendations fixing the same Waste carry the same figure (engine prices per Group).
        group = (r["target_type"], r["target_id"], r["recurring_discovery_id"], r["kind"], round(r["usd"], 8))
        if group in seen:
            notes.append("same Waste as above, not additive")
        seen.add(group)
        note = "; ".join(notes) or None
        out.append({
            "recommendation_id": r["recommendation_id"],
            "target_type": r["target_type"],
            "target_id": r["target_id"],
            "practice": {"practice_id": r["practice_id"], "title": practice_title(r["practice_id"])},
            "title": r["title"],
            "body": r["body"],
            "infra_refs": r["infra_refs"] or [],
            "saving": money(r["usd"], r["kind"], note),
            "draft_id": r["draft_id"],
            "recurring_discovery_id": r["recurring_discovery_id"],
            "overlap_group": overlap_group(r, forms.get(r["recurring_discovery_id"])),
            "measured_drop": None,
            "policy_prefill": prefill(r["target_id"], r["suggested_models"])
            if r["target_type"] in ("team", "policy") else None,
        })
    return attach_measured_drops(conn, out)


def _initiative_from_store(conn, initiative_id: str) -> dict:
    rows = db.rows(conn, "SELECT * FROM recommendations WHERE target_type = 'initiative' AND target_id = ? "
                         "ORDER BY rank, usd DESC", (initiative_id,))
    return {"items": to_contract(conn, rows)}


def _all_from_store(conn, target_type: Optional[str] = None) -> dict:
    if target_type in TARGET_TYPES:
        rows = db.rows(conn, "SELECT * FROM recommendations WHERE target_type = ? ORDER BY usd DESC", (target_type,))
    else:
        rows = db.rows(conn, "SELECT * FROM recommendations ORDER BY target_type, target_id, rank")
    return {"items": to_contract(conn, rows)}


initiative_recommendations = Endpoint("initiative_recommendations", RecommendationList, real=_initiative_from_store)
recommendations = Endpoint("recommendations", RecommendationList, real=_all_from_store)


@router.get("/api/initiatives/{initiative_id}/recommendations", response_model=RecommendationList)
def list_initiative_recommendations(initiative_id: str, conn=Depends(get_conn)):
    return initiative_recommendations.serve(conn, key=initiative_id, initiative_id=initiative_id)


@router.get("/api/recommendations", response_model=RecommendationList)
def list_recommendations(target_type: Optional[str] = None, conn=Depends(get_conn)):
    """All Recommendations, optionally filtered by target_type (team | policy | initiative).
    The fixture ignores the filter."""
    return recommendations.serve(conn, target_type=target_type)
