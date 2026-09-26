"""Run batches of Sessions and write their outputs.

Per Session:
  data/otlp/real/<session_id>.json        OTLP JSON (ingest with `pipeline run ingest data/otlp/real`)
  data/real_layer_runs.json               run manifest: model + harness settings + outcome (no labels)
  data/ground-truth/real_layer_labels.yaml   planted pattern + what the harness observed (detectors never read it)
"""
from __future__ import annotations

import hashlib
import json
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from dwight import config, db
from dwight.harness.agent import MAX_TOKENS_PER_CALL, SessionResult, SessionSpec, observed_signals, run_session
from dwight.ingest.otlp import ingest_file

OTLP_REAL_DIR = config.DATA_DIR / "otlp" / "real"
RUNS_PATH = config.DATA_DIR / "real_layer_runs.json"
LABELS_PATH = config.GROUND_TRUTH_DIR / "real_layer_labels.yaml"
MAX_WORKERS = 4

PLANTED = {"clean": "none", "redundant_read": "redundant_read", "cache_miss": "cache_miss",
           "runaway_loop": "runaway_loop"}

LABELS_HEADER = """\
# GROUND TRUTH for the real layer (ticket 03 harness runs). Which Session carries
# which planted Waste Pattern. The detectors (05), classifier (06) and every
# pipeline stage must NEVER read this file; only acceptance checks (15) and
# evals may.
#
# planted_pattern: none | redundant_read | cache_miss | runaway_loop
#   (no model_overkill: the real layer runs only light pool models)
# observed: what the harness itself saw in the run (not detector output):
#   duplicate_tool_results             tool results whose content hash appeared earlier in the Session
#   max_identical_consecutive_tool_calls  longest run of consecutive Calls requesting the same
#                                      single tool call with the same args and same result
#   volatile_prefix                    the system prompt started with a per-Call timestamp
#   cache_read_reported                the API reported cache-read tokens on any Call
"""

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _settings(spec: SessionSpec, result: SessionResult) -> dict:
    return {
        "model": result.model,
        "agent": spec.agent,
        "temperature": spec.temperature,
        "max_calls": spec.max_calls,
        "max_tokens_per_call": MAX_TOKENS_PER_CALL,
        "tools": list(spec.tools) if spec.tools else None,
        "docs": sorted(spec.docs),
        "system_prompt_sha": hashlib.sha256(spec.system_prompt.encode()).hexdigest()[:12],
        "context_files": [str(Path(p)) for p in spec.context_files],
        "retry_prompt": spec.retry_prompt,
    }


def _load_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text()) if path.exists() else default


def _record(spec: SessionSpec, result: SessionResult, out_dir: Path, runs_path: Path, labels_path: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{spec.session_id}.json").write_text(json.dumps(result.payload, indent=1) + "\n")
    with _lock:
        runs = _load_json(runs_path, {"sessions": {}})
        runs["sessions"][spec.session_id] = {
            "task_id": spec.task_id, "experiment": spec.experiment, "recorded_at": _now(),
            "member_id": spec.member_id, "team": spec.team, "settings": _settings(spec, result),
            "calls": result.calls, "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
            "stop_reason": result.stop_reason, "task_success": result.task_success,
            "check_notes": result.check_notes}
        runs["sessions"] = dict(sorted(runs["sessions"].items()))
        runs_path.write_text(json.dumps(runs, indent=1) + "\n")

        labels = yaml.safe_load(labels_path.read_text()) if labels_path.exists() else None
        labels = labels or {"version": 1, "sessions": {}}
        labels["sessions"][spec.session_id] = {
            "task_id": spec.task_id, "variant": spec.variant, "planted_pattern": PLANTED[spec.variant],
            "experiment": spec.experiment,
            "observed": {**observed_signals(result), "volatile_prefix": spec.variant == "cache_miss",
                         "cache_read_reported": result.cache_read_reported},
            "stop_reason": result.stop_reason, "calls": result.calls}
        labels["sessions"] = dict(sorted(labels["sessions"].items()))
        labels_path.parent.mkdir(parents=True, exist_ok=True)
        labels_path.write_text(LABELS_HEADER + "\n" + yaml.safe_dump(labels, sort_keys=False, width=110))


def run_batch(specs: list[SessionSpec], *, workers: int = MAX_WORKERS, out_dir: Path = OTLP_REAL_DIR,
              ingest: bool = False, client: Any = None, log=print,
              runs_path: Path = RUNS_PATH, labels_path: Path = LABELS_PATH) -> tuple[list[SessionResult], list[str]]:
    """Run Sessions in parallel (<= MAX_WORKERS), write each one's outputs as it
    finishes. Returns (results, failed session ids). A failed Session writes nothing."""
    workers = max(1, min(workers, MAX_WORKERS))
    results: list[SessionResult] = []
    failed: list[str] = []

    def one(spec: SessionSpec) -> SessionResult:
        return run_session(spec, client=client)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(one, s): s for s in specs}
        for fut in as_completed(futs):
            spec = futs[fut]
            try:
                r = fut.result()
            except Exception as e:  # noqa: BLE001
                failed.append(spec.session_id)
                log(f"[{spec.session_id}] FAILED: {type(e).__name__}: {e}")
                traceback.print_exc()
                continue
            _record(spec, r, out_dir, runs_path, labels_path)
            results.append(r)
            sig = observed_signals(r)
            log(f"[{spec.session_id}] {spec.variant:<14} {spec.task_id:<30} calls={r.calls:<3} "
                f"in={r.input_tokens:<7} out={r.output_tokens:<6} stop={r.stop_reason:<12} "
                f"success={r.task_success} dup={sig['duplicate_tool_results']} "
                f"streak={sig['max_identical_consecutive_tool_calls']}")
    if ingest and results:
        conn = db.connect()
        for r in results:
            ingest_file(conn, out_dir / f"{r.session_id}.json")
        conn.close()
        log(f"ingested {len(results)} Sessions into {config.DB_PATH}")
    return results, failed
