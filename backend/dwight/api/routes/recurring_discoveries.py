"""Initiative detail: Recurring Discovery panel (both forms). Owner: 10 (11 writes the
repeated_discovery rows into the same table). FIXTURE until real=... is set."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from dwight.api.contract import RecurringDiscoveries
from dwight.api.serving import Endpoint, get_conn

router = APIRouter()

initiative_recurring = Endpoint("initiative_recurring_discoveries", RecurringDiscoveries, real=None)


@router.get("/api/initiatives/{initiative_id}/recurring-discoveries", response_model=RecurringDiscoveries)
def get_recurring_discoveries(initiative_id: str, conn=Depends(get_conn)):
    return initiative_recurring.serve(conn, key=initiative_id, initiative_id=initiative_id)
