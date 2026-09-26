"""Initiatives table, Initiative header and Sessions list. Owner: 06.
FIXTURE until 06 sets real=... on each Endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from dwight.api.contract import Initiative, InitiativeList, SessionList
from dwight.api.serving import Endpoint, get_conn

router = APIRouter()

initiatives = Endpoint("initiatives", InitiativeList, real=None)
initiative = Endpoint("initiative", Initiative, real=None)
initiative_sessions = Endpoint("initiative_sessions", SessionList, real=None)


@router.get("/api/initiatives", response_model=InitiativeList)
def list_initiatives(conn=Depends(get_conn)):
    return initiatives.serve(conn)


@router.get("/api/initiatives/{initiative_id}", response_model=Initiative)
def get_initiative(initiative_id: str, conn=Depends(get_conn)):
    return initiative.serve(conn, key=initiative_id, initiative_id=initiative_id)


@router.get("/api/initiatives/{initiative_id}/sessions", response_model=SessionList)
def list_initiative_sessions(initiative_id: str, conn=Depends(get_conn)):
    return initiative_sessions.serve(conn, key=initiative_id, initiative_id=initiative_id)
