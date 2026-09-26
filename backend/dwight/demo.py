"""Demo freeze (ticket 17): snapshot the demo store, reset the app to it, export the numbers.

From backend/ (DWIGHT_DB = the demo store; set DWIGHT_OUT_DIR too if the API uses one):

    python -m dwight.pipeline snapshot [--name demo]          # freeze the store + its Draft files
    python -m dwight.pipeline reset-demo [--name demo]        # restore them (seconds, no model calls)
    python -m dwight.pipeline export-numbers                  # docs/demo-numbers.{md,json}

Order on the final store: rebuild (15) -> `run eval_classifier score --label "..."` LAST
(the strip shows the latest eval_runs row) -> snapshot -> export-numbers.

A snapshot lives in backend/var/snapshots/<name>/ (gitignored; the store is ~150MB):
  store.sqlite      a consistent copy of the store (SQLite backup API, WAL folded in)
  drafts/           the Draft files the store's `drafts` rows describe (written from the rows,
                    which are what the Draft Viewer and its download serve)
  policies/         any Policy files Apply had written under <out dir>/policies/
  manifest.json     sha256s, row counts, the closing numbers and the before/after behind them
The manifest is also written to data/demo-snapshot.json, which is committed, so everyone can
check a local snapshot against the one the slides were made from.

reset-demo copies store.sqlite over DWIGHT_DB (after checking its sha256), rewrites the Draft
files into <out dir>/drafts/, and puts <out dir>/policies/ back to the snapshot's files (so a
Policy applied during a rehearsal disappears). The API opens one connection per request, so it
can keep running; reload the dashboard afterwards.

Dollar figures are formatted the way dashboard/src/components/Money.tsx formats them, and
percentages the way ClosingNumbers.tsx does, so the slides match the strip character for character.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dwight import config, db

SNAPSHOTS_DIR = config.BACKEND_DIR / "var" / "snapshots"
COMMITTED_MANIFEST = config.DATA_DIR / "demo-snapshot.json"
EXPORT_BASE = config.REPO_ROOT / "docs" / "demo-numbers"      # .md + .json
PINNED_DRAFTS_DIR = config.DATA_DIR / "drafts"

TABLES = ("sessions", "calls", "tool_calls", "staging_content", "trail_entries", "discoveries", "initiatives",
          "waste_findings", "recurring_discoveries", "recommendations", "drafts", "policies", "eval_runs")


# ------------------------------------------------------------------ formatting (mirrors the UI)

KIND_LABEL = {"measured": "Measured", "estimated": "Estimated"}


def usd(n: float) -> str:
    """Money.tsx's usd(): >= $1,000 no cents; >= $1 (or 0) two decimals; else 2 significant digits."""
    a = abs(n)
    if a >= 1000:
        return f"-${a:,.0f}" if n < 0 else f"${a:,.0f}"
    if a >= 1 or a == 0:
        return f"-${a:,.2f}" if n < 0 else f"${a:,.2f}"
    return "$" + ("%#.2g" % n)


def money_text(m: dict) -> str:
    """'$0.16 [Measured]', the text <Money> renders (amount + its label chip)."""
    return f"{usd(m['usd'])} [{KIND_LABEL[m['kind']]}{', ' + m['note'] if m.get('note') else ''}]"


def pct(x: float) -> str:
    """ClosingNumbers.tsx's pct(): one decimal."""
    return f"{x:.1f}%"


# ------------------------------------------------------------------ helpers

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(config.REPO_ROOT))
    except ValueError:
        return str(p)


def _connect_ro(path: Path) -> sqlite3.Connection:
    """Read-only connection (never touches the source store's schema or WAL mode)."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def row_counts(conn) -> dict[str, int]:
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES if t in have}


def numbers(conn) -> dict:
    """Everything the strip shows, plus the rows behind it. Read-only; no model calls."""
    from dwight.api.routes import before_after
    from dwight.api.routes import closing_numbers as cn

    body = cn.closing_numbers_body(conn)
    src = cn.token_drop_source(conn)
    ev = cn.latest_eval(conn)
    out: dict = {"closing_numbers": body}
    if src:
        iid, ba = src
        tasks: dict = {}
        for r in before_after._experiment_sessions(conn, iid):   # the same Sessions the panel uses
            tasks.setdefault(r["experiment_task_id"] or r["session_id"], {})[r["experiment"]] = {
                "tokens": r["tokens"], "spend_usd": r["spend_usd"], "task_success": r["task_success"]}
        out["before_after"] = {
            "initiative_id": iid,
            **{k: ba.get(k) for k in ("before", "after", "token_drop_pct", "spend_drop", "success_held")},
            "per_task": tasks,
        }
    if ev:
        details = json.loads(conn.execute("SELECT details_json FROM eval_runs WHERE eval_id=?",
                                          (ev["eval_id"],)).fetchone()[0] or "{}")
        out["eval"] = {"eval_id": ev["eval_id"], "created_at": ev["created_at"], "label": ev["label"],
                       "accuracy": ev["accuracy"], "n_sessions": ev["n_sessions"],
                       **{k: details.get(k) for k in ("accuracy_clear", "n_clear", "accuracy_ambiguous",
                                                       "n_ambiguous", "accuracy_population_weighted", "mode")}}
    out["waste_by_pattern"] = [dict(r) for r in conn.execute(
        "SELECT s.dataset, w.pattern, w.kind, COUNT(*) findings, ROUND(SUM(w.usd), 6) usd "
        "FROM waste_findings w JOIN sessions s USING (session_id) GROUP BY 1, 2, 3 ORDER BY 1, 2, 3")]
    out["sessions_by_dataset"] = {r[0]: {"sessions": r[1], "spend_usd": round(r[2] or 0, 6)} for r in conn.execute(
        "SELECT dataset, COUNT(*), SUM(spend_usd) FROM sessions GROUP BY dataset ORDER BY dataset")}
    return out


def headline(body: dict) -> list[str]:
    """The strip's four statements, as text (the same wording as ClosingNumbers.tsx)."""
    lines = [f"{money_text(body['spend_analysed'])} of Spend analysed",
             f"{money_text(body['measured_waste'])} Measured Waste found"
             f" ({money_text(body['measured_waste_real_layer'])} of it on the real layer)"]
    d = body.get("draft_token_drop_pct")
    lines.append(f"Drafts cut tokens by {pct(d)} [Measured]" if d is not None
                 else "Drafts: no token drop to show (no before/after runs, or task success dropped)")
    a = body.get("classifier_accuracy")
    lines.append(f"classifier {pct(a * 100)} accurate"
                 + (f" on {body['classifier_eval_sessions']:,} Sessions" if body.get("classifier_eval_sessions") else "")
                 if a is not None else "classifier: no eval has run on this store")
    lines.append(f"{money_text(body['estimated_saving'])} Estimated Saving")
    return lines


# ------------------------------------------------------------------ snapshot

def snapshot(name: str = "demo", source: Path | None = None, manifest_out: Path | None | bool = True) -> dict:
    """Freeze `source` (default DWIGHT_DB). manifest_out: True = COMMITTED_MANIFEST, None/False = skip."""
    source = Path(source or config.DB_PATH)
    if not source.exists():
        raise FileNotFoundError(f"no store at {source}")
    snap = SNAPSHOTS_DIR / name
    tmp = snap.with_name(snap.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "drafts").mkdir(parents=True)
    (tmp / "policies").mkdir()

    src_conn = _connect_ro(source)
    dst = sqlite3.connect(tmp / "store.sqlite")
    src_conn.backup(dst)          # consistent copy, including anything still in the WAL
    dst.execute("PRAGMA journal_mode=DELETE")   # a single self-contained file
    dst.close()
    src_conn.close()

    conn = _connect_ro(tmp / "store.sqlite")
    drafts = []
    for r in conn.execute("SELECT draft_id, initiative_id, type, filename, content, tokens FROM drafts ORDER BY draft_id"):
        p = tmp / "drafts" / r["filename"]
        p.write_text(r["content"])
        pinned = PINNED_DRAFTS_DIR / r["filename"]
        drafts.append({"draft_id": r["draft_id"], "initiative_id": r["initiative_id"], "type": r["type"],
                       "filename": r["filename"], "tokens": r["tokens"], "sha256": sha256(p),
                       "matches_committed": pinned.exists() and pinned.read_text() == r["content"]})
    policies = []
    for p in sorted(Path(config.POLICY_OUT_DIR).glob("*.yaml")) if Path(config.POLICY_OUT_DIR).exists() else []:
        shutil.copy2(p, tmp / "policies" / p.name)
        policies.append({"filename": p.name, "sha256": sha256(p)})
    nums = numbers(conn)
    manifest = {
        "snapshot": name,
        "created_at": _now(),
        "source_store": str(source),
        "source_sha256": sha256(source),
        "source_had_wal": source.with_name(source.name + "-wal").exists()
                          and source.with_name(source.name + "-wal").stat().st_size > 0,
        "store_sha256": sha256(tmp / "store.sqlite"),
        "store_bytes": (tmp / "store.sqlite").stat().st_size,
        "row_counts": row_counts(conn),
        "drafts": drafts,
        "policy_files": policies,
        "headline": headline(nums["closing_numbers"]),
        **nums,
    }
    conn.close()
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.rmtree(snap, ignore_errors=True)
    tmp.rename(snap)
    if manifest_out is True:
        manifest_out = COMMITTED_MANIFEST
    if manifest_out:
        Path(manifest_out).write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


# ------------------------------------------------------------------ reset

def reset(name: str = "demo", target: Path | None = None, check_committed: bool = True) -> dict:
    snap = SNAPSHOTS_DIR / name
    mpath = snap / "manifest.json"
    if not mpath.exists():
        raise FileNotFoundError(f"no snapshot at {snap}; run `python -m dwight.pipeline snapshot --name {name}` first")
    manifest = json.loads(mpath.read_text())
    store = snap / "store.sqlite"
    got = sha256(store)
    if got != manifest["store_sha256"]:
        raise RuntimeError(f"{store} sha256 {got[:12]} != manifest {manifest['store_sha256'][:12]}: snapshot damaged")
    warnings = []
    if check_committed and COMMITTED_MANIFEST.exists():
        committed = json.loads(COMMITTED_MANIFEST.read_text())
        if committed.get("snapshot") == name and committed.get("store_sha256") != got:
            warnings.append(f"this snapshot ({got[:12]}) is not the one in {_rel(COMMITTED_MANIFEST)} "
                            f"({committed.get('store_sha256', '')[:12]}); the slides may not match")

    target = Path(target or config.DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".restoring")
    shutil.copyfile(store, tmp)
    for suffix in ("-wal", "-shm"):
        p = target.with_name(target.name + suffix)
        if p.exists():
            p.unlink()
    os.replace(tmp, target)

    draft_dir = Path(config.DRAFT_OUT_DIR)
    draft_dir.mkdir(parents=True, exist_ok=True)
    for d in manifest["drafts"]:
        shutil.copyfile(snap / "drafts" / d["filename"], draft_dir / d["filename"])
    pol_dir = Path(config.POLICY_OUT_DIR)
    removed = []
    if pol_dir.exists():
        keep = {p["filename"] for p in manifest["policy_files"]}
        for p in pol_dir.glob("*.yaml"):
            if p.name not in keep:
                p.unlink()
                removed.append(p.name)
    if manifest["policy_files"]:
        pol_dir.mkdir(parents=True, exist_ok=True)
        for p in manifest["policy_files"]:
            shutil.copyfile(snap / "policies" / p["filename"], pol_dir / p["filename"])

    conn = db.connect(target)
    now = numbers(conn)["closing_numbers"]
    conn.close()
    if now != manifest["closing_numbers"]:
        warnings.append("closing numbers after reset differ from the manifest")
    return {"target": str(target), "store_sha256": got, "drafts": [d["filename"] for d in manifest["drafts"]],
            "policy_files_removed": removed, "headline": headline(now), "warnings": warnings}


# ------------------------------------------------------------------ export for the slides

CAVEATS = [
    "Every dollar figure is labelled Measured (tokens actually used x list price) or Estimated "
    "(projected). The model never produces a dollar figure; code prices tokens from data/prices.yaml.",
    "The token drop is Measured on the real layer: the same 10 storage tasks run before and after loading "
    "the Draft, same model and settings, only the context files changed. It is an average over the 10 tasks "
    "(tokens per Session), not a gain on every task.",
    "It is the second Draft attempt. Draft v1 held task success at only 8/10 (-28.3% tokens), so it did not "
    "count; its runs are archived in data/archive/draft-v1-after-runs/. The Drafter was fixed (keep the table "
    "columns that rules depend on; the Draft replaces the source docs) and the whole after batch was run once "
    "with Draft v2. No re-runs or tuning after that.",
    "Real-layer Spend is priced as uncached input: Sciforium reports no cached-token counts, so no cache "
    "discount can be Measured there.",
    "Cache Miss and Model Overkill appear in the synthetic layer only: Cache Miss is not observable on a "
    "provider that reports no cache reads, and the real layer runs Flash models only, so there is no overkill.",
    "The synthetic layer is generated (ticket 07); its Spend is a fictional company's month. The real layer "
    "is the harness runs (tickets 03, 04, 16).",
]


def _task_caveat(ba: dict) -> str | None:
    worse = [(t, v) for t, v in sorted(ba.get("per_task", {}).items())
             if "before" in v and "after" in v and v["after"]["tokens"] > v["before"]["tokens"]]
    if not worse:
        return None
    parts = [f"{t} ({(v['after']['tokens'] - v['before']['tokens']) / v['before']['tokens'] * 100:+.1f}% tokens, "
             f"{usd(v['before']['spend_usd'])} -> {usd(v['after']['spend_usd'])} Measured)" for t, v in worse]
    return "Not every task got cheaper: " + "; ".join(parts) + " cost more after the Draft."


def export(conn, base: Path | None = None) -> tuple[Path, Path]:
    base = Path(base or EXPORT_BASE)
    nums = numbers(conn)
    body = nums["closing_numbers"]
    snap_sha = None
    if COMMITTED_MANIFEST.exists():
        snap_sha = json.loads(COMMITTED_MANIFEST.read_text()).get("store_sha256")
    data = {"generated_at": _now(), "store": str(config.DB_PATH), "snapshot_store_sha256": snap_sha,
            "headline": headline(body), **nums}
    jpath, mpath = base.with_suffix(".json"), base.with_suffix(".md")
    jpath.write_text(json.dumps(data, indent=2) + "\n")

    L = ["# Demo numbers", "",
         f"Generated by `python -m dwight.pipeline export-numbers` from the demo store "
         f"(snapshot sha256 `{(snap_sha or 'n/a')[:12]}`, see `data/demo-snapshot.json`). "
         "These are exactly the numbers the Overview's closing strip shows (`GET /api/closing-numbers`). "
         "Do not edit by hand; regenerate.", "",
         "## The closing line", ""]
    L += [f"- {h}" for h in headline(body)]
    L += ["", "## Where each number comes from", "",
          "| Number | Value | Label | Source |", "|---|---|---|---|",
          f"| Spend analysed | {usd(body['spend_analysed']['usd'])} | Measured | every Session in the store |",
          f"| Measured Waste | {usd(body['measured_waste']['usd'])} | Measured | detector findings, full dataset |",
          f"| Measured Waste, real layer | {usd(body['measured_waste_real_layer']['usd'])} | Measured | "
          "detector findings on the harness runs only (dataset=real) |",
          f"| Estimated Saving | {usd(body['estimated_saving']['usd'])} | Estimated | Estimated findings, full dataset |"]
    d, a = body.get("draft_token_drop_pct"), body.get("classifier_accuracy")
    L.append(f"| Draft token drop | {pct(d) if d is not None else 'not shown (task success dropped or no runs)'} | "
             "Measured | before/after runs, tokens per Session |")
    ev = nums.get("eval")
    L.append(f"| Classifier accuracy | {pct(a * 100) if a is not None else 'no eval'} | (not a $ figure) | "
             + (f"eval `{ev['label']}`, {ev['n_sessions']:,} Sessions, {ev['created_at']} |" if ev else "- |"))
    ba = nums.get("before_after")
    if ba and ba.get("before") and ba.get("after"):
        b, af = ba["before"], ba["after"]
        L += ["", f"## Before/after (`{ba['initiative_id']}`, Measured)", "",
              "| | before | after |", "|---|---|---|",
              f"| Sessions | {b['session_count']} | {af['session_count']} |",
              f"| tasks passed | {b['tasks_passed']}/{b['tasks_total']} | {af['tasks_passed']}/{af['tasks_total']} |",
              f"| tokens per Session | {b['avg_tokens']:,.0f} | {af['avg_tokens']:,.0f} |",
              f"| Spend | {money_text(b['spend'])} | {money_text(af['spend'])} |", "",
              f"Token drop {pct(ba['token_drop_pct'])}, Spend drop {money_text(ba['spend_drop'])}, "
              f"task success held: {'yes' if ba['success_held'] else 'NO (the strip shows no drop)'}.", "",
              "| task | tokens before -> after | change | Spend before -> after (Measured) | success |",
              "|---|---|---|---|---|"]
        for t, v in sorted(ba["per_task"].items()):
            if "before" in v and "after" in v:
                bt, at = v["before"], v["after"]
                ch = (at["tokens"] - bt["tokens"]) / bt["tokens"] * 100 if bt["tokens"] else 0
                ok = lambda x: "pass" if x else ("fail" if x is not None else "-")  # noqa: E731
                L.append(f"| {t} | {bt['tokens']:,} -> {at['tokens']:,} | {ch:+.1f}% | "
                         f"{usd(bt['spend_usd'])} -> {usd(at['spend_usd'])} | {ok(bt['task_success'])} -> "
                         f"{ok(at['task_success'])} |")
    if ev and ev.get("accuracy_clear") is not None:
        L += ["", "## Classifier eval", "",
              f"`{ev['label']}`: {pct(ev['accuracy'] * 100)} on {ev['n_sessions']:,} Sessions "
              f"(clear {ev['accuracy_clear']} on {ev['n_clear']}, ambiguous {ev['accuracy_ambiguous']} on "
              f"{ev['n_ambiguous']}, population-weighted {ev['accuracy_population_weighted']})."]
    L += ["", "## Waste by pattern", "", "| dataset | Waste Pattern | label | findings | $ |", "|---|---|---|---|---|"]
    for r in nums["waste_by_pattern"]:
        L.append(f"| {r['dataset']} | {r['pattern']} | {KIND_LABEL[r['kind']]} | {r['findings']:,} | {usd(r['usd'])} |")
    L += ["", "## Caveats (say these if asked)", ""]
    caveats = list(CAVEATS)
    if ba:
        tc = _task_caveat(ba)
        if tc:
            caveats.insert(2, tc)
    L += [f"{i}. {c}" for i, c in enumerate(caveats, 1)]
    mpath.write_text("\n".join(L) + "\n")
    return mpath, jpath


# ------------------------------------------------------------------ CLI

def main(cmd: str, argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog=f"python -m dwight.pipeline {cmd}")
    if cmd == "snapshot":
        p.add_argument("--name", default="demo")
        p.add_argument("--from", dest="source", help="store to freeze (default: DWIGHT_DB)")
        p.add_argument("--no-manifest", action="store_true", help=f"don't write {_rel(COMMITTED_MANIFEST)}")
        ns = p.parse_args(argv)
        m = snapshot(ns.name, Path(ns.source) if ns.source else None,
                     not ns.no_manifest)
        print(f"[snapshot] {SNAPSHOTS_DIR / ns.name}: store {m['store_bytes'] / 1e6:.1f} MB "
              f"sha256 {m['store_sha256'][:12]}, {m['row_counts'].get('sessions', 0):,} Sessions, "
              f"{len(m['drafts'])} Draft files, {len(m['policy_files'])} Policy files")
        for h in m["headline"]:
            print(f"  {h}")
        return 0
    if cmd == "reset-demo":
        p.add_argument("--name", default="demo")
        p.add_argument("--to", dest="target", help="store to overwrite (default: DWIGHT_DB)")
        ns = p.parse_args(argv)
        r = reset(ns.name, Path(ns.target) if ns.target else None)
        print(f"[reset-demo] {r['target']} <- snapshot {ns.name} (sha256 {r['store_sha256'][:12]}); "
              f"Drafts -> {config.DRAFT_OUT_DIR}; Policy files removed: {r['policy_files_removed'] or 'none'}")
        for h in r["headline"]:
            print(f"  {h}")
        for w in r["warnings"]:
            print(f"  WARNING: {w}")
        return 0
    if cmd == "export-numbers":
        p.add_argument("--out", default=str(EXPORT_BASE), help="path without extension (writes .md and .json)")
        ns = p.parse_args(argv)
        conn = db.connect()
        md, js = export(conn, Path(ns.out))
        conn.close()
        print(f"[export-numbers] {md} + {js.name}")
        return 0
    raise SystemExit(f"unknown demo command {cmd}")
