"""Agent harness CLI (run from backend/).

  python -m dwight.harness plan                         # the 40-Session real-layer plan
  python -m dwight.harness real [--only real-001,real-007] [--variant cache_miss] [--workers 4] [--ingest]
  python -m dwight.harness storage --experiment before --prefix real-scr-b [--tasks t01,t02]
                                   [--context-file PATH ...] [--model MODEL] [--repeat N] [--ingest]
  python -m dwight.harness storage --settings ../data/real_scr_settings.json --experiment before|after ...
                                   # model + settings pinned by the file (04 writes it, 16 reuses it)
  python -m dwight.harness storage-settings --model MODEL [--out ../data/real_scr_settings.json]
  python -m dwight.harness stats                        # -> data/real_layer_stats.json

Outputs: data/otlp/real/<session_id>.json (OTLP JSON), data/real_layer_runs.json
(settings + outcome), data/ground-truth/real_layer_labels.yaml (planted patterns).
Live runs call the model through dwight.glm (SCIFORIUM_API_KEY in .env).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dwight.harness import runner, settings, stats, tasks


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m dwight.harness")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("plan", help="print the real-layer Session plan")

    r = sub.add_parser("real", help="run real-layer Sessions against the pinned OSS repo")
    r.add_argument("--only", help="comma-separated session ids (default: all)")
    r.add_argument("--variant", choices=["clean", "redundant_read", "cache_miss", "runaway_loop"])
    r.add_argument("--workers", type=int, default=runner.MAX_WORKERS)
    r.add_argument("--out", type=Path, default=runner.OTLP_REAL_DIR)
    r.add_argument("--ingest", action="store_true", help="also ingest into the store (DWIGHT_DB)")

    s = sub.add_parser("storage", help="run the storage cost reduction tasks (tickets 04/16)")
    s.add_argument("--experiment", choices=["before", "after", "none"], required=True)
    s.add_argument("--prefix", required=True, help="session id prefix, e.g. real-scr-b")
    s.add_argument("--tasks", help="comma-separated task ids or t-numbers (t01,t02)")
    s.add_argument("--context-file", type=Path, action="append", default=[],
                   help="file loaded into the Agent's starting context (repeatable)")
    s.add_argument("--settings", type=Path,
                   help="settings file (storage-settings) that pins model, max-calls, repeat, tasks, workers; "
                        "refuses to run if the harness drifted since it was written")
    s.add_argument("--model", help="model string (default: glm.model_for())")
    s.add_argument("--repeat", type=int)
    s.add_argument("--max-calls", type=int)
    s.add_argument("--workers", type=int)
    s.add_argument("--out", type=Path, default=runner.OTLP_REAL_DIR)
    s.add_argument("--ingest", action="store_true")

    w = sub.add_parser("storage-settings", help="write the storage-run settings file (pins one model)")
    w.add_argument("--model", required=True)
    w.add_argument("--max-calls", type=int, default=tasks.STORAGE_MAX_CALLS)
    w.add_argument("--repeat", type=int, default=1)
    w.add_argument("--tasks", help="comma-separated task ids (default: all)")
    w.add_argument("--workers", type=int, default=runner.MAX_WORKERS)
    w.add_argument("--out", type=Path, default=settings.DEFAULT_PATH)

    sub.add_parser("stats", help="write data/real_layer_stats.json")

    a = p.parse_args(argv)
    if a.cmd == "plan":
        for i, spec in enumerate(tasks.real_specs()):
            print(f"{spec.session_id}  {spec.variant:<14} {spec.task_id:<30} {spec.team} / {spec.member_id}")
        return 0
    if a.cmd == "real":
        specs = tasks.real_specs()
        if a.only:
            ids = set(a.only.split(","))
            specs = [x for x in specs if x.session_id in ids]
        if a.variant:
            specs = [x for x in specs if x.variant == a.variant]
        _, failed = runner.run_batch(specs, workers=a.workers, out_dir=a.out, ingest=a.ingest)
        print(f"{len(specs) - len(failed)} ok, {len(failed)} failed{': ' + ','.join(failed) if failed else ''}")
        return 1 if failed else 0
    if a.cmd == "storage":
        opts = {"model": a.model, "max_calls": a.max_calls, "repeat": a.repeat, "workers": a.workers,
                "tasks": a.tasks.split(",") if a.tasks else None}
        if a.settings:
            given = [k for k, v in opts.items() if v is not None]
            if given:
                p.error(f"--settings pins {', '.join(given)}; don't pass them too")
            opts = settings.load(a.settings)
        specs = tasks.storage_specs(
            experiment=None if a.experiment == "none" else a.experiment, session_prefix=a.prefix,
            task_ids=opts["tasks"], context_files=a.context_file, model=opts["model"],
            repeat=opts["repeat"] or 1, max_calls=opts["max_calls"] or tasks.STORAGE_MAX_CALLS)
        results, failed = runner.run_batch(specs, workers=opts["workers"] or runner.MAX_WORKERS, out_dir=a.out,
                                           ingest=a.ingest)
        passed = sum(1 for x in results if x.task_success)
        print(f"{passed}/{len(results)} tasks passed, {len(failed)} failed to run")
        return 1 if failed else 0
    if a.cmd == "storage-settings":
        settings.write(a.out, model=a.model, max_calls=a.max_calls, repeat=a.repeat, workers=a.workers,
                       task_ids=a.tasks.split(",") if a.tasks else None)
        print(f"wrote {a.out}")
        return 0
    if a.cmd == "stats":
        out = stats.write()
        print(json.dumps({k: out[k] for k in ("models", "cache", "pattern_rates")}, indent=1))
        print(f"wrote {stats.STATS_PATH}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
