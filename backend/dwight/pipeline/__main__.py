"""python -m dwight.pipeline list
   python -m dwight.pipeline run <stage> [stage args...]
   python -m dwight.pipeline run-all            # every IN_DEFAULT_RUN stage, in ORDER
   python -m dwight.pipeline reset              # delete the store file (DWIGHT_DB)
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
        for suffix in ("", "-wal", "-shm"):
            p = config.DB_PATH.with_name(config.DB_PATH.name + suffix)
            if p.exists():
                p.unlink()
        print(f"deleted {config.DB_PATH}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
