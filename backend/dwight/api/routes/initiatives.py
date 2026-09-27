"""Initiatives table, Initiative header and Sessions list. Owner: 06. Real from the store.

Initiative rows (name, description, business_function, session_count, spend_usd)
are written by the classify stage. `teams` (added after the freeze, additive) splits an
Initiative's Spend by Team, from the Sessions. Waste comes from waste_findings (ticket 05's
detect stage, or the seeded fixture findings until it lands): measured findings
sum to Measured Waste, estimated ones to Estimated Saving. Spend is Measured.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from dwight.api.contract import Initiative, InitiativeList, SessionList
from dwight.api.serving import Endpoint, get_conn, money
from dwight.classifier.model import candidates

router = APIRouter()


def _waste_by_initiative(conn) -> dict[str, dict]:
    """{initiative_id: {"measured": usd, "estimated": usd, "top": pattern}}"""
    out: dict[str, dict] = {}
    per_pattern: dict[str, dict[str, float]] = {}
    for iid, kind, pattern, usd in conn.execute(
            "SELECT s.initiative_id, w.kind, w.pattern, SUM(w.usd) FROM waste_findings w "
            "JOIN sessions s ON s.session_id = w.session_id WHERE s.initiative_id IS NOT NULL "
            "GROUP BY s.initiative_id, w.kind, w.pattern"):
        o = out.setdefault(iid, {"measured": 0.0, "estimated": 0.0, "top": None})
        o[kind] = o.get(kind, 0.0) + (usd or 0.0)
        pp = per_pattern.setdefault(iid, {})
        pp[pattern] = pp.get(pattern, 0.0) + (usd or 0.0)
    for iid, pp in per_pattern.items():
        top = max(pp.items(), key=lambda kv: (kv[1], kv[0]))
        out[iid]["top"] = top[0] if top[1] > 0 else None
    return out


def _teams_by_initiative(conn, initiative_id: str | None = None) -> dict[str, list[dict]]:
    """{initiative_id: [TeamSpend, ...]} ranked by Spend (Measured)."""
    where, args = ("WHERE initiative_id = ?", (initiative_id,)) if initiative_id else (
        "WHERE initiative_id IS NOT NULL", ())
    out: dict[str, list[dict]] = {}
    for iid, team, n, usd in conn.execute(
            f"SELECT initiative_id, team, COUNT(*), SUM(spend_usd) FROM sessions {where} "
            "GROUP BY initiative_id, team ORDER BY initiative_id, SUM(spend_usd) DESC, team", args):
        out.setdefault(iid, []).append({"team": team, "spend": money(usd, "measured"), "session_count": n})
    return out


def _initiatives_from_store(conn) -> dict:
    waste = _waste_by_initiative(conn)
    teams = _teams_by_initiative(conn)
    items = []
    for r in conn.execute("SELECT initiative_id, name, business_function, session_count, spend_usd "
                          "FROM initiatives WHERE session_count > 0 ORDER BY spend_usd DESC, initiative_id"):
        w = waste.get(r["initiative_id"], {})
        items.append({
            "initiative_id": r["initiative_id"], "name": r["name"], "business_function": r["business_function"],
            "session_count": r["session_count"], "spend": money(r["spend_usd"], "measured"),
            "measured_waste": money(w.get("measured", 0.0), "measured"),
            "estimated_saving": money(w.get("estimated", 0.0), "estimated"),
            "top_waste_pattern": w.get("top"),
            "teams": teams.get(r["initiative_id"], []),
        })
    return {"items": items}


def _known(initiative_id: str) -> dict | None:
    """An org.yaml Initiative not yet written to the store (nothing classified yet)."""
    for c in candidates():
        if c.initiative_id == initiative_id:
            return {"initiative_id": c.initiative_id, "name": c.name, "description": c.description,
                    "business_function": c.business_function, "session_count": 0, "spend_usd": 0.0}
    return None


def _initiative_row(conn, initiative_id: str) -> dict:
    r = conn.execute("SELECT initiative_id, name, description, business_function, session_count, spend_usd "
                     "FROM initiatives WHERE initiative_id=?", (initiative_id,)).fetchone()
    row = dict(r) if r else _known(initiative_id)
    if row is None:
        raise HTTPException(404, f"unknown Initiative {initiative_id!r}")
    return row


def _initiative_from_store(conn, initiative_id: str) -> dict:
    r = _initiative_row(conn, initiative_id)
    return {"initiative_id": r["initiative_id"], "name": r["name"], "description": r["description"],
            "business_function": r["business_function"], "session_count": r["session_count"],
            "spend": money(r["spend_usd"], "measured"),
            "teams": _teams_by_initiative(conn, initiative_id).get(initiative_id, [])}


def _sessions_from_store(conn, initiative_id: str) -> dict:
    _initiative_row(conn, initiative_id)  # 404 on an unknown id
    patterns: dict[str, list[str]] = {}
    for sid, pattern in conn.execute(
            "SELECT DISTINCT w.session_id, w.pattern FROM waste_findings w JOIN sessions s "
            "ON s.session_id = w.session_id WHERE s.initiative_id=? ORDER BY w.pattern", (initiative_id,)):
        patterns.setdefault(sid, []).append(pattern)
    items = []
    for r in conn.execute(
            "SELECT session_id, member_id, team, business_function, agent, started_at, ended_at, summary, "
            "complexity, call_count, total_input_tokens + total_output_tokens AS total_tokens, spend_usd, "
            "experiment, task_success FROM sessions WHERE initiative_id=? "
            "ORDER BY spend_usd DESC, started_at DESC", (initiative_id,)):
        items.append({
            "session_id": r["session_id"], "member_id": r["member_id"], "team": r["team"],
            "business_function": r["business_function"], "agent": r["agent"], "started_at": r["started_at"],
            "ended_at": r["ended_at"], "summary": r["summary"], "complexity": r["complexity"],
            "call_count": r["call_count"], "total_tokens": r["total_tokens"],
            "spend": money(r["spend_usd"], "measured"),
            "waste_patterns": patterns.get(r["session_id"], []),
            "experiment": r["experiment"] if r["experiment"] in ("before", "after") else None,
            "task_success": None if r["task_success"] is None else bool(r["task_success"]),
        })
    return {"items": items}


initiatives = Endpoint("initiatives", InitiativeList, real=_initiatives_from_store)
initiative = Endpoint("initiative", Initiative, real=_initiative_from_store)
initiative_sessions = Endpoint("initiative_sessions", SessionList, real=_sessions_from_store)


@router.get("/api/initiatives", response_model=InitiativeList)
def list_initiatives(conn=Depends(get_conn)):
    return initiatives.serve(conn)


@router.get("/api/initiatives/{initiative_id}", response_model=Initiative)
def get_initiative(initiative_id: str, conn=Depends(get_conn)):
    return initiative.serve(conn, key=initiative_id, initiative_id=initiative_id)


@router.get("/api/initiatives/{initiative_id}/sessions", response_model=SessionList)
def list_initiative_sessions(initiative_id: str, conn=Depends(get_conn)):
    return initiative_sessions.serve(conn, key=initiative_id, initiative_id=initiative_id)
