"""Initiative detail: before/after panel. Owner: 13.

Everything here is computed from stored Sessions tagged dwight.experiment=before|after
(sessions.experiment, experiment_task_id, task_success). No figure is hand-entered, so
the real "after" runs (ticket 16) show up as soon as they are ingested and classified.

How the comparison is built (one Initiative):
  * Experiment Sessions are the Initiative's Sessions with experiment = before | after.
    If any of them are dataset='real', only the real ones are used, so fixture or
    synthetic runs in the same store never mix with the real proof.
  * When both sides carry task ids, only tasks run on BOTH sides are compared, so a
    missing or extra task can't fake a drop. Every run of a compared task counts
    (re-runs are not deduplicated, so a retried failure stays visible).
  * total_tokens = input + output tokens (input includes cache reads, OTel GenAI).
  * token_drop_pct compares tokens per Session, so unequal run counts stay fair.
  * spend_drop = (before Spend per Session - after Spend per Session) x after runs:
    the Spend the after runs saved versus as many before runs. With equal run counts
    it is simply before Spend - after Spend. Measured (tokens x list price).
  * success_held = both sides recorded task success and the after success rate is not
    below the before rate. If False, the drop doesn't count and isn't shown as a saving.

Other tickets use `compute()` / `measured_drop()` rather than re-deriving these numbers:
09 attaches measured_drop to the Recommendation carrying the Draft
(`attach_measured_drops`), 17 reads the token drop for the closing numbers.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from dwight.api.contract import BeforeAfter
from dwight.api.serving import Endpoint, get_conn, money

router = APIRouter()

_EPS = 1e-9


def _experiment_sessions(conn, initiative_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT session_id, experiment, experiment_task_id, task_success, dataset, spend_usd, "
        "total_input_tokens + total_output_tokens AS tokens "
        "FROM sessions WHERE initiative_id = ? AND experiment IN ('before', 'after')",
        (initiative_id,)).fetchall()
    rows = [dict(r) for r in rows]
    if any(r["dataset"] == "real" for r in rows):
        rows = [r for r in rows if r["dataset"] == "real"]
    return rows


def _totals(runs: list[dict]) -> dict:
    n = len(runs)
    recorded = [r for r in runs if r["task_success"] is not None]
    passed = sum(1 for r in recorded if r["task_success"])
    tokens = sum(r["tokens"] for r in runs)
    spend = sum(r["spend_usd"] for r in runs)
    return {
        "session_count": n,
        "tasks_passed": passed,
        "tasks_total": len(recorded),
        "success_rate": passed / len(recorded) if recorded else 0.0,
        "total_tokens": tokens,
        "avg_tokens": tokens / n if n else 0.0,
        "spend": money(spend, "measured"),
    }


def compute(conn, initiative_id: str) -> dict:
    """The BeforeAfter body (minus `source`) for one Initiative, from the store."""
    return compare(initiative_id, _experiment_sessions(conn, initiative_id))


def compare(initiative_id: str, rows: list[dict]) -> dict:
    """The BeforeAfter body for experiment Session rows (experiment, experiment_task_id,
    task_success, spend_usd, tokens). compute() passes the store's; dwight.live_run passes
    the recorded before runs plus a live after batch, so both use exactly these rules."""
    body: dict = {"initiative_id": initiative_id, "has_runs": bool(rows)}
    if not rows:
        return body
    before = [r for r in rows if r["experiment"] == "before"]
    after = [r for r in rows if r["experiment"] == "after"]
    shared = ({r["experiment_task_id"] for r in before if r["experiment_task_id"]}
              & {r["experiment_task_id"] for r in after if r["experiment_task_id"]})
    if shared:
        before = [r for r in before if r["experiment_task_id"] in shared]
        after = [r for r in after if r["experiment_task_id"] in shared]
    b = _totals(before) if before else None
    a = _totals(after) if after else None
    body.update(before=b, after=a)
    if b and a:
        if b["avg_tokens"] > 0:
            body["token_drop_pct"] = round((b["avg_tokens"] - a["avg_tokens"]) / b["avg_tokens"] * 100, 1)
        # from the raw store dollars, not the served Money (which carries the demo multiplier)
        b_per = sum(r["spend_usd"] for r in before) / len(before)
        a_per = sum(r["spend_usd"] for r in after) / len(after)
        body["spend_drop"] = money((b_per - a_per) * a["session_count"], "measured")
        body["success_held"] = (b["tasks_total"] > 0 and a["tasks_total"] > 0
                                and a["success_rate"] + _EPS >= b["success_rate"])
    return body


def measured_drop(conn, initiative_id: str) -> Optional[dict]:
    """The contract's MeasuredDrop for an Initiative, or None if it has no before AND after runs.
    `counts` is False when task success dropped: show it, but never as a saving."""
    ba = compute(conn, initiative_id)
    if ba.get("token_drop_pct") is None or ba.get("spend_drop") is None:
        return None
    return {"token_drop_pct": ba["token_drop_pct"], "spend_drop": ba["spend_drop"],
            "counts": bool(ba["success_held"])}


def attach_measured_drops(conn, recommendations: list[dict]) -> list[dict]:
    """Set `measured_drop` on each Initiative Recommendation that carries a Draft, when that
    Initiative has before/after runs (the after runs load the Draft). Mutates and returns
    the list of Recommendation dicts (contract shape). For ticket 09's _from_store."""
    cache: dict[str, Optional[dict]] = {}
    for rec in recommendations:
        if rec.get("target_type") != "initiative" or not rec.get("draft_id"):
            continue
        iid = rec["target_id"]
        if iid not in cache:
            cache[iid] = measured_drop(conn, iid)
        if cache[iid] is not None:
            rec["measured_drop"] = dict(cache[iid])
    return recommendations


def _from_store(conn, initiative_id: str) -> dict:
    return compute(conn, initiative_id)


initiative_before_after = Endpoint("initiative_before_after", BeforeAfter, real=_from_store)


@router.get("/api/initiatives/{initiative_id}/before-after", response_model=BeforeAfter)
def get_before_after(initiative_id: str, conn=Depends(get_conn)):
    return initiative_before_after.serve(conn, key=initiative_id, initiative_id=initiative_id)
