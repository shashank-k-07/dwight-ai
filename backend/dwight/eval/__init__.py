"""Classifier accuracy eval (ticket 08, build-spec §4.3 / §5).

Scores the classifier's Initiative choice against the synthetic ground truth
(data/ground-truth/synthetic_sessions.jsonl) and records the result in
`eval_runs`, which the closing-numbers strip serves.

This package and the acceptance checks (15) are the ONLY code allowed to read
data/ground-truth/. Ground truth is used for picking the sample and for scoring,
never shown to the classifier: the classifier runs through the normal
`dwight.classifier.classify_sessions` path, which knows nothing about it.

Two modes (CLI: `python -m dwight.pipeline run eval_classifier --help`):

  * score   score what is already classified in the store (e.g. 15's full run),
            without any model calls; writes one eval_runs row.
  * sample  pick a fixed, stratified sample of synthetic Sessions, re-ingest just
            those from the OTLP files (classifying deletes staging, so this
            restores their content), classify them with the current prompt, then
            score them; writes one eval_runs row. Same seed = same sample, so a
            before/after prompt comparison is fair.
"""
from __future__ import annotations

import json
import random
import re
import sqlite3
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dwight import config

GROUND_TRUTH_PATH = config.GROUND_TRUTH_DIR / "synthetic_sessions.jsonl"
SYNTHETIC_OTLP_DIR = config.DATA_DIR / "otlp" / "synthetic"

DEFAULT_PER_INITIATIVE = 20
DEFAULT_AMBIGUOUS_PER_INITIATIVE = 6
DEFAULT_SEED = 8


@dataclass(frozen=True)
class Truth:
    session_id: str
    initiative_id: str
    complexity: str | None
    ambiguous: bool


def load_truth(path: Path | str = GROUND_TRUTH_PATH) -> dict[str, Truth]:
    out: dict[str, Truth] = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        out[r["session_id"]] = Truth(r["session_id"], r["initiative_id"], r.get("complexity"),
                                     bool(r.get("ambiguous")))
    return out


def stratified_sample(truth: dict[str, Truth], *, per_initiative: int = DEFAULT_PER_INITIATIVE,
                      ambiguous_per_initiative: int = DEFAULT_AMBIGUOUS_PER_INITIATIVE,
                      seed: int = DEFAULT_SEED) -> list[str]:
    """`per_initiative` Sessions from every Initiative, of which
    `ambiguous_per_initiative` are ambiguous prompts (fewer if the Initiative has
    fewer). Deterministic for a given ground-truth file and seed."""
    rng = random.Random(seed)
    by_init: dict[str, dict[bool, list[str]]] = defaultdict(lambda: {True: [], False: []})
    for t in truth.values():
        by_init[t.initiative_id][t.ambiguous].append(t.session_id)
    picked: list[str] = []
    for iid in sorted(by_init):
        amb, clear = sorted(by_init[iid][True]), sorted(by_init[iid][False])
        n_amb = min(ambiguous_per_initiative, len(amb), per_initiative)
        n_clear = min(per_initiative - n_amb, len(clear))
        picked += rng.sample(amb, n_amb) + rng.sample(clear, n_clear)
    return sorted(picked)


# --- re-ingest ------------------------------------------------------------------------
def reingest(conn: sqlite3.Connection, session_ids: list[str], otlp_dir: Path | str = SYNTHETIC_OTLP_DIR) -> int:
    """Ingest only the payloads that carry these Sessions (one JSON line per
    payload). Re-ingest restores staged content, so the classify stage picks the
    Session up again. Returns how many Sessions were written."""
    from dwight.ingest.otlp import ingest_payload

    wanted = set(session_ids)
    remaining = set(wanted)
    written: set[str] = set()
    files = sorted(Path(otlp_dir).rglob("*.jsonl")) + sorted(Path(otlp_dir).rglob("*.json"))
    for f in files:
        with open(f) as fh:
            for line in fh:
                if not line.strip() or not (set(_QUOTED_ID.findall(line)) & remaining):
                    continue
                for sid in ingest_payload(conn, json.loads(line)):
                    if sid in wanted:
                        written.add(sid)
                        remaining.discard(sid)
                if not remaining:
                    return len(written)
    return len(written)


# Any quoted string that looks like an id; used only to skip payloads cheaply.
_QUOTED_ID = re.compile(r'"([\w.:-]{3,80})"')


# --- scoring --------------------------------------------------------------------------
def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def score(predictions: dict[str, str], truth: dict[str, Truth],
          complexities: dict[str, str | None] | None = None) -> dict:
    """predictions: session_id -> predicted initiative_id. Sessions without ground
    truth are ignored. Returns accuracy plus a per-Initiative confusion summary."""
    pairs = [(sid, truth[sid], p) for sid, p in predictions.items() if sid in truth]
    n = len(pairs)
    correct = sum(1 for _, t, p in pairs if t.initiative_id == p)
    amb = [(t, p) for _, t, p in pairs if t.ambiguous]
    clear = [(t, p) for _, t, p in pairs if not t.ambiguous]

    confusion: dict[str, Counter] = defaultdict(Counter)
    predicted_as: Counter = Counter()
    for _, t, p in pairs:
        confusion[t.initiative_id][p] += 1
        predicted_as[p] += 1
    per_init = {}
    for iid in sorted(confusion):
        row = confusion[iid]
        total, hit = sum(row.values()), row.get(iid, 0)
        per_init[iid] = {
            "n": total, "correct": hit, "recall": _rate(hit, total),
            "precision": _rate(hit, predicted_as.get(iid, 0)),
            "confused_with": {k: v for k, v in row.most_common() if k != iid},
        }
    pairs_off = Counter()
    for iid, row in confusion.items():
        for p, c in row.items():
            if p != iid:
                pairs_off[f"{iid} -> {p}"] += c

    # Population share of ambiguous prompts, to re-weight a stratified sample.
    pop_amb = sum(1 for t in truth.values() if t.ambiguous) / len(truth) if truth else 0.0
    acc_amb = _rate(sum(1 for t, p in amb if t.initiative_id == p), len(amb))
    acc_clear = _rate(sum(1 for t, p in clear if t.initiative_id == p), len(clear))
    weighted = (round(acc_clear * (1 - pop_amb) + acc_amb * pop_amb, 4)
                if acc_amb is not None and acc_clear is not None else None)

    out = {
        "n_sessions": n, "correct": correct, "accuracy": _rate(correct, n) or 0.0,
        "accuracy_ambiguous": acc_amb, "n_ambiguous": len(amb),
        "accuracy_clear": acc_clear, "n_clear": len(clear),
        "accuracy_population_weighted": weighted, "population_ambiguous_share": round(pop_amb, 4),
        "per_initiative": per_init,
        "top_confusions": dict(pairs_off.most_common(10)),
    }
    if complexities:
        cx = [(truth[sid].complexity, complexities.get(sid)) for sid, _, _ in pairs
              if truth[sid].complexity and complexities.get(sid)]
        out["complexity_accuracy"] = _rate(sum(1 for a, b in cx if a == b), len(cx))
    return out


def classified_predictions(conn: sqlite3.Connection, session_ids: list[str] | None = None,
                           since: str | None = None) -> tuple[dict[str, str], dict[str, str | None]]:
    sql = "SELECT session_id, initiative_id, complexity FROM sessions WHERE classified_at IS NOT NULL " \
          "AND initiative_id IS NOT NULL"
    params: list = []
    if since:
        sql += " AND classified_at >= ?"
        params.append(since)
    rows = conn.execute(sql, params).fetchall()
    keep = set(session_ids) if session_ids is not None else None
    preds, cx = {}, {}
    for sid, iid, c in rows:
        if keep is None or sid in keep:
            preds[sid], cx[sid] = iid, c
    return preds, cx


def record(conn: sqlite3.Connection, result: dict, *, label: str, extra: dict | None = None) -> str:
    eval_id = "eval-" + uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    details = {**result, **(extra or {})}
    conn.execute("INSERT INTO eval_runs (eval_id, created_at, label, accuracy, n_sessions, details_json) "
                 "VALUES (?,?,?,?,?,?)",
                 (eval_id, now, label, result["accuracy"], result["n_sessions"], json.dumps(details)))
    conn.commit()
    return eval_id


def latest(conn: sqlite3.Connection) -> dict | None:
    """The most recent eval run (what the closing-numbers strip shows)."""
    row = conn.execute("SELECT eval_id, created_at, label, accuracy, n_sessions FROM eval_runs "
                       "ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return {"eval_id": row[0], "created_at": row[1], "label": row[2], "accuracy": row[3], "n_sessions": row[4]}


def report(result: dict, label: str) -> str:
    """Human-readable confusion summary."""
    lines = [f"eval {label}: accuracy {result['accuracy']:.3f} ({result['correct']}/{result['n_sessions']})"
             f"; clear {result['accuracy_clear']} (n={result['n_clear']})"
             f"; ambiguous {result['accuracy_ambiguous']} (n={result['n_ambiguous']})"
             f"; population-weighted {result['accuracy_population_weighted']}"
             + (f"; complexity {result['complexity_accuracy']}" if result.get("complexity_accuracy") is not None
                else ""),
             f"  {'initiative':<27} {'n':>4} {'recall':>7} {'prec':>6}  confused with"]
    for iid, r in result["per_initiative"].items():
        conf = ", ".join(f"{k} {v}" for k, v in r["confused_with"].items())
        prec = "-" if r["precision"] is None else f"{r['precision']:.2f}"
        lines.append(f"  {iid:<27} {r['n']:>4} {r['recall']:>7.2f} {prec:>6}  {conf}")
    return "\n".join(lines)
