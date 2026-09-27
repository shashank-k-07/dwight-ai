"""Acceptance check: draft_check (ticket 12, used by 15). Not part of run-all.

Checks the stored initiative doc Draft of an Initiative against build-spec §4.6
acceptance:
  * tokens <= 25% of the source tokens (both the common path's stored tokens and the
    source docs counted with the Drafter's counter, chars/4), and
  * every doc-resident planted fact in data/ground-truth/planted_facts.yaml
    `draft_must_keep` is still present (case-sensitive substring).
It also reports which planted trial-and-error facts the memory file carries (informational).

This is the only Dwight code outside the eval (08) that reads data/ground-truth/, as
planted_facts.yaml's header allows. The draft stage itself never reads it.

  run draft_check [--initiative storage-cost-reduction] [--max-share 0.25]

Exits non-zero (stage status "error") when a check fails.
"""
from __future__ import annotations

import argparse
import re

import yaml

from dwight import config, db
from dwight.pipeline.stages import _drafter as d

ORDER = 75
TICKET = "12"
DESCRIPTION = "Acceptance check: initiative doc Draft <= 25% of source tokens and keeps every doc-resident planted fact"
IN_DEFAULT_RUN = False

PLANTED_FACTS = config.GROUND_TRUTH_DIR / "planted_facts.yaml"
# How to recognise each planted trial-and-error fact in a memory file (informational only).
MEMORY_SIGNS = {
    "pf1-storage-env-staging": r"STORAGE_ENV=staging",
    "pf2-bare-bucket-names": r"(?i)bare bucket|not (an? )?s3://|without (the )?s3://|no s3://|strip.*s3://",
}


class DraftCheckFailed(RuntimeError):
    pass


def missing_facts(content: str, must_keep: dict[str, list[str]]) -> dict[str, list[str]]:
    """{source doc: [facts not in content]} for every doc with a missing fact."""
    out = {}
    for doc, facts in must_keep.items():
        gone = [f for f in facts if f not in content]
        if gone:
            out[doc] = gone
    return out


def check(conn, initiative_id: str, max_share: float = 0.25) -> dict:
    gt = yaml.safe_load(PLANTED_FACTS.read_text())
    doc = next(iter(db.rows(conn, "SELECT * FROM drafts WHERE initiative_id=? AND type='initiative_doc'",
                            (initiative_id,))), None)
    mem = next(iter(db.rows(conn, "SELECT * FROM drafts WHERE initiative_id=? AND type='memory'",
                            (initiative_id,))), None)
    res: dict = {"initiative_id": initiative_id, "has_doc": doc is not None, "has_memory": mem is not None}
    if doc:
        docs, _ = d.fetch_source_docs(doc["source_resource_ids"])
        counted = sum(x.tokens for x in docs)
        base = min(b for b in (doc["source_tokens"], counted) if b) if (doc["source_tokens"] or counted) else 0
        res.update(tokens=doc["tokens"], source_tokens=doc["source_tokens"], counted_source_tokens=counted,
                   share=doc["tokens"] / base if base else None,
                   missing=missing_facts(doc["content"], gt.get("draft_must_keep") or {}),
                   fact_count=sum(len(v) for v in (gt.get("draft_must_keep") or {}).values()))
        res["ok"] = bool(base) and res["share"] <= max_share and not res["missing"]
    else:
        res["ok"] = False
    if mem:
        res["memory_facts"] = {fid: bool(re.search(sign, mem["content"])) for fid, sign in MEMORY_SIGNS.items()}
    return res


def run(conn, args):
    p = argparse.ArgumentParser(prog="draft_check")
    p.add_argument("--initiative", default=None, help="default: the planted Initiative in planted_facts.yaml")
    p.add_argument("--max-share", type=float, default=0.25)
    ns = p.parse_args(args)
    iid = ns.initiative or yaml.safe_load(PLANTED_FACTS.read_text())["initiative_id"]
    r = check(conn, iid, ns.max_share)
    if not r["has_doc"]:
        raise DraftCheckFailed(f"{iid}: no initiative doc Draft in the store (run the draft stage)")
    kept = r["fact_count"] - sum(len(v) for v in r["missing"].values())
    msg = (f"{iid}: initiative doc {r['tokens']} tokens = {r['share']:.1%} of source "
           f"(stored {r['source_tokens']}, counted {r['counted_source_tokens']}); "
           f"planted doc facts kept {kept}/{r['fact_count']}")
    if r["missing"]:
        msg += f"; MISSING {r['missing']}"
    if "memory_facts" in r:
        msg += "; memory file: " + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in r["memory_facts"].items())
    if not r["ok"]:
        raise DraftCheckFailed(msg)
    return msg
