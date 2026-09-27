"""Overview screen. Owner: 01 (Spend), 05 (Measured Waste / Estimated Saving totals),
07 (Spend by Business Function over the full dataset). Real from the store."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from dwight.api.contract import Overview
from dwight.api.serving import Endpoint, get_conn, money

router = APIRouter()


def _from_store(conn) -> dict:
    n, spend, start, end = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(spend_usd),0), MIN(started_at), MAX(ended_at) FROM sessions").fetchone()
    waste = dict(conn.execute("SELECT kind, COALESCE(SUM(usd),0) FROM waste_findings GROUP BY kind").fetchall())
    bfs: dict[str, dict] = {}
    for bf, team, cnt, usd in conn.execute(
            "SELECT business_function, team, COUNT(*), SUM(spend_usd) FROM sessions "
            "GROUP BY business_function, team ORDER BY SUM(spend_usd) DESC"):
        b = bfs.setdefault(bf, {"business_function": bf, "usd": 0.0, "session_count": 0, "teams": []})
        b["usd"] += usd
        b["session_count"] += cnt
        b["teams"].append({"team": team, "spend": money(usd, "measured"), "session_count": cnt})
    by_bf = [{"business_function": b["business_function"], "spend": money(b["usd"], "measured"),
              "session_count": b["session_count"], "teams": b["teams"]}
             for b in sorted(bfs.values(), key=lambda b: -b["usd"])]
    return {
        "period": {"start": start, "end": end},
        "session_count": n,
        "spend": money(spend, "measured"),
        "measured_waste": money(waste.get("measured", 0), "measured"),
        "estimated_saving": money(waste.get("estimated", 0), "estimated"),
        "spend_by_business_function": by_bf,
    }


overview = Endpoint("overview", Overview, real=_from_store)


@router.get("/api/overview", response_model=Overview)
def get_overview(conn=Depends(get_conn)):
    return overview.serve(conn)
