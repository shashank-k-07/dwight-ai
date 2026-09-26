"""Initiative detail: Waste Pattern breakdown panel. Owner: 09 (reads 05's WasteFindings).
FIXTURE until real=... is set."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from dwight.api.contract import WasteBreakdown
from dwight.api.serving import Endpoint, get_conn

router = APIRouter()

initiative_waste = Endpoint("initiative_waste", WasteBreakdown, real=None)


@router.get("/api/initiatives/{initiative_id}/waste", response_model=WasteBreakdown)
def get_initiative_waste(initiative_id: str, conn=Depends(get_conn)):
    return initiative_waste.serve(conn, key=initiative_id, initiative_id=initiative_id)
