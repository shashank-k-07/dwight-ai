"""Initiative detail: Waste Pattern breakdown panel. Owner: 09 (reads 05's WasteFindings).
Real from the store: WasteFindings of the Initiative's Sessions, summed per Waste Pattern.
Redundant Read / Cache Miss / Runaway Loop are Measured Waste, Model Overkill is an
Estimated Saving; each amount keeps the kind its findings carry (ADR 0006)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from dwight.api.contract import WasteBreakdown
from dwight.api.serving import Endpoint, get_conn, money

router = APIRouter()


def _from_store(conn, initiative_id: str) -> dict:
    rows = conn.execute(
        "SELECT w.pattern, w.kind, COUNT(*), COUNT(DISTINCT w.session_id), SUM(w.usd) "
        "FROM waste_findings w JOIN sessions s USING (session_id) WHERE s.initiative_id = ? "
        "GROUP BY w.pattern, w.kind ORDER BY SUM(w.usd) DESC", (initiative_id,)).fetchall()
    totals = {"measured": 0.0, "estimated": 0.0}
    patterns = []
    for pattern, kind, n, sessions, usd in rows:
        totals[kind] += usd or 0.0
        patterns.append({"pattern": pattern, "amount": money(usd, kind), "finding_count": n,
                         "session_count": sessions})
    return {"initiative_id": initiative_id, "measured_total": money(totals["measured"], "measured"),
            "estimated_total": money(totals["estimated"], "estimated"), "patterns": patterns}


initiative_waste = Endpoint("initiative_waste", WasteBreakdown, real=_from_store)


@router.get("/api/initiatives/{initiative_id}/waste", response_model=WasteBreakdown)
def get_initiative_waste(initiative_id: str, conn=Depends(get_conn)):
    return initiative_waste.serve(conn, key=initiative_id, initiative_id=initiative_id)
