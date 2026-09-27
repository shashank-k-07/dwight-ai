"""Ingest OTLP JSON files into the store (and price every Call)."""
from __future__ import annotations

import argparse
from pathlib import Path

from dwight import config
from dwight.ingest.otlp import ingest_file

ORDER = 10
TICKET = "01"
DESCRIPTION = "OTLP JSON files/dirs -> Sessions + Calls, priced from prices.yaml (default: data/otlp/)"

DEFAULT_INBOX = config.DATA_DIR / "otlp"   # harness (03) -> data/otlp/real/, generator (07) -> data/otlp/synthetic/


def run(conn, args):
    p = argparse.ArgumentParser(prog="ingest")
    p.add_argument("paths", nargs="*", type=Path, default=[DEFAULT_INBOX])
    ns = p.parse_args(args)
    files: list[Path] = []
    for path in ns.paths:
        if path.is_dir():
            files += sorted(path.rglob("*.json")) + sorted(path.rglob("*.jsonl"))
        elif path.exists():
            files.append(path)
    sessions: list[str] = []
    for f in files:
        sessions += ingest_file(conn, f)
    return f"{len(sessions)} Sessions from {len(files)} files"
