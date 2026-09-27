"""Draft viewer + download. Owner: 12. Served from the store (stage `draft`).

Until the draft stage has written any Draft (an empty drafts table), these endpoints
serve the fixtures, labelled source="fixture", so the panel shows its fixture badge.
Once any Draft exists, everything comes from the store and an unknown draft_id is a 404.
Drafts carry token counts only; their Estimated Saving is on the Recommendation they
are attached to.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from dwight import db
from dwight.api.contract import Draft, DraftList
from dwight.api.serving import Endpoint, fixture, get_conn

router = APIRouter()


def _item(r: dict) -> dict:
    return {k: r[k] for k in ("draft_id", "recommendation_id", "initiative_id", "type", "title", "filename",
                              "content", "tokens", "source_tokens")} | {
        "source_resource_ids": r.get("source_resource_ids") or []}


def _list_from_store(conn, initiative_id: str) -> dict:
    rows = db.rows(conn, "SELECT * FROM drafts WHERE initiative_id=? "
                         "ORDER BY type='memory', draft_id", (initiative_id,))
    return {"items": [_item(r) for r in rows]}


def _draft_from_store(conn, draft_id: str) -> dict:
    rows = db.rows(conn, "SELECT * FROM drafts WHERE draft_id=?", (draft_id,))
    if not rows:
        raise HTTPException(404, f"unknown Draft {draft_id!r}")
    return _item(rows[0])


initiative_drafts = Endpoint("initiative_drafts", DraftList, real=_list_from_store)
draft = Endpoint("draft", Draft, real=_draft_from_store)


def _serve(ep: Endpoint, conn, key: str, **params):
    if ep.source == "store" and conn.execute("SELECT 1 FROM drafts LIMIT 1").fetchone() is None:
        return ep.model.model_validate({**fixture(ep.name, key), "source": "fixture"})
    return ep.serve(conn, key=key, **params)


@router.get("/api/initiatives/{initiative_id}/drafts", response_model=DraftList)
def list_initiative_drafts(initiative_id: str, conn=Depends(get_conn)):
    return _serve(initiative_drafts, conn, initiative_id, initiative_id=initiative_id)


@router.get("/api/drafts/{draft_id}", response_model=Draft)
def get_draft(draft_id: str, conn=Depends(get_conn)):
    return _serve(draft, conn, draft_id, draft_id=draft_id)


@router.get("/api/drafts/{draft_id}/download", response_class=PlainTextResponse)
def download_draft(draft_id: str, conn=Depends(get_conn)):
    d = _serve(draft, conn, draft_id, draft_id=draft_id)
    return PlainTextResponse(d.content, media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="{d.filename}"'})
