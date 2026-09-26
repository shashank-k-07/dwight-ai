"""Stage: eval_classifier (ticket 08). Not in run-all.

Scores the classifier's Initiative choice against data/ground-truth/synthetic_sessions.jsonl
and writes an eval_runs row (the closing-numbers strip serves the latest one).
This is the only stage allowed to read data/ground-truth/, and it never shows it to the model.

  run eval_classifier score                     score every classified Session that has ground truth
                                                (no model calls; use on 15's final store)
  run eval_classifier score --label "final"     custom label (default: "<PROMPT_VERSION> store")
  run eval_classifier sample                    re-ingest a fixed stratified sample from data/otlp/synthetic/,
                                                classify it with the current prompt, score it
  run eval_classifier sample --per-initiative 20 --ambiguous 6 --seed 8 --workers 8 --thinking off
  run eval_classifier sample --no-classify      re-score the sample as it stands (no model calls)

`sample` costs one model call per sampled Session (15 x per-initiative, 300 by default).
In `score` mode the classify configuration is whatever produced the store; say it in --label.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from dwight import eval as ev

ORDER = 25
TICKET = "08"
DESCRIPTION = "Classifier accuracy vs synthetic ground truth -> eval_runs (score | sample)"
IN_DEFAULT_RUN = False


def run(conn, args):
    from dwight.classifier import classify_sessions, pending_sessions
    from dwight.classifier import run as runner
    from dwight.classifier.model import PROMPT_VERSION

    p = argparse.ArgumentParser(prog="eval_classifier")
    sub = p.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("score")
    s.add_argument("--label")
    sm = sub.add_parser("sample")
    sm.add_argument("--per-initiative", type=int, default=ev.DEFAULT_PER_INITIATIVE)
    sm.add_argument("--ambiguous", type=int, default=ev.DEFAULT_AMBIGUOUS_PER_INITIATIVE)
    sm.add_argument("--seed", type=int, default=ev.DEFAULT_SEED)
    sm.add_argument("--workers", type=int, default=8)
    sm.add_argument("--tier")
    sm.add_argument("--thinking", choices=["on", "off"],
                    default="on" if runner.DEFAULT_THINKING else "off",
                    help="model reasoning for classify (default: the classify stage's default, off)")
    sm.add_argument("--no-classify", action="store_true")
    sm.add_argument("--label")
    ns = p.parse_args(args)

    truth = ev.load_truth()
    if ns.mode == "score":
        preds, cx = ev.classified_predictions(conn)
        result = ev.score(preds, truth, cx)
        if not result["n_sessions"]:
            return "no classified Sessions with ground truth in this store; nothing recorded"
        label = ns.label or f"{PROMPT_VERSION} store"
        eval_id = ev.record(conn, result, label=label, extra={"mode": "score", "prompt_version": PROMPT_VERSION})
        print(ev.report(result, label))
        return f"{eval_id}: accuracy {result['accuracy']:.3f} over {result['n_sessions']} Sessions"

    ids = ev.stratified_sample(truth, per_initiative=ns.per_initiative,
                               ambiguous_per_initiative=ns.ambiguous, seed=ns.seed)
    extra = {"mode": "sample", "prompt_version": PROMPT_VERSION, "seed": ns.seed, "thinking": ns.thinking,
             "sample_per_initiative": ns.per_initiative, "sample_ambiguous_per_initiative": ns.ambiguous}
    since = None
    if not ns.no_classify:
        since = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        n = ev.reingest(conn, ids)
        stats = classify_sessions(conn, pending_sessions(conn, session_ids=ids), workers=ns.workers, tier=ns.tier,
                                  thinking=ns.thinking == "on", progress_every=50)
        extra.update(reingested=n, classify=stats.line())
        print(stats.line())
    preds, cx = ev.classified_predictions(conn, ids, since=since)
    result = ev.score(preds, truth, cx)
    if not result["n_sessions"]:
        return "no sampled Sessions were classified; nothing recorded"
    label = ns.label or f"{PROMPT_VERSION} thinking={ns.thinking} sample n={len(ids)} seed={ns.seed}"
    eval_id = ev.record(conn, result, label=label, extra={**extra, "sample_size": len(ids)})
    print(ev.report(result, label))
    return f"{eval_id}: accuracy {result['accuracy']:.3f} over {result['n_sessions']}/{len(ids)} sampled Sessions"
