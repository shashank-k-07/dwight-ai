"""python -m dwight.synth <command>   (run from backend/)

  content   [--refresh]                      GLM-write the content library (only missing jobs; cached)
  generate  [--sessions N] [--seed S]        compose Sessions -> data/otlp/synthetic/ + data/ground-truth/ (no GLM)
  ingest                                     ingest data/otlp/synthetic/ into the store (DWIGHT_DB) via the OTLP path
  build     [--sessions N] [--seed S] [--ingest]   content (if missing) + generate (+ ingest)
  calibrate [--from DIR ...] [--rates-from YAML]   fit shapes to real-layer OTLP -> data/synthetic/calibration.yaml
  stats                                      print the last generation summary

One-command regenerate: python -m dwight.synth build --ingest
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dwight.synth import params as P


def _ingest() -> str:
    from dwight import db
    from dwight.ingest.otlp import ingest_file

    conn = db.connect()
    n, files = 0, sorted(P.OTLP_OUT_DIR.glob("day-*.jsonl"))
    t0 = time.time()
    for f in files:
        n += len(ingest_file(conn, f))
    conn.close()
    return f"ingested {n} synthetic Sessions from {len(files)} files in {time.time() - t0:.0f}s"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m dwight.synth", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["content", "generate", "ingest", "build", "calibrate", "stats"])
    ap.add_argument("--sessions", type=int)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--from", dest="from_paths", type=Path, nargs="+")
    ap.add_argument("--rates-from", type=Path)
    ns = ap.parse_args(argv)
    params = P.load()

    if ns.command == "calibrate":
        from dwight.synth.calibrate import calibrate
        doc = calibrate(ns.from_paths, ns.rates_from)
        print(json.dumps(doc["stats"], indent=1))
        print(f"wrote {P.CALIBRATION_PATH}; now run: python -m dwight.synth build --ingest")
        return 0
    if ns.command == "stats":
        print(P.SUMMARY_PATH.read_text() if P.SUMMARY_PATH.exists() else "no summary yet; run generate")
        return 0
    if ns.command == "ingest":
        print(_ingest())
        return 0

    from dwight.synth import content, generate

    if ns.command in ("content", "build"):
        library = content.build(params, refresh=ns.refresh)
        print(f"content library: {len(library['jobs'])} jobs cached; last build {json.dumps(library.get('last_build'))}")
        if ns.command == "content":
            return 0
    if ns.command in ("generate", "build"):
        library = content.load_library()
        t0 = time.time()
        summary = generate.generate(params, library, sessions=ns.sessions, seed=ns.seed)
        print(f"generated {summary['sessions']} Sessions in {time.time() - t0:.0f}s: "
              f"patterns {summary['waste_patterns']}, clean {summary['clean_sessions']}, "
              f"{summary['files']['otlp_bytes'] / 1e6:.1f} MB OTLP -> {P.OTLP_OUT_DIR}")
        print(f"ground truth -> {P.GROUND_TRUTH_PATH}")
    if ns.ingest:
        print(_ingest())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
