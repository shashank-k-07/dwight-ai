"""Draft viewer + download. Owner: 12. FIXTURE until real=... is set."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from dwight.api.contract import Draft, DraftList
from dwight.api.serving import Endpoint, get_conn

router = APIRouter()

initiative_drafts = Endpoint("initiative_drafts", DraftList, real=None)
draft = Endpoint("draft", Draft, real=None)


@router.get("/api/initiatives/{initiative_id}/drafts", response_model=DraftList)
def list_initiative_drafts(initiative_id: str, conn=Depends(get_conn)):
    return initiative_drafts.serve(conn, key=initiative_id, initiative_id=initiative_id)


@router.get("/api/drafts/{draft_id}", response_model=Draft)
def get_draft(draft_id: str, conn=Depends(get_conn)):
    return draft.serve(conn, key=draft_id, draft_id=draft_id)


@router.get("/api/drafts/{draft_id}/download", response_class=PlainTextResponse)
def download_draft(draft_id: str, conn=Depends(get_conn)):
    d = draft.serve(conn, key=draft_id, draft_id=draft_id)
    return PlainTextResponse(d.content, media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="{d.filename}"'})
