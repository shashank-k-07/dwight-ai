"""Initiative detail: before/after panel. Owner: 13. Must compute from stored
Sessions tagged dwight.experiment=before|after. FIXTURE until real=... is set."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from dwight.api.contract import BeforeAfter
from dwight.api.serving import Endpoint, get_conn

router = APIRouter()

initiative_before_after = Endpoint("initiative_before_after", BeforeAfter, real=None)


@router.get("/api/initiatives/{initiative_id}/before-after", response_model=BeforeAfter)
def get_before_after(initiative_id: str, conn=Depends(get_conn)):
    return initiative_before_after.serve(conn, key=initiative_id, initiative_id=initiative_id)
