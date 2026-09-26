"""Load the committed fixtures into the store, so any stage or panel can be
built before its upstream stages exist.

  run seed_fixtures             ingest fixtures/otlp/*.json + load fixtures/store/derived.json
                                (as if classify/detect/... had run; staging is cleared for
                                classified Sessions, like the real classify stage does)
  run seed_fixtures --raw-only  ingest only: Sessions + Calls + staged prompt content, nothing
                                derived (for building classify / detect against raw input)

Tip: point DWIGHT_DB at a scratch file so you don't mix fixtures into the real store.
"""
from __future__ import annotations

import argparse
import json

from dwight import config
from dwight.db import dumps
from dwight.ingest.otlp import ingest_file

ORDER = 5
TICKET = "01"
DESCRIPTION = "Load committed fixtures (OTLP Sessions + derived rows) into the store [--raw-only]"
IN_DEFAULT_RUN = False


def _insert(conn, table: str, row: dict) -> None:
    row = {(k + "_json" if isinstance(v, (list, dict)) or k in _JSON_COLS else k):
           (dumps(v) if (isinstance(v, (list, dict)) or k in _JSON_COLS) and v is not None else v)
           for k, v in row.items()}
    cols = ", ".join(row)
    conn.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))


_JSON_COLS = {"evidence", "resource_ids", "infra_refs", "source_resource_ids", "allowed_models",
              "suggested_models", "details"}


def run(conn, args):
    p = argparse.ArgumentParser(prog="seed_fixtures")
    p.add_argument("--raw-only", action="store_true")
    ns = p.parse_args(args)
    n = 0
    for f in sorted(config.OTLP_FIXTURES_DIR.glob("*.json")):
        n += len(ingest_file(conn, f))
    if ns.raw_only:
        return f"ingested {n} fixture Sessions (raw only)"
    d = json.loads((config.STORE_FIXTURES_DIR / "derived.json").read_text())
    for s in d["sessions"]:
        conn.execute("UPDATE sessions SET initiative_id=?, summary=?, complexity=?, classified_at=datetime('now') "
                     "WHERE session_id=?", (s["initiative_id"], s["summary"], s["complexity"], s["session_id"]))
        # mirror the classify stage: raw content is discarded once a Session is classified
        conn.execute("DELETE FROM staging_content WHERE session_id=?", (s["session_id"],))
        conn.execute("DELETE FROM trail_entries WHERE session_id=?", (s["session_id"],))
        conn.execute("DELETE FROM discoveries WHERE session_id=?", (s["session_id"],))
        conn.execute("DELETE FROM waste_findings WHERE session_id=?", (s["session_id"],))
    for table in ("trail_entries", "discoveries", "initiatives", "waste_findings", "recurring_discoveries",
                  "recommendations", "drafts", "policies", "eval_runs"):
        for row in d[table]:
            _insert(conn, table, row)
    conn.commit()
    return f"ingested {n} fixture Sessions + derived rows ({len(d['sessions'])} classified)"
