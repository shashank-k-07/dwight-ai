"""python -m dwight.pipeline list
   python -m dwight.pipeline run <stage> [stage args...]
   python -m dwight.pipeline run-all            # every IN_DEFAULT_RUN stage, in ORDER
   python -m dwight.pipeline reset              # delete the store file (DWIGHT_DB)
   python -m dwight.pipeline rebuild [--keep]   # ticket 15: the whole demo store in one command

rebuild = reset the store (unless --keep), generate the synthetic OTLP if
data/otlp/synthetic/ is empty (no model calls; the content library is committed),
then run-all over data/otlp/ (real + synthetic) with the draft stage importing the
committed Drafts in data/drafts/ (--pinned), then draft_check and acceptance.
It stops at the first stage that errors. Classify is the only slow stage (about
4 min for 4K Sessions at 32 workers with reasoning off, the default).
"""
from __future__ import annotations

import sys
import time
import traceback
from datetime import datetime, timezone

from dwight import config, db
from dwight.pipeline import NotImplementedYet, discover


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(stage, args: list[str]) -> bool:
    conn = db.connect()
    started = _now()
    t0 = time.time()
    try:
        msg = stage.run(conn, args)
        status = "ok"
    except NotImplementedYet as e:
        msg, status = str(e), "not_implemented"
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        msg, status = f"{type(e).__name__}: {e}", "error"
    conn.execute("INSERT INTO stage_runs (stage, started_at, finished_at, status, message) VALUES (?,?,?,?,?)",
                 (stage.name, started, _now(), status, msg))
    conn.commit()
    conn.close()
    print(f"[{stage.name}] {status} ({time.time() - t0:.1f}s){': ' + msg if msg else ''}")
    return status != "error"


def _reset() -> None:
    for suffix in ("", "-wal", "-shm"):
        p = config.DB_PATH.with_name(config.DB_PATH.name + suffix)
        if p.exists():
            p.unlink()
    print(f"deleted {config.DB_PATH}")


PINNED_DRAFTS_DIR = config.DATA_DIR / "drafts"   # the committed Drafts (15 -> 16)
SYNTHETIC_OTLP_DIR = config.DATA_DIR / "otlp" / "synthetic"


def rebuild_args() -> dict[str, list[str]]:
    """Per-stage args for `rebuild` (every other stage runs with its defaults)."""
    return {"draft": ["--pinned", str(PINNED_DRAFTS_DIR)]}


def rebuild(stages, keep: bool = False) -> int:
    if not keep:
        _reset()
    if not any(SYNTHETIC_OTLP_DIR.glob("*.json*")):
        from dwight.synth.__main__ import main as synth_main
        print(f"[rebuild] {SYNTHETIC_OTLP_DIR} is empty: generating the synthetic dataset (no model calls)")
        if synth_main(["build"]) != 0:
            return 1
    extra = rebuild_args()
    plan = [s for s in stages.values() if s.in_default_run] + [stages[n] for n in ("draft_check", "acceptance")
                                                                 if n in stages]
    t0 = time.time()
    for s in plan:
        if not _run(s, extra.get(s.name, [])):
            print(f"[rebuild] stopped: {s.name} failed ({time.time() - t0:.0f}s)")
            return 1
    print(f"[rebuild] done in {time.time() - t0:.0f}s: store {config.DB_PATH}")
    return 0


def main(argv: list[str]) -> int:
    stages = discover()
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "list":
        print(f"store: {config.DB_PATH}")
        for s in stages.values():
            flag = "" if s.in_default_run else "  (not in run-all)"
            print(f"  {s.order:>3}  {s.name:<22} ticket {s.ticket:<4} {s.description}{flag}")
        return 0
    if cmd == "run":
        if not rest or rest[0] not in stages:
            print(f"unknown stage; choose from: {', '.join(stages)}")
            return 2
        return 0 if _run(stages[rest[0]], rest[1:]) else 1
    if cmd == "run-all":
        ok = True
        for s in stages.values():
            if s.in_default_run:
                ok = _run(s, []) and ok
        return 0 if ok else 1
    if cmd == "reset":
        _reset()
        return 0
    if cmd == "rebuild":
        return rebuild(stages, keep="--keep" in rest)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
