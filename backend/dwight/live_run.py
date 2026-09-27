"""Live agent run: apply a Recommendation's Draft fix, then have the Customer's Agent
re-run the same tasks for real, and measure it (demo feedback: "show an agent applying the fix").

    POST /api/recommendations/{id}/live-run   -> start (one run at a time)
    GET  /api/live-runs/{run_id}              -> poll progress
    GET  /api/recommendations/{id}/live-run   -> can it run here, the latest run, the recorded fallback

What happens, in order:
  1. apply   Dwight puts the fix in place, in code: the Initiative's Draft files, exactly as stored
             (what the Recommendations carry), are written to the run's context/ directory and loaded
             into kestrel-devagent's starting context. Both Drafts go in together (the initiative doc
             and the memory file), as the recorded after runs (ticket 16) did.
  2. run     The harness (dwight.harness, a real tool-using Agent on the pinned model) runs the same
             storage tasks as the recorded before runs, all in parallel, with the settings file
             data/real_scr_settings.json. Loading it re-checks its fingerprint (system prompt, tools,
             tasks, docs, workspace, provider), so the only difference from the before runs is the
             context files. Progress is reported per Call.
  3. measure Each finished Session's spans are ingested into the run's own scratch store
             (<run dir>/run.sqlite) by the normal ingest code, so tokens and Spend are priced exactly as
             in the store. before_after.compare() then compares the recorded before runs (from the
             store) with this batch, with the same rules as the Before/After panel. Measured.

Nothing is written to the demo store, data/otlp/, or the harness run manifests, so a live run never
changes the frozen numbers; reset-demo has nothing to undo. If a run fails or times out, the dashboard
shows the recorded after runs instead, labelled as recorded.

Gated: DWIGHT_LIVE_RUNS=1 and a model API key (it makes real, paid model calls).
"""
from __future__ import annotations

import json
import secrets
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dwight import config, db
from dwight.api.routes import before_after
from dwight.api.serving import money

INITIATIVE = "storage-cost-reduction"      # the one Initiative with harness tasks and recorded before runs
TIMEOUT_S = float(config.LIVE_RUN_TIMEOUT_S)
WORKERS = 10                                # every task at once: the run takes about as long as its slowest task


class LiveRunError(Exception):
    """Can't start a run (disabled, ineligible, or one is already running). .status = HTTP status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class Task:
    task_id: str
    session_id: str
    status: str = "queued"                  # queued | running | done | failed
    calls: int = 0
    tokens: int = 0
    last_tools: list[str] = field(default_factory=list)
    task_success: bool | None = None
    spend_usd: float | None = None
    error: str | None = None
    check_notes: list[str] = field(default_factory=list)


@dataclass
class Run:
    run_id: str
    recommendation_id: str
    initiative_id: str
    model: str
    started: float
    started_at: str
    dir: Path
    applied: list[dict]
    tasks: dict[str, Task]
    status: str = "applying"                # applying | running | done | failed | timed_out
    finished_at: str | None = None
    finished: float | None = None
    message: str | None = None
    after_rows: list[dict] = field(default_factory=list)
    before_rows: list[dict] = field(default_factory=list)


_lock = threading.RLock()
_runs: dict[str, Run] = {}
_latest: dict[str, str] = {}                # recommendation_id -> run_id


def enabled() -> tuple[bool, str | None]:
    if not config.LIVE_RUNS:
        return False, "Live runs are off. Set DWIGHT_LIVE_RUNS=1 for the API (it makes real model calls)."
    if not config.GLM_API_KEY:
        return False, "No model API key (SCIFORIUM_API_KEY) is configured for the API."
    return True, None


def _recommendation(conn, recommendation_id: str) -> dict | None:
    r = conn.execute("SELECT recommendation_id, target_type, target_id, draft_id FROM recommendations "
                     "WHERE recommendation_id = ?", (recommendation_id,)).fetchone()
    return dict(r) if r else None


def _before_rows(conn, initiative_id: str) -> list[dict]:
    return [r for r in before_after._experiment_sessions(conn, initiative_id)
            if r["experiment"] == "before" and r["dataset"] == "real"]


def eligibility(conn, recommendation_id: str) -> tuple[bool, str | None]:
    """Only a Draft Recommendation on the Initiative whose tasks the harness can run, with recorded
    before runs to compare against."""
    r = _recommendation(conn, recommendation_id)
    if r is None:
        return False, f"unknown Recommendation {recommendation_id!r}"
    if r["target_type"] != "initiative" or not r["draft_id"]:
        return False, "Only a Recommendation that carries a Draft can be run by an agent."
    if r["target_id"] != INITIATIVE:
        return False, f"The harness has real tasks only for {INITIATIVE}."
    if not _before_rows(conn, INITIATIVE):
        return False, "No recorded before runs to compare against."
    if not _drafts(conn, INITIATIVE):
        return False, "This Initiative has no Drafts."
    return True, None


def _drafts(conn, initiative_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT draft_id, type, filename, content, tokens FROM drafts WHERE initiative_id = ? "
        "ORDER BY CASE type WHEN 'initiative_doc' THEN 0 ELSE 1 END", (initiative_id,))]


def _settings() -> dict:
    from dwight.harness import settings
    return settings.load(settings.DEFAULT_PATH)   # raises if the harness drifted since the before runs


def task_count() -> int:
    from dwight import company
    return len((company.storage_tasks() or {}).get("tasks", []))


def active() -> Run | None:
    with _lock:
        return next((r for r in _runs.values() if r.status in ("applying", "running")), None)


def latest(recommendation_id: str) -> Run | None:
    with _lock:
        rid = _latest.get(recommendation_id)
        return _runs.get(rid) if rid else None


def get(run_id: str) -> Run | None:
    with _lock:
        return _runs.get(run_id)


def start(conn, recommendation_id: str, *, client: Any = None, background: bool = True) -> Run:
    """Apply the fix and start the Agent. `client` replaces the model client (tests)."""
    ok, why = enabled() if client is None else (True, None)
    if not ok:
        raise LiveRunError(why, 403)
    ok, why = eligibility(conn, recommendation_id)
    if not ok:
        raise LiveRunError(why, 400)
    params = _settings()
    with _lock:
        if active():
            raise LiveRunError("A live run is already in progress.", 409)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
        run_dir = Path(config.LIVE_RUNS_DIR) / run_id
        (run_dir / "context").mkdir(parents=True)
        # 1. apply: the Draft files, exactly as stored, into the Agent's starting context
        applied = []
        for d in _drafts(conn, INITIATIVE):
            (run_dir / "context" / d["filename"]).write_text(d["content"])
            applied.append({"draft_id": d["draft_id"], "filename": d["filename"], "type": d["type"],
                            "tokens": d["tokens"]})
        from dwight.harness import tasks as htasks
        specs = htasks.storage_specs(
            experiment="after", session_prefix=f"live-{run_id}", task_ids=params["tasks"],
            context_files=[run_dir / "context" / a["filename"] for a in applied], model=params["model"],
            repeat=1, max_calls=params["max_calls"] or htasks.STORAGE_MAX_CALLS)
        run = Run(run_id=run_id, recommendation_id=recommendation_id, initiative_id=INITIATIVE,
                  model=params["model"], started=time.time(), started_at=_now(), dir=run_dir, applied=applied,
                  tasks={s.task_id: Task(task_id=s.task_id, session_id=s.session_id) for s in specs},
                  before_rows=_before_rows(conn, INITIATIVE))
        _runs[run_id] = run
        _latest[recommendation_id] = run_id
        _save(run)
    worker = threading.Thread(target=_execute, args=(run, specs, client), name=f"live-run-{run_id}", daemon=True)
    if background:
        worker.start()
    else:
        worker.run()
    return run


def _execute(run: Run, specs: list, client: Any) -> None:
    from dwight import glm
    from dwight.harness.agent import run_session
    from dwight.ingest.otlp import ingest_payload

    with _lock:
        run.status = "running"
    try:
        client = client or glm.client()
    except Exception as e:  # noqa: BLE001
        _finish(run, "failed", f"Couldn't create the model client: {e}")
        return
    store = db.connect(run.dir / "run.sqlite")
    store_lock = threading.Lock()

    def one(spec) -> None:
        t = run.tasks[spec.task_id]
        with _lock:
            t.status = "running"

        def progress(ev: dict) -> None:
            with _lock:
                t.calls, t.tokens, t.last_tools = ev["seq"] + 1, ev["total_tokens"], ev["tools"]

        try:
            res = run_session(spec, client=client, on_call=progress)
            (run.dir / f"{spec.session_id}.json").write_text(json.dumps(res.payload) + "\n")
            with store_lock:   # 3. measure: priced by the normal ingest code, in the run's own store
                ingest_payload(store, res.payload)
                row = store.execute(
                    "SELECT session_id, experiment, experiment_task_id, task_success, dataset, spend_usd, "
                    "total_input_tokens + total_output_tokens AS tokens FROM sessions WHERE session_id = ?",
                    (spec.session_id,)).fetchone()
            with _lock:
                t.status, t.calls, t.tokens = "done", res.calls, row["tokens"]
                t.task_success, t.spend_usd, t.check_notes = res.task_success, row["spend_usd"], list(res.check_notes)
                run.after_rows.append(dict(row))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            with _lock:
                t.status, t.error = "failed", f"{type(e).__name__}: {e}"[:300]
        finally:
            with _lock:
                _save(run)

    # No `with`: leaving it would wait for every Session, which defeats the timeout.
    pool = ThreadPoolExecutor(max_workers=min(WORKERS, len(specs)), thread_name_prefix=f"live-{run.run_id}")
    futs = [pool.submit(one, s) for s in specs]
    deadline = run.started + TIMEOUT_S
    for f in futs:
        try:
            f.result(timeout=max(deadline - time.time(), 0.01))
        except TimeoutError:
            # Sessions still running finish in the background; their results no longer count.
            _finish(run, "timed_out", f"The live run passed {TIMEOUT_S:.0f} s, so it was stopped.")
            pool.shutdown(wait=False, cancel_futures=True)
            return
    pool.shutdown(wait=True)
    store.close()
    ran = [t for t in run.tasks.values() if t.status == "done"]
    failed = [t for t in run.tasks.values() if t.status == "failed"]
    if not ran:
        _finish(run, "failed", f"No task finished: {failed[0].error if failed else 'unknown error'}")
    elif failed:
        _finish(run, "done", f"{len(failed)} of {len(run.tasks)} tasks failed to run (API errors); "
                             f"compared on the {len(ran)} that ran, against the same tasks' before runs.")
    else:
        _finish(run, "done", None)


def _finish(run: Run, status: str, message: str | None) -> None:
    with _lock:
        if run.status not in ("applying", "running"):
            return
        run.status, run.message, run.finished, run.finished_at = status, message, time.time(), _now()
        _save(run)


def _save(run: Run) -> None:
    try:
        (run.dir / "run.json").write_text(json.dumps({
            "run_id": run.run_id, "recommendation_id": run.recommendation_id, "initiative_id": run.initiative_id,
            "status": run.status, "started": run.started, "finished": run.finished,
            "model": run.model, "started_at": run.started_at, "finished_at": run.finished_at,
            "message": run.message, "applied": run.applied,
            "tasks": {k: vars(t) for k, t in run.tasks.items()}, "after_rows": run.after_rows}, indent=1) + "\n")
    except OSError:
        pass


def to_contract(run: Run) -> dict:
    """The LiveRun response body (minus `source`). Dollars built here, with serving.money()."""
    with _lock:
        before = {r["experiment_task_id"]: r for r in run.before_rows}
        tasks = []
        for tid in sorted(run.tasks):
            t, b = run.tasks[tid], before.get(tid)
            tasks.append({
                "task_id": t.task_id, "session_id": t.session_id, "status": t.status, "calls": t.calls,
                "tokens": t.tokens, "last_tools": list(t.last_tools), "task_success": t.task_success,
                "spend": money(t.spend_usd, "measured") if t.spend_usd is not None else None,
                "before_tokens": b["tokens"] if b else None,
                "before_spend": money(b["spend_usd"], "measured") if b else None,
                "before_success": None if not b or b["task_success"] is None else bool(b["task_success"]),
                "error": t.error, "check_notes": list(t.check_notes)})
        result = None
        if run.status == "done" and run.after_rows:
            result = {**before_after.compare(run.initiative_id, run.before_rows + run.after_rows)}
        end = run.finished or time.time()
        return {"run_id": run.run_id, "recommendation_id": run.recommendation_id,
                "initiative_id": run.initiative_id, "status": run.status, "model": run.model,
                "started_at": run.started_at, "finished_at": run.finished_at,
                "elapsed_s": round(end - run.started, 1), "applied_files": list(run.applied), "tasks": tasks,
                "result": result, "message": run.message}


def _iso_epoch(ts: str | None) -> float | None:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() if ts else None


def load_saved(conn) -> int:
    """Re-read finished runs from LIVE_RUNS_DIR/<run_id>/run.json after an API restart, so the last
    result still shows. Runs that were in progress when the API stopped are marked failed."""
    root = Path(config.LIVE_RUNS_DIR)
    n = 0
    for f in sorted(root.glob("*/run.json")) if root.exists() else []:
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        with _lock:
            if d["run_id"] in _runs:
                continue
            iid = d.get("initiative_id", INITIATIVE)
            run = Run(run_id=d["run_id"], recommendation_id=d["recommendation_id"], initiative_id=iid,
                      model=d["model"], started=d.get("started") or _iso_epoch(d["started_at"]) or 0.0,
                      started_at=d["started_at"], dir=f.parent, applied=d["applied"],
                      tasks={k: Task(**v) for k, v in d["tasks"].items()}, status=d["status"],
                      finished_at=d.get("finished_at"), finished=d.get("finished") or _iso_epoch(d.get("finished_at")),
                      message=d.get("message"), after_rows=d.get("after_rows", []),
                      before_rows=_before_rows(conn, iid))
            if run.status in ("applying", "running"):
                run.status, run.message = "failed", "The API stopped while this run was in progress."
            _runs[run.run_id] = run
            _latest[run.recommendation_id] = max(
                (r for r in _runs.values() if r.recommendation_id == run.recommendation_id),
                key=lambda r: r.started).run_id
            n += 1
    return n


_loaded = False


def status_body(conn, recommendation_id: str) -> dict:
    """The LiveRunStatus body (minus `source`)."""
    global _loaded
    if not _loaded:
        _loaded = True
        load_saved(conn)
    on, why_off = enabled()
    ok, why = eligibility(conn, recommendation_id)
    run = latest(recommendation_id)
    recorded = before_after.compute(conn, INITIATIVE) if ok else None
    model = None
    if ok:
        try:
            model = _settings()["model"]
        except (ValueError, OSError) as e:
            ok, why = False, f"Harness settings don't match the before runs: {e}"
    return {"enabled": on, "eligible": ok, "reason": why if not ok else why_off,
            "task_count": task_count() if ok else 0, "model": model,
            "applied_drafts": [{k: d[k] for k in ("draft_id", "filename", "type", "tokens")}
                               for d in _drafts(conn, INITIATIVE)] if ok else [],
            "run": to_contract(run) if run else None,
            "recorded": {**recorded, "source": "store"} if recorded and recorded.get("has_runs") else None}
