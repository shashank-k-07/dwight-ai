"""Stage: repeated_discoveries (ticket 11, build-spec §4.6.2).

Per Initiative: group its Discoveries by meaning with a model pass
(_discovery_clusters.py; embeddings aren't available), then keep each cluster
reached separately in enough Sessions as a RecurringDiscovery of form
`repeated_discovery`.

  run repeated_discoveries [--initiative ID ...] [--min-sessions 5] [--min-share 0.2]
                           [--floor 2] [--batch-size 100] [--workers 4] [--tier T]

Reads:  discoveries, sessions (initiative_id, experiment), calls (spend up to call_seq)
Writes: recurring_discoveries WHERE form='repeated_discovery' (only those rows; common_path is ticket 10's)
Only stored Discoveries, never prompt content: this stage does not touch
staging_content (ADR 0008).

Rules (all computed in code, never by the model):
- Population: the Initiative's Sessions except `experiment=after` runs (they ran
  with the Draft loaded, so they would dilute the share; same rule as ticket 10).
- A cluster counts once per Session. It is repeated when it is found in at least
  `floor` Sessions (a one-off is never "repeated") and in >= `min_sessions`
  Sessions or >= `min_share` of the population.
- spend_usd = for each of those Sessions, the Spend of its Calls from the start up
  to and including the Call where the Discovery was established (`call_seq`; the
  earliest one if the Session found it twice), summed across Sessions. Measured,
  and a conservative upper bound on what a memory entry saves.
"""
from __future__ import annotations

import argparse
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Iterable, Mapping

from dwight import db
from dwight.db import dumps
from dwight.pipeline.stages._discovery_clusters import (DEFAULT_BATCH_SIZE, Cluster, cluster_statements)

ORDER = 50
TICKET = "11"
DESCRIPTION = "Per Initiative: group Discoveries by meaning (GLM) -> RecurringDiscovery(form=repeated_discovery), Measured"

FORM = "repeated_discovery"


@dataclass(frozen=True)
class Thresholds:
    min_sessions: int = int(os.environ.get("DWIGHT_RD_MIN_SESSIONS", 5))
    min_share: float = float(os.environ.get("DWIGHT_RD_MIN_SHARE", 0.2))
    floor: int = int(os.environ.get("DWIGHT_RD_FLOOR_SESSIONS", 2))

    def met(self, sessions: int, population: int) -> bool:
        share = sessions / population if population else 0.0
        return sessions >= self.floor and (sessions >= self.min_sessions or share >= self.min_share)


@dataclass(frozen=True)
class Discovery:
    session_id: str
    idx: int
    statement: str
    call_seq: int
    spend_upto_usd: float   # Spend of the Session's Calls with seq <= call_seq (Measured)

    @property
    def key(self) -> tuple[str, int]:
        return (self.session_id, self.idx)


def score(initiative_id: str, clusters: Iterable[Cluster], discoveries: Mapping[tuple[str, int], Discovery],
          population: int, thresholds: Thresholds = Thresholds()) -> list[dict]:
    """The repeated-Discovery rows for one Initiative, most widespread first."""
    found = []
    for c in clusters:
        per_session: dict[str, float] = {}
        for key in c.keys:
            d = discoveries[key]
            per_session[d.session_id] = min(per_session.get(d.session_id, d.spend_upto_usd), d.spend_upto_usd)
        n = len(per_session)
        if thresholds.met(n, population):
            found.append((c.statement, per_session))
    found.sort(key=lambda f: (-len(f[1]), -sum(f[1].values()), f[0]))
    return [{"recurring_discovery_id": f"rd-{initiative_id}-rep{i + 1:02d}", "initiative_id": initiative_id,
             "form": FORM, "resource_ids": None, "statement": statement, "tokens": None,
             "session_count": len(per_session), "session_share": round(len(per_session) / population, 4),
             "spend_usd": sum(per_session.values()), "evidence": sorted(per_session)}
            for i, (statement, per_session) in enumerate(found)]


def _population(conn) -> dict[str, int]:
    return {r["initiative_id"]: r["n"] for r in db.rows(
        conn, "SELECT initiative_id, COUNT(*) n FROM sessions WHERE initiative_id IS NOT NULL "
              "AND COALESCE(experiment, '') != 'after' GROUP BY initiative_id")}


def _discoveries(conn) -> dict[str, list[Discovery]]:
    out: dict[str, list[Discovery]] = {}
    for r in db.rows(conn, """
            SELECT s.initiative_id, d.session_id, d.idx, d.statement, d.call_seq,
                   (SELECT COALESCE(SUM(c.spend_usd), 0) FROM calls c
                     WHERE c.session_id = d.session_id AND c.seq <= d.call_seq) AS spend_upto_usd
              FROM discoveries d JOIN sessions s ON s.session_id = d.session_id
             WHERE s.initiative_id IS NOT NULL AND COALESCE(s.experiment, '') != 'after'
             ORDER BY s.initiative_id, d.session_id, d.idx"""):
        iid = r.pop("initiative_id")
        out.setdefault(iid, []).append(Discovery(**r))
    return out


def _analyse(initiative_id: str, found: list[Discovery], population: int, thresholds: Thresholds,
             batch_size: int, workers: int, tier: str | None, limiter: threading.Semaphore) -> list[dict]:
    if len({d.session_id for d in found}) < thresholds.floor:
        return []   # can't be repeated: skip the model call
    clusters = cluster_statements([(d.key, d.statement) for d in found], batch_size=batch_size,
                                  workers=workers, tier=tier, limiter=limiter)
    return score(initiative_id, clusters, {d.key: d for d in found}, population, thresholds)


def _insert(conn, row: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO recurring_discoveries (recurring_discovery_id, initiative_id, form, "
        "resource_ids_json, statement, tokens, session_count, session_share, spend_usd, evidence_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (row["recurring_discovery_id"], row["initiative_id"], row["form"], None, row["statement"], None,
         row["session_count"], row["session_share"], row["spend_usd"], dumps(row["evidence"])))


def run(conn, args):
    d = Thresholds()
    p = argparse.ArgumentParser(prog="repeated_discoveries")
    p.add_argument("--initiative", action="append", help="only these Initiatives (repeatable)")
    p.add_argument("--min-sessions", type=int, default=d.min_sessions)
    p.add_argument("--min-share", type=float, default=d.min_share)
    p.add_argument("--floor", type=int, default=d.floor, help="never repeated below this many Sessions")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Discoveries per model call")
    p.add_argument("--workers", type=int, default=int(os.environ.get("DWIGHT_RD_WORKERS", 4)),
                   help="max model calls in flight")
    p.add_argument("--tier", default=None, help="GLM tier/model (default: the model pool)")
    ns = p.parse_args(args)
    thresholds = Thresholds(ns.min_sessions, ns.min_share, ns.floor)

    population = _population(conn)
    discoveries = _discoveries(conn)
    targets = sorted(ns.initiative or population)
    limiter = threading.BoundedSemaphore(max(1, ns.workers))

    def work(iid: str):
        try:
            return iid, _analyse(iid, discoveries.get(iid, []), population.get(iid, 0), thresholds,
                                 ns.batch_size, ns.workers, ns.tier, limiter), None
        except Exception as e:  # noqa: BLE001 - one Initiative failing keeps its old rows
            return iid, None, e

    with ThreadPoolExecutor(max_workers=max(1, min(ns.workers, len(targets) or 1))) as pool:
        results = list(pool.map(work, targets))

    failed = [(iid, e) for iid, _, e in results if e is not None]
    written = 0
    for iid, rows, e in results:
        if e is not None:
            continue
        conn.execute("DELETE FROM recurring_discoveries WHERE form=? AND initiative_id=?", (FORM, iid))
        for row in rows:
            _insert(conn, row)
        written += len(rows)
    if not ns.initiative:   # a full run owns every repeated_discovery row: drop Initiatives that are gone
        keep = set(targets)
        for r in db.rows(conn, "SELECT DISTINCT initiative_id FROM recurring_discoveries WHERE form=?", (FORM,)):
            if r["initiative_id"] not in keep:
                conn.execute("DELETE FROM recurring_discoveries WHERE form=? AND initiative_id=?",
                             (FORM, r["initiative_id"]))
    conn.commit()
    n_disc = sum(len(discoveries.get(i, [])) for i in targets)
    msg = f"{written} repeated Discoveries from {n_disc} Discoveries across {len(targets)} Initiatives"
    if failed:
        raise RuntimeError(msg + "; failed (old rows kept): "
                           + ", ".join(f"{iid} ({type(e).__name__}: {e})" for iid, e in failed))
    return msg
