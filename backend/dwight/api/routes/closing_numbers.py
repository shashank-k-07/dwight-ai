"""Closing-numbers strip. Owner: 17 (accuracy from 08, token drop from 13/16).
FIXTURE until real=... is set."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from dwight.api.contract import ClosingNumbers
from dwight.api.serving import Endpoint, get_conn

router = APIRouter()

closing_numbers = Endpoint("closing_numbers", ClosingNumbers, real=None)


@router.get("/api/closing-numbers", response_model=ClosingNumbers)
def get_closing_numbers(conn=Depends(get_conn)):
    return closing_numbers.serve(conn)
