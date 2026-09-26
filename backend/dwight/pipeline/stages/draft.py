"""Stage: draft (ticket 12, build-spec §4.6.3-4).

For each Initiative with a RecurringDiscovery:
  * common path -> initiative doc (Draft type initiative_doc). The source docs are
    re-fetched fresh from company-docs/ by resource_id; the model gets them plus the
    Initiative's Session summaries and Discoveries, and writes a consolidated doc of
    at most 25% of the common path's tokens (--target-share). Resources that aren't
    company docs (repo files, Perch pages) can't be fetched and are left out.
  * repeated Discoveries -> one memory file per Initiative (Draft type memory), one
    instruction-style line per repeated Discovery.
Each Draft is attached to the Initiative's Recommendation that cites the matching
Practice (recommend.library.DRAFT_PRACTICE), which gets the Draft's Estimated Saving.

  run draft [--initiative ID ...] [--target-share 0.25] [--no-glm] [--tier T] [--workers 4]
            [--out-dir DIR]

Reads:  recurring_discoveries, discoveries, sessions (summary, times), calls (model, input tokens),
        recommendations, company-docs/ (re-fetched by resource_id via dwight.company.company_doc_path)
Writes: drafts (its Initiatives' rows), recommendations.draft_id / usd / kind (the matching row),
        files <out-dir>/<initiative_id>.md and <initiative_id>.memory.md (default out/drafts/)
Never reads staging_content or any stored prompt (ADRs 0005, 0008).

Estimated Saving (code, never the model; build-spec §4.6.4):
  initiative doc = (common-path tokens - Draft tokens) x Sessions per month x input rate
  memory file    = sum of its repeated Discoveries' Measured spend_usd, per month
  where Sessions per month = Sessions that read the whole path / months observed,
  months observed = the analysed Sessions' time span in days / 30, at least 1 (a
  window shorter than a month is never extrapolated up), and input rate = the
  uncached input rate of the reading Sessions' Calls, weighted by input tokens.
  Both are Estimated until a before/after run exists (ticket 13 shows the Measured drop).

Idempotent: a Draft is only replaced once its replacement has been built, so a failed
model call keeps the previous Draft.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from dwight import config, db, pricing
from dwight.pipeline.stages import _drafter as d
from dwight.pipeline.stages.common_paths import analysed_session_ids, mean_tokens_per_read
from dwight.recommend import library as lib

ORDER = 70
TICKET = "12"
DESCRIPTION = "Drafter: common path -> initiative doc, repeated Discoveries -> memory file; attach to Recommendation; price Estimated Saving"

DEFAULT_TARGET_SHARE = 0.25
DAYS_PER_MONTH = 30.0


def draft_id(initiative_id: str, type_: str) -> str:
    return f"d-{initiative_id}-{'doc' if type_ == 'initiative_doc' else 'memory'}"


def draft_filename(initiative_id: str, type_: str) -> str:
    return f"{initiative_id}.md" if type_ == "initiative_doc" else f"{initiative_id}.memory.md"


def draft_files(initiative_id: str, out_dir: Path | None = None) -> dict[str, Path]:
    """Where this stage writes an Initiative's Drafts ({type: path}); for the harness (16)."""
    out = Path(out_dir or config.DRAFT_OUT_DIR)
    return {t: out / draft_filename(initiative_id, t) for t in ("initiative_doc", "memory")}


# ---------------------------------------------------------------- pricing (code only)

def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def months_observed(conn, session_ids: list[str]) -> float:
    if not session_ids:
        return 1.0
    marks = ",".join("?" * len(session_ids))
    lo, hi = conn.execute(f"SELECT MIN(started_at), MAX(ended_at) FROM sessions WHERE session_id IN ({marks})",
                          tuple(session_ids)).fetchone()
    if not lo or not hi:
        return 1.0
    days = (_ts(hi) - _ts(lo)).total_seconds() / 86400
    return max(days / DAYS_PER_MONTH, 1.0)


def input_rate(conn, session_ids: list[str]) -> float:
    """USD per uncached input token over these Sessions' Calls, weighted by input tokens."""
    if not session_ids:
        return 0.0
    marks = ",".join("?" * len(session_ids))
    tok = usd = 0.0
    for model, n in conn.execute(f"SELECT model, SUM(input_tokens) FROM calls WHERE session_id IN ({marks}) "
                                 f"GROUP BY model", tuple(session_ids)):
        try:
            rate = pricing.input_rate(model, cached=False)
        except pricing.UnknownModel:
            continue
        tok += n or 0
        usd += (n or 0) * rate
    return usd / tok if tok else 0.0


def doc_saving_usd(path_tokens: int, draft_tokens: int, sessions_per_month: float, rate: float) -> float:
    return max(path_tokens - draft_tokens, 0) * sessions_per_month * rate


def memory_saving_usd(spend_usd: float, months: float) -> float:
    return spend_usd / months


# ---------------------------------------------------------------- stage

def run(conn, args):
    p = argparse.ArgumentParser(prog="draft")
    p.add_argument("--initiative", action="append", help="only this Initiative (repeatable); default all with a RecurringDiscovery")
    p.add_argument("--target-share", type=float, default=DEFAULT_TARGET_SHARE,
                   help="initiative doc budget as a share of the common path's tokens (default 0.25)")
    p.add_argument("--no-glm", action="store_true", help="offline: memory files from the stored statements, no initiative docs")
    p.add_argument("--tier", default=None, help="model tier or name for the Drafter's calls (default: the pool)")
    p.add_argument("--workers", type=int, default=4, help="model calls in flight per initiative doc")
    p.add_argument("--out-dir", type=Path, default=None, help="where Draft files go (default out/drafts/)")
    ns = p.parse_args(args)
    out_dir = Path(ns.out_dir or config.DRAFT_OUT_DIR)

    initiatives = ns.initiative or [r["initiative_id"] for r in db.rows(
        conn, "SELECT DISTINCT initiative_id FROM recurring_discoveries ORDER BY 1")]
    notes = []
    if not ns.initiative:  # full run: drop Drafts of Initiatives that no longer have a RecurringDiscovery
        for iid, type_ in conn.execute("SELECT initiative_id, type FROM drafts").fetchall():
            if iid not in initiatives:
                _remove(conn, iid, type_, out_dir)
    for iid in initiatives:
        notes.extend(_draft_initiative(conn, iid, ns, out_dir))
        conn.commit()
    return f"{len(initiatives)} Initiatives" + (": " + "; ".join(notes) if notes else "")


def _draft_initiative(conn, iid: str, ns, out_dir: Path) -> list[str]:
    rds = db.rows(conn, "SELECT * FROM recurring_discoveries WHERE initiative_id=? "
                        "ORDER BY form, session_count DESC, recurring_discovery_id", (iid,))
    ini = conn.execute("SELECT name, description FROM initiatives WHERE initiative_id=?", (iid,)).fetchone()
    name, description = (ini["name"], ini["description"]) if ini else (iid, None)
    analysed = analysed_session_ids(conn, iid)
    months = months_observed(conn, analysed)
    notes: list[str] = []

    common = next((r for r in rds if r["form"] == "common_path"), None)
    if common is None:
        _remove(conn, iid, "initiative_doc", out_dir)
    elif ns.no_glm:
        notes.append(f"{iid}: initiative doc skipped (--no-glm)")
    else:
        try:
            note = _initiative_doc(conn, iid, name, description, common, analysed, months, ns, out_dir)
        except Exception as e:  # noqa: BLE001 - keep the previous Draft, report, carry on
            note = f"{iid}: initiative doc failed ({type(e).__name__}: {e}); kept the previous Draft"
        notes.append(note)

    reps = [r for r in rds if r["form"] == "repeated_discovery"]
    if reps:
        notes.append(_memory(conn, iid, name, reps, months, ns, out_dir))
    else:
        _remove(conn, iid, "memory", out_dir)
    return notes


def _initiative_doc(conn, iid, name, description, rd, analysed, months, ns, out_dir) -> str:
    resource_ids = rd.get("resource_ids") or []
    docs, skipped = d.fetch_source_docs(resource_ids)
    if not docs:
        _remove(conn, iid, "initiative_doc", out_dir)
        return f"{iid}: no initiative doc (none of the {len(resource_ids)} common-path resources is a company doc)"
    readers = rd.get("evidence") or []
    path_tokens = int(rd["tokens"] or 0)
    if skipped or not path_tokens:  # price only the part of the path the Draft replaces
        trail = db.rows(conn, "SELECT resource_id, tokens FROM trail_entries WHERE session_id IN "
                              f"({','.join('?' * len(analysed))})", tuple(analysed)) if analysed else []
        path_tokens = round(sum(mean_tokens_per_read(trail, doc.resource_id) for doc in docs))
    counted = sum(doc.tokens for doc in docs)
    base = min(path_tokens, counted) if path_tokens else counted
    target = int(base * ns.target_share)

    ctx = d.DocContext(
        initiative_id=iid, name=name, description=description,
        summaries=_distinct(conn, "SELECT summary FROM sessions WHERE session_id IN ({}) AND summary IS NOT NULL "
                                  "GROUP BY summary ORDER BY COUNT(*) DESC, summary", analysed, d.MAX_SUMMARIES),
        discoveries=_distinct(conn, "SELECT statement FROM discoveries WHERE session_id IN ({}) "
                                    "GROUP BY statement ORDER BY COUNT(*) DESC, statement", analysed, d.MAX_DISCOVERIES),
        readers=rd["session_count"], analysed=len(analysed), path_tokens=path_tokens, tier=ns.tier, workers=ns.workers)
    content = d.build_initiative_doc(ctx, docs, target)
    tokens = d.count_tokens(content)

    sessions_per_month = rd["session_count"] / months
    usd = doc_saving_usd(path_tokens, tokens, sessions_per_month, input_rate(conn, readers or analysed))
    _store(conn, iid, "initiative_doc", f"{name}: initiative doc", content, [doc.resource_id for doc in docs],
           tokens, path_tokens, "common_path", rd["recurring_discovery_id"], usd, out_dir)
    ratio = tokens / base if base else 0.0
    flag = "" if tokens <= target else f", OVER the {ns.target_share:.0%} target of {target}"
    extra = f", skipped {len(skipped)} non-doc resources" if skipped else ""
    return (f"{iid}: initiative doc {tokens} tokens = {ratio:.1%} of {base} source tokens "
            f"({len(docs)} docs{extra}{flag})")


def _memory(conn, iid, name, reps, months, ns, out_dir) -> str:
    log: list[str] = []
    lines = d.memory_lines([r["statement"] or "" for r in reps], use_glm=not ns.no_glm, tier=ns.tier, log=log)
    content = d.memory_file(name, lines)
    usd = sum(memory_saving_usd(r["spend_usd"] or 0.0, months) for r in reps)
    _store(conn, iid, "memory", f"{name}: memory file", content, [], d.count_tokens(content), None,
           "repeated_discovery", reps[0]["recurring_discovery_id"], usd, out_dir)
    return f"{iid}: memory file with {len(lines)} lines" + (f" ({log[0]})" if log else "")


def _distinct(conn, sql: str, session_ids: list[str], limit: int) -> list[str]:
    if not session_ids:
        return []
    q = sql.format(",".join("?" * len(session_ids))) + f" LIMIT {int(limit)}"
    return [r[0] for r in conn.execute(q, tuple(session_ids))]


def _recommendation_for(conn, iid: str, form: str, rd_id: str) -> str | None:
    r = conn.execute(
        "SELECT recommendation_id FROM recommendations WHERE target_type='initiative' AND target_id=? "
        "AND practice_id=? ORDER BY (recurring_discovery_id = ?) DESC, rank, recommendation_id LIMIT 1",
        (iid, lib.DRAFT_PRACTICE[form], rd_id)).fetchone()
    return r[0] if r else None


def _detach(conn, iid: str, type_: str) -> None:
    olds = [r[0] for r in conn.execute("SELECT draft_id FROM drafts WHERE initiative_id=? AND type=?", (iid, type_))]
    if olds:
        conn.execute(f"UPDATE recommendations SET draft_id=NULL WHERE draft_id IN ({','.join('?' * len(olds))})",
                     tuple(olds))
        conn.execute("DELETE FROM drafts WHERE initiative_id=? AND type=?", (iid, type_))


def _remove(conn, iid: str, type_: str, out_dir: Path) -> None:
    """The Initiative no longer has this form of RecurringDiscovery: drop its Draft."""
    _detach(conn, iid, type_)
    f = out_dir / draft_filename(iid, type_)
    if f.exists():
        f.unlink()


def _store(conn, iid, type_, title, content, source_ids, tokens, source_tokens, form, rd_id, usd, out_dir) -> None:
    _detach(conn, iid, type_)
    did = draft_id(iid, type_)
    rec = _recommendation_for(conn, iid, form, rd_id)
    conn.execute(
        "INSERT INTO drafts (draft_id, recommendation_id, initiative_id, type, title, filename, content, "
        "source_resource_ids_json, tokens, source_tokens) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (did, rec, iid, type_, title, draft_filename(iid, type_), content, db.dumps(source_ids), tokens,
         source_tokens))
    if rec:
        conn.execute("UPDATE recommendations SET draft_id=?, usd=?, kind='estimated' WHERE recommendation_id=?",
                     (did, round(usd, 8), rec))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / draft_filename(iid, type_)).write_text(content)
