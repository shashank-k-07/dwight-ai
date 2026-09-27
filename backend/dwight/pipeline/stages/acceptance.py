"""Acceptance checks (ticket 15): the spec's criteria, scored on the store. Not part of run-all.

Run after the whole pipeline (see `python -m dwight.pipeline rebuild`). Hard checks
fail the stage (non-zero exit); informational ones are only reported.

Hard:
  detectors   every planted real-layer run (data/ground-truth/real_layer_labels.yaml) is
              flagged with its pattern, and clean real runs have no Measured finding unless
              the harness itself recorded that waste in the run (its `observed` block: a
              duplicate tool result, or an identical-call streak >= the loop minimum).
              Cache Miss counts as "not observable" on models whose provider never reports
              cache reads (pricing.reports_cache_usage). No Model Overkill on the real layer.
  recurring   the planted Initiative (planted_facts.yaml) has its 4 company-docs/ docs in its
              common path and the STORAGE_ENV fact as a repeated Discovery
  draft       draft_check passes (<= 25% of source tokens, every doc-resident planted fact kept)
  recommend   the top 3 Initiatives by Spend each have >= 2 Recommendations, each citing a
              real Practice and at least one real Infra Profile item
  endpoints   every API endpoint serves from the store, and the store has Drafts
Informational:
  Measured Waste on the real layer (dataset='real') vs the full dataset; the bare-bucket
  fact as a repeated Discovery; the classifier and detectors scored against the synthetic
  ground truth (data/ground-truth/synthetic_sessions.jsonl), over classified Sessions.

Writes the full report to <out dir>/acceptance.json. Like draft_check and the eval, this
is allowed to read data/ground-truth/; no pipeline stage in run-all may.

  run acceptance [--loop-min 3]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter

import yaml

from dwight import config, db, pricing
from dwight.pipeline.stages import draft_check
from dwight.recommend import library as lib

ORDER = 80
TICKET = "15"
DESCRIPTION = "Acceptance checks: detectors vs real labels, both RecurringDiscovery forms, Draft, Recommendations, endpoints"
IN_DEFAULT_RUN = False

REAL_LABELS = config.GROUND_TRUTH_DIR / "real_layer_labels.yaml"
SYNTH_LABELS = config.GROUND_TRUTH_DIR / "synthetic_sessions.jsonl"
PATTERNS = ("redundant_read", "cache_miss", "runaway_loop", "model_overkill")


class AcceptanceFailed(RuntimeError):
    pass


def _usd(x: float, kind: str) -> str:
    return f"${x:,.4f} ({kind.capitalize()})"


# ---------------------------------------------------------------- detectors vs the real labels

def _findings(conn, dataset: str | None = None) -> dict[str, dict[str, set[str]]]:
    """{session_id: {kind: {pattern}}}"""
    sql = "SELECT w.session_id, w.pattern, w.kind FROM waste_findings w JOIN sessions s USING (session_id)"
    out: dict[str, dict[str, set[str]]] = {}
    for sid, pat, kind in conn.execute(sql + (" WHERE s.dataset=?" if dataset else ""), (dataset,) if dataset else ()):
        out.setdefault(sid, {}).setdefault(kind, set()).add(pat)
    return out


def _observable(conn, sid: str, pattern: str) -> bool:
    if pattern != "cache_miss":
        return True
    models = [r[0] for r in conn.execute("SELECT DISTINCT model FROM calls WHERE session_id=?", (sid,))]
    return any(pricing.reports_cache_usage(m) for m in models)


def _explained(observed: dict, pattern: str, loop_min: int) -> bool:
    """Did the harness itself record this waste in a clean run? (Then the finding is genuine.)"""
    if pattern == "redundant_read":
        return (observed.get("duplicate_tool_results") or 0) > 0
    if pattern == "runaway_loop":
        return (observed.get("max_identical_consecutive_tool_calls") or 0) >= loop_min
    return False


def check_detectors(conn, loop_min: int) -> dict:
    labels = (yaml.safe_load(REAL_LABELS.read_text()) or {}).get("sessions") or {}
    present = {r[0] for r in conn.execute("SELECT session_id FROM sessions WHERE dataset='real'")}
    found = _findings(conn, "real")
    per: dict[str, dict] = {}
    clean = {"sessions": 0, "with_measured": [], "unexplained": []}
    extra: list[str] = []
    for sid, lab in sorted(labels.items()):
        if sid not in present:
            continue
        pat = lab.get("planted_pattern") or "none"
        measured = found.get(sid, {}).get("measured", set())
        if pat == "none":
            clean["sessions"] += 1
            if measured:
                clean["with_measured"].append(f"{sid}: {','.join(sorted(measured))}")
                if not all(_explained(lab.get("observed") or {}, p, loop_min) for p in measured):
                    clean["unexplained"].append(sid)
            continue
        row = per.setdefault(pat, {"planted": 0, "flagged": 0, "not_observable": 0, "missed": []})
        row["planted"] += 1
        flagged = pat in measured or pat in found.get(sid, {}).get("estimated", set())
        if flagged:
            row["flagged"] += 1
        elif not _observable(conn, sid, pat):
            row["not_observable"] += 1
        else:
            row["missed"].append(sid)
        others = measured - {pat}
        if others:
            extra.append(f"{sid} ({pat}) also {','.join(sorted(others))}")
    overkill = conn.execute("SELECT COUNT(*) FROM waste_findings w JOIN sessions s USING (session_id) "
                            "WHERE s.dataset='real' AND w.pattern='model_overkill'").fetchone()[0]
    unlabelled = sorted(present - set(labels))
    ok = (not clean["unexplained"] and overkill == 0
          and all(not r["missed"] for r in per.values()) and bool(per))
    return {"ok": ok, "per_pattern": per, "clean": clean, "extra_findings": extra,
            "real_model_overkill_findings": overkill, "unlabelled_real_sessions": len(unlabelled)}


# ---------------------------------------------------------------- Measured Waste, real vs full

def waste_totals(conn) -> dict:
    def q(where: str) -> dict:
        spend, n = conn.execute(f"SELECT COALESCE(SUM(spend_usd),0), COUNT(*) FROM sessions s {where}").fetchone()
        rows = conn.execute(f"SELECT w.kind, w.pattern, SUM(w.usd) FROM waste_findings w JOIN sessions s "
                            f"USING (session_id) {where} GROUP BY 1, 2").fetchall()
        measured = sum(u for k, _, u in rows if k == "measured")
        estimated = sum(u for k, _, u in rows if k == "estimated")
        return {"sessions": n, "spend_measured": spend, "measured_waste": measured, "estimated_saving": estimated,
                "measured_by_pattern": {p: u for k, p, u in rows if k == "measured"}}
    return {"real": q("WHERE s.dataset='real'"),
            "real_excluding_experiments": q("WHERE s.dataset='real' AND s.experiment IS NULL"),
            "synthetic": q("WHERE s.dataset='synthetic'"),
            "full": q("")}


# ---------------------------------------------------------------- RecurringDiscovery, Draft

def check_recurring(conn, iid: str) -> dict:
    rds = db.rows(conn, "SELECT * FROM recurring_discoveries WHERE initiative_id=?", (iid,))
    cp = next((r for r in rds if r["form"] == "common_path"), None)
    docs = sorted(f"company-docs/{p.name}" for p in config.COMPANY_DOCS_DIR.glob("*.md"))
    reps = [r for r in rds if r["form"] == "repeated_discovery"]
    signs = {fid: [r["recurring_discovery_id"] for r in reps
                   if re.search(sign, r["statement"] or "")]
             for fid, sign in draft_check.MEMORY_SIGNS.items()}
    has_path = bool(cp) and set(docs) <= set(cp["resource_ids"] or [])
    return {"ok": has_path and bool(signs["pf1-storage-env-staging"]),
            "common_path": {"resource_ids": cp["resource_ids"], "session_count": cp["session_count"],
                            "session_share": cp["session_share"], "tokens": cp["tokens"]} if cp else None,
            "company_docs_in_path": has_path,
            "repeated_discoveries": [{"id": r["recurring_discovery_id"], "sessions": r["session_count"],
                                      "share": r["session_share"], "statement": r["statement"]} for r in reps],
            "planted_facts_as_repeated_discovery": signs}


# ---------------------------------------------------------------- Recommendations

def check_recommendations(conn, top: int = 3) -> dict:
    ranked = [r[0] for r in conn.execute("SELECT initiative_id FROM initiatives WHERE session_count > 0 "
                                         "ORDER BY spend_usd DESC, initiative_id LIMIT ?", (top,))]
    out, ok = {}, len(ranked) == top
    for iid in ranked:
        recs = db.rows(conn, "SELECT * FROM recommendations WHERE target_type='initiative' AND target_id=?", (iid,))
        good = [r for r in recs if lib.practice(r["practice_id"]) is not None
                and any(lib.is_infra_ref(x) for x in (r["infra_refs"] or []))]
        bad = [r["recommendation_id"] for r in recs if r not in good]
        out[iid] = {"recommendations": len(recs), "valid": len(good), "invalid": bad,
                    "practices": sorted({r["practice_id"] for r in recs})}
        ok = ok and len(good) >= 2 and not bad
    return {"ok": ok, "top_initiatives": out}


# ---------------------------------------------------------------- endpoints

def check_endpoints(conn) -> dict:
    import dwight.api.main  # noqa: F401  registers every endpoint
    from dwight.api.serving import ENDPOINTS
    sources = {name: ep.source for name, ep in sorted(ENDPOINTS.items())}
    drafts = conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]
    fixture = sorted(n for n, s in sources.items() if s != "store")
    # the drafts endpoints fall back to fixtures while the store has no Drafts at all
    return {"ok": not fixture and drafts > 0, "fixture_endpoints": fixture, "drafts_in_store": drafts,
            "sessions": conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]}


# ---------------------------------------------------------------- synthetic ground truth (informational)

def synthetic_scores(conn) -> dict:
    if not SYNTH_LABELS.exists():
        return {}
    gt = {}
    for line in SYNTH_LABELS.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            gt[r["session_id"]] = r
    rows = conn.execute("SELECT session_id, initiative_id, complexity FROM sessions "
                        "WHERE dataset='synthetic' AND classified_at IS NOT NULL").fetchall()
    rows = [r for r in rows if r[0] in gt]
    n = len(rows)
    right = sum(1 for s, i, _ in rows if gt[s]["initiative_id"] == i)
    cx = sum(1 for s, _, c in rows if gt[s].get("complexity") == c)
    amb = [(s, i) for s, i, _ in rows if gt[s].get("ambiguous")]
    found = _findings(conn, "synthetic")
    det: dict[str, Counter] = {p: Counter() for p in PATTERNS}
    for s, _, _ in rows:
        truth = set(gt[s].get("waste_patterns") or [])
        flagged = set().union(*found.get(s, {}).values()) if found.get(s) else set()
        for p in PATTERNS:
            det[p]["tp" if p in truth and p in flagged else "fn" if p in truth else "fp" if p in flagged else "tn"] += 1
    return {"classified": n, "initiative_accuracy": right / n if n else None,
            "ambiguous_accuracy": (sum(1 for s, i in amb if gt[s]["initiative_id"] == i) / len(amb)) if amb else None,
            "complexity_accuracy": cx / n if n else None,
            "detectors": {p: dict(c) for p, c in det.items()}}


# ---------------------------------------------------------------- stage

def run(conn, args):
    p = argparse.ArgumentParser(prog="acceptance")
    p.add_argument("--loop-min", type=int, default=3, help="identical-call streak that explains a clean run's loop")
    ns = p.parse_args(args)
    iid = yaml.safe_load(draft_check.PLANTED_FACTS.read_text())["initiative_id"]

    rep = {"detectors": check_detectors(conn, ns.loop_min), "waste": waste_totals(conn),
           "recurring": check_recurring(conn, iid), "recommendations": check_recommendations(conn),
           "endpoints": check_endpoints(conn), "synthetic": synthetic_scores(conn)}
    dc = draft_check.check(conn, iid)
    rep["draft"] = {k: v for k, v in dc.items()}
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (config.OUT_DIR / "acceptance.json").write_text(json.dumps(rep, indent=2, default=list))

    lines = []
    d = rep["detectors"]
    pats = ", ".join(f"{k} {v['flagged']}/{v['planted']}" + (f" ({v['not_observable']} not observable)"
                                                             if v["not_observable"] else "")
                     + (f" MISSED {v['missed']}" if v["missed"] else "") for k, v in sorted(d["per_pattern"].items()))
    lines.append(f"detectors [{'ok' if d['ok'] else 'FAIL'}]: {pats}; clean {d['clean']['sessions']} runs, "
                 f"{len(d['clean']['with_measured'])} with a Measured finding "
                 f"({len(d['clean']['unexplained'])} not explained by the harness's own observations); "
                 f"Model Overkill on real: {d['real_model_overkill_findings']}")
    w = rep["waste"]
    lines.append(f"Measured Waste: real layer {_usd(w['real']['measured_waste'], 'measured')} of "
                 f"{_usd(w['real']['spend_measured'], 'measured')} Spend over {w['real']['sessions']} Sessions; "
                 f"full dataset {_usd(w['full']['measured_waste'], 'measured')} of "
                 f"{_usd(w['full']['spend_measured'], 'measured')} Spend over {w['full']['sessions']} Sessions; "
                 f"Estimated Saving (full) {_usd(w['full']['estimated_saving'], 'estimated')}")
    r = rep["recurring"]
    cp = r["common_path"] or {}
    lines.append(f"recurring [{'ok' if r['ok'] else 'FAIL'}]: common path {len(cp.get('resource_ids') or [])} resources "
                 f"(company-docs in path: {r['company_docs_in_path']}), {cp.get('session_count')} Sessions "
                 f"(share {cp.get('session_share') or 0:.2f}); repeated Discoveries "
                 + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in r["planted_facts_as_repeated_discovery"].items()))
    kept = (dc.get("fact_count") or 0) - sum(len(v) for v in (dc.get("missing") or {}).values())
    lines.append(f"draft [{'ok' if dc['ok'] else 'FAIL'}]: {dc.get('tokens')} tokens = {dc.get('share') or 0:.1%} of "
                 f"source, facts kept {kept}/{dc.get('fact_count')}")
    rc = rep["recommendations"]
    lines.append(f"recommend [{'ok' if rc['ok'] else 'FAIL'}]: " + "; ".join(
        f"{k} {v['valid']}/{v['recommendations']} valid" for k, v in rc["top_initiatives"].items()))
    e = rep["endpoints"]
    lines.append(f"endpoints [{'ok' if e['ok'] else 'FAIL'}]: fixture-served {e['fixture_endpoints'] or 'none'}, "
                 f"{e['drafts_in_store']} Drafts, {e['sessions']} Sessions")
    s = rep["synthetic"]
    if s.get("classified"):
        lines.append(f"synthetic (info): classifier {s['initiative_accuracy']:.1%} on {s['classified']} Sessions "
                     f"(ambiguous {s['ambiguous_accuracy'] or 0:.1%}, complexity {s['complexity_accuracy']:.1%}); "
                     "detectors " + ", ".join(f"{p} tp={c.get('tp', 0)} fn={c.get('fn', 0)} fp={c.get('fp', 0)}"
                                              for p, c in s["detectors"].items()))
    for line in lines:
        print(f"  {line}")
    failed = [k for k in ("detectors", "recurring", "recommendations", "endpoints") if not rep[k]["ok"]]
    failed += [] if dc["ok"] else ["draft"]
    summary = f"{'FAILED ' + ','.join(failed) if failed else 'all hard checks ok'}; report {config.OUT_DIR / 'acceptance.json'}"
    if failed:
        raise AcceptanceFailed(summary)
    return summary
