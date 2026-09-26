"""Batch driver: classify many Sessions with bounded concurrency, write the
derived fields, then DISCARD the raw prompt content.

Privacy rule (ADRs 0005, 0008), enforced here:
  * Raw content is read only from `staging_content`, only by this module.
  * Once a Session's derived fields are written (summary, Initiative,
    complexity, Trail, Discoveries), its `staging_content` rows are DELETED in
    the same transaction. Nothing derived is ever recomputed from prompts later.
  * The transcript is held in memory only for the one model call.
  * A Session whose model call fails keeps its staged content, so the next run
    can retry it; it is never half-written.

Which Sessions run: every Session that still has staged content. Staging is
deleted on success, so "has staged content" = "not classified since its last
ingest"; re-running the stage only picks up new or failed Sessions. A Session
re-ingested from OTLP gets fresh staging and is classified again (how ticket 08
can re-score after a prompt change).

Concurrency: the model calls run on a thread pool (default 8 workers,
DWIGHT_CLASSIFY_WORKERS); all SQLite reads and writes stay on the calling
thread. At most 2 x workers transcripts are in memory at once. Cost: 1 model
call per Session, up to 3 when the output fails validation (glm.chat_json
re-asks), plus `attempts` outer retries with backoff on API errors.
"""
from __future__ import annotations

import os
import random
import sqlite3
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone

from dwight import glm
from dwight.classifier.model import Candidate, Classification, candidates, classify_transcript
from dwight.classifier.trail import build_trail
from dwight.classifier.transcript import load_staged, render_transcript

DEFAULT_WORKERS = int(os.environ.get("DWIGHT_CLASSIFY_WORKERS", "8"))
DEFAULT_ATTEMPTS = 3


@dataclass
class RunStats:
    selected: int = 0
    classified: int = 0
    failed: int = 0
    attempts: int = 0
    trail_entries: int = 0
    discoveries: int = 0
    by_initiative: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    no_content: int = 0      # unclassified Sessions with nothing staged (content never sent, or already discarded)

    def line(self) -> str:
        calls = f"{self.attempts / self.classified:.2f}" if self.classified else "0"
        s = (f"classified {self.classified}/{self.selected} Sessions into {len(self.by_initiative)} Initiatives; "
             f"{self.trail_entries} Trail entries, {self.discoveries} Discoveries; {calls} attempts/Session; "
             f"staged content deleted for {self.classified}")
        if self.failed:
            s += f"; {self.failed} failed (staging kept for retry): " + "; ".join(
                f"{k}: {v}" for k, v in list(self.errors.items())[:3])
        if self.no_content:
            s += f"; {self.no_content} unclassified Sessions have no staged content"
        return s


def pending_sessions(conn: sqlite3.Connection, *, session_ids: list[str] | None = None,
                     dataset: str | None = None, limit: int | None = None) -> list[str]:
    """Sessions that still have staged content, oldest first."""
    sql = ("SELECT s.session_id FROM sessions s WHERE EXISTS "
           "(SELECT 1 FROM staging_content sc WHERE sc.session_id = s.session_id)")
    params: list = []
    if session_ids:
        sql += f" AND s.session_id IN ({','.join('?' * len(session_ids))})"
        params += session_ids
    if dataset:
        sql += " AND s.dataset = ?"
        params.append(dataset)
    sql += " ORDER BY s.started_at, s.session_id"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [r[0] for r in conn.execute(sql, params)]


def upsert_initiatives(conn: sqlite3.Connection, cands: list[Candidate]) -> None:
    conn.executemany(
        "INSERT INTO initiatives (initiative_id, name, description, business_function) VALUES (?,?,?,?) "
        "ON CONFLICT(initiative_id) DO UPDATE SET name=excluded.name, description=excluded.description, "
        "business_function=excluded.business_function",
        [(c.initiative_id, c.name, c.description, c.business_function) for c in cands])


def refresh_initiative_totals(conn: sqlite3.Connection) -> None:
    """session_count and Spend (Measured, sum of Session spend_usd) per Initiative."""
    conn.execute(
        "UPDATE initiatives SET "
        "session_count = (SELECT COUNT(*) FROM sessions s WHERE s.initiative_id = initiatives.initiative_id), "
        "spend_usd = (SELECT COALESCE(SUM(s.spend_usd), 0) FROM sessions s "
        "             WHERE s.initiative_id = initiatives.initiative_id)")


def write_result(conn: sqlite3.Connection, session_id: str, c: Classification) -> tuple[int, int]:
    """Store one Session's derived fields and delete its raw content. Idempotent:
    the Session's Trail and Discoveries are replaced, not appended."""
    trail = build_trail(conn, session_id)  # needs the staged tool arguments, so before the delete
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    conn.execute("DELETE FROM trail_entries WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM discoveries WHERE session_id=?", (session_id,))
    conn.executemany("INSERT INTO trail_entries (session_id, position, resource_id, tokens, call_seq) "
                     "VALUES (?,?,?,?,?)",
                     [(session_id, t.position, t.resource_id, t.tokens, t.call_seq) for t in trail])
    conn.executemany("INSERT INTO discoveries (session_id, idx, statement, call_seq) VALUES (?,?,?,?)",
                     [(session_id, i, d.statement, d.call_seq) for i, d in enumerate(c.discoveries)])
    conn.execute("UPDATE sessions SET initiative_id=?, summary=?, complexity=?, classified_at=? WHERE session_id=?",
                 (c.initiative_id, c.summary, c.complexity, now, session_id))
    # ADRs 0005/0008: the raw prompt content is discarded now that the derived fields exist.
    conn.execute("DELETE FROM staging_content WHERE session_id=?", (session_id,))
    return len(trail), len(c.discoveries)


def _classify_with_retry(transcript: str, cands: list[Candidate], context: dict, max_seq: int | None,
                         tier: str | None, attempts: int) -> tuple[Classification, int]:
    for i in range(attempts):
        try:
            return classify_transcript(transcript, cands, context=context, max_seq=max_seq, tier=tier), i + 1
        except glm.GLMNotConfigured:
            raise
        except Exception:  # noqa: BLE001  API error, timeout, invalid output: back off and retry
            if i == attempts - 1:
                raise
            time.sleep(min(30.0, 2.0 * 2 ** i) + random.random())
    raise AssertionError("unreachable")


def _prepare(conn: sqlite3.Connection, session_id: str) -> tuple[str, dict, int | None]:
    row = conn.execute("SELECT team, business_function, call_count FROM sessions WHERE session_id=?",
                       (session_id,)).fetchone()
    transcript = render_transcript(load_staged(conn, session_id))
    context = {"team": row["team"], "business_function": row["business_function"]} if row else {}
    max_seq = conn.execute("SELECT MAX(seq) FROM calls WHERE session_id=?", (session_id,)).fetchone()[0]
    return transcript, context, max_seq


def classify_sessions(conn: sqlite3.Connection, session_ids: list[str], *, workers: int = DEFAULT_WORKERS,
                      tier: str | None = None, attempts: int = DEFAULT_ATTEMPTS,
                      cands: list[Candidate] | None = None, progress_every: int = 100) -> RunStats:
    cands = cands if cands is not None else candidates()
    if not cands:
        raise RuntimeError("no candidate Initiatives: data/company/org.yaml is missing or empty")
    stats = RunStats(selected=len(session_ids))
    upsert_initiatives(conn, cands)
    conn.commit()

    def finish(sid: str, fut: Future) -> None:
        try:
            c, tries = fut.result()
        except glm.GLMNotConfigured:
            raise
        except Exception as e:  # noqa: BLE001
            stats.failed += 1
            stats.errors[sid] = f"{type(e).__name__}: {str(e)[:160]}"
            return
        n_trail, n_disc = write_result(conn, sid, c)
        conn.commit()
        stats.classified += 1
        stats.attempts += tries
        stats.trail_entries += n_trail
        stats.discoveries += n_disc
        stats.by_initiative[c.initiative_id] = stats.by_initiative.get(c.initiative_id, 0) + 1
        done = stats.classified + stats.failed
        if progress_every and done % progress_every == 0:
            print(f"[classify] {done}/{stats.selected} ({stats.failed} failed)", file=sys.stderr, flush=True)

    w = max(1, workers)
    inflight: dict[Future, str] = {}
    with ThreadPoolExecutor(max_workers=w) as pool:
        for sid in session_ids:
            transcript, context, max_seq = _prepare(conn, sid)
            inflight[pool.submit(_classify_with_retry, transcript, cands, context, max_seq, tier, attempts)] = sid
            del transcript
            if len(inflight) >= 2 * w:
                done, _ = wait(inflight, return_when=FIRST_COMPLETED)
                for f in done:
                    finish(inflight.pop(f), f)
        for f in as_completed(list(inflight)):
            finish(inflight.pop(f), f)

    refresh_initiative_totals(conn)
    stats.no_content = conn.execute(
        "SELECT COUNT(*) FROM sessions s WHERE s.classified_at IS NULL AND NOT EXISTS "
        "(SELECT 1 FROM staging_content sc WHERE sc.session_id = s.session_id)").fetchone()[0]
    conn.commit()
    return stats
