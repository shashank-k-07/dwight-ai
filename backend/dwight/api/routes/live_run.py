"""Live agent run endpoints (demo feedback; added after the freeze, additive). See dwight/live_run.py.

  GET  /api/recommendations/{recommendation_id}/live-run   LiveRunStatus: can it run, latest run, recorded fallback
  POST /api/recommendations/{recommendation_id}/live-run   LiveRun: apply the Draft fix and start the Agent
  GET  /api/live-runs/{run_id}                             LiveRun: poll progress

Always served from the store and the running harness, never from fixtures.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from dwight import live_run
from dwight.api.contract import LiveRun, LiveRunStatus
from dwight.api.serving import get_conn

router = APIRouter()


@router.get("/api/recommendations/{recommendation_id}/live-run", response_model=LiveRunStatus)
def get_live_run_status(recommendation_id: str, conn=Depends(get_conn)):
    return LiveRunStatus.model_validate({**live_run.status_body(conn, recommendation_id), "source": "store"})


@router.post("/api/recommendations/{recommendation_id}/live-run", response_model=LiveRun)
def start_live_run(recommendation_id: str, conn=Depends(get_conn)):
    try:
        run = live_run.start(conn, recommendation_id)
    except live_run.LiveRunError as e:
        raise HTTPException(e.status, str(e)) from e
    except ValueError as e:   # the harness settings drifted since the before runs
        raise HTTPException(409, str(e)) from e
    return LiveRun.model_validate({**live_run.to_contract(run), "source": "store"})


@router.get("/api/live-runs/{run_id}", response_model=LiveRun)
def get_live_run(run_id: str):
    run = live_run.get(run_id)
    if run is None:
        raise HTTPException(404, f"no live run {run_id!r} in this API process")
    return LiveRun.model_validate({**live_run.to_contract(run), "source": "store"})
