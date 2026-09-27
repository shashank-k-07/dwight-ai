"""Closing-numbers strip. Owner: 17 (accuracy from 08, token drop from 13/16).

Served from the store (ticket 15 switched it from fixtures; 17 owns the copy and the panel):
  spend_analysed            Measured, every Session
  measured_waste            Measured, every Session (the Overview figure)
  measured_waste_real_layer Measured, dataset='real' Sessions only (harness runs, no synthetic)
  estimated_saving          Estimated, the Overview figure (Estimated findings)
  draft_token_drop_pct      13's before/after token drop for the Initiative whose real "after"
                            runs exist (16); None until they do, or when task success dropped
  classifier_accuracy       the latest eval_runs row (08); None until an eval has run

`python -m dwight.demo export` writes the same body (closing_numbers_body) for the slides.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from dwight.api.contract import ClosingNumbers
from dwight.api.routes import before_after
from dwight.api.serving import Endpoint, get_conn, money

router = APIRouter()


def token_drop_source(conn) -> tuple[str, dict] | None:
    """(initiative_id, before_after.compute body) the strip's token drop comes from, or None.
    Prefers the Initiative with real-layer "after" runs, then the one with the most."""
    for (iid,) in conn.execute(
            "SELECT initiative_id FROM sessions WHERE experiment='after' AND initiative_id IS NOT NULL "
            "GROUP BY initiative_id ORDER BY MAX(dataset='real') DESC, COUNT(*) DESC, initiative_id"):
        ba = before_after.compute(conn, iid)
        if ba.get("token_drop_pct") is not None:
            return iid, ba
    return None


def _token_drop(conn) -> float | None:
    src = token_drop_source(conn)
    if src is None:
        return None
    ba = src[1]
    return ba["token_drop_pct"] if ba.get("success_held") else None


def latest_eval(conn):
    """The eval_runs row the strip shows (08): the latest by created_at."""
    return conn.execute("SELECT eval_id, created_at, label, accuracy, n_sessions FROM eval_runs "
                        "ORDER BY created_at DESC, eval_id DESC LIMIT 1").fetchone()


def _from_store(conn) -> dict:
    spend = conn.execute("SELECT COALESCE(SUM(spend_usd), 0) FROM sessions").fetchone()[0]
    waste = dict(conn.execute("SELECT kind, COALESCE(SUM(usd), 0) FROM waste_findings GROUP BY kind").fetchall())
    real = conn.execute("SELECT COALESCE(SUM(w.usd), 0) FROM waste_findings w JOIN sessions s USING (session_id) "
                        "WHERE s.dataset='real' AND w.kind='measured'").fetchone()[0]
    ev = latest_eval(conn)
    return {
        "spend_analysed": money(spend, "measured"),
        "measured_waste": money(waste.get("measured", 0), "measured"),
        "measured_waste_real_layer": money(real, "measured"),
        "estimated_saving": money(waste.get("estimated", 0), "estimated"),
        "draft_token_drop_pct": _token_drop(conn),
        "classifier_accuracy": ev["accuracy"] if ev else None,
        "classifier_eval_sessions": ev["n_sessions"] if ev else None,
    }


closing_numbers = Endpoint("closing_numbers", ClosingNumbers, real=_from_store)


def closing_numbers_body(conn) -> dict:
    """Exactly what GET /api/closing-numbers returns (source included), as JSON-ready data."""
    return closing_numbers.serve(conn).model_dump(mode="json")


@router.get("/api/closing-numbers", response_model=ClosingNumbers)
def get_closing_numbers(conn=Depends(get_conn)):
    return closing_numbers.serve(conn)
