"""OTLP/HTTP JSON trace receiver: POST /v1/traces (Content-Type: application/json).
Protobuf is not supported; exporters must send JSON (or write files for the ingest stage)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from dwight.api.serving import get_conn
from dwight.ingest.otlp import ingest_payload

router = APIRouter()


@router.post("/v1/traces")
async def receive_traces(request: Request, conn=Depends(get_conn)):
    payload = await request.json()
    sessions = ingest_payload(conn, payload)
    return {"partialSuccess": {}, "dwight_sessions": sessions}
