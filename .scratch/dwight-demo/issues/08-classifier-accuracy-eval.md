# 08: Classifier accuracy eval

**What to build:** Score the classifier against the synthetic ground truth and show the accuracy number in the app, so it can go on stage (build-spec §5). This is also the loop for improving the classifier prompt.

**Blocked by:** 06, 07

**Status:** done

- [x] An eval command reports the share of Sessions placed in the right Initiative, plus a per-Initiative confusion summary
- [x] The number is stored and served by the API for the closing-numbers strip
- [x] At least one round of prompt improvement is run, with the before and after accuracy recorded

## Comments


**From 06 (merged):** the classifier is callable as functions in `backend/dwight/classifier/` (`model.py`: one `glm.chat_json` call per Session; `run.py`: thread pool). Classifying deletes staging, so to re-score after a prompt change, re-ingest the OTLP files and rerun the stage. Label eval runs with `classifier.model.PROMPT_VERSION`. The model sees only each Initiative's id, name and description from `org.yaml` plus the Session's team and Business Function. It always picks one of the 15 known Initiatives, so there's no "none" answer (the tracer Session lands in `k8s-upgrade`).

**From 03 (merged):** real-layer labels (planted Waste Pattern per Session) are in `data/ground-truth/real_layer_labels.yaml`. The 40 tomli Sessions don't match any org.yaml Initiative well, so expect them to be classified loosely; score Initiative accuracy on the synthetic layer.

**Done (ticket 08).** Code: `backend/dwight/eval/__init__.py` (ground truth loader, stratified sample, sample-only re-ingest, scoring + confusion summary, `eval_runs` writer) and the stage `backend/dwight/pipeline/stages/eval_classifier.py` (`IN_DEFAULT_RUN = False`). Prompt: `backend/dwight/classifier/model.py` is now `classify-v3` (commit 05becdb). Tests: `backend/tests/test_eval.py` (glm mocked). Only this package and 15's acceptance stage read `data/ground-truth/`. Ground truth picks the sample and scores it, and it never reaches the model.

Commands (from `backend/`, with `DWIGHT_DB` pointing at the store):

```bash
# score whatever is classified in the store (no model calls) -> one eval_runs row
python -m dwight.pipeline run eval_classifier score --label "classify-v3 thinking=off full store"
# prompt loop: re-ingest a fixed stratified sample from data/otlp/synthetic/ (only those payloads), classify it, score it
python -m dwight.pipeline run eval_classifier sample [--per-initiative 20 --ambiguous 6 --seed 8 --workers 8 --thinking off]
python -m dwight.pipeline run eval_classifier sample --no-classify    # re-score the sample as it stands
```

`sample` restores the sample's staged content before classifying, so you can rerun it after every prompt change. Use a scratch store for it, because it re-ingests and re-classifies those Sessions. `score` counts every classified Session that has a ground-truth row, which in practice means synthetic only. The row has `accuracy`, `n_sessions`, `created_at`, `label` and a `details_json` holding `prompt_version`, clear/ambiguous accuracy, a population-weighted accuracy (the sample over-weights ambiguous prompts: 30% vs 15% in the dataset), complexity accuracy, per-Initiative recall/precision/confused-with and the top confusions.

**Prompt round (same sample: 300 Sessions, 20 per Initiative of which 6 ambiguous, seed 8, reasoning off, the classify default after 15):**

| prompt | accuracy | clear (210) | ambiguous (90) | population-weighted | complexity |
|---|---|---|---|---|---|
| `classify-v2` | 0.920 (276/300) | 0.995 | 0.744 | 0.957 | 0.780 |
| `classify-v3` | **0.950** (285/300) | 1.000 | 0.833 | 0.975 | 0.787 |

A first round with reasoning **on** (180 Sessions, 12 per Initiative with 4 ambiguous, seed 8) went from 0.906 to 0.978. Those rows are kept separate and aren't mixed into the comparison above.

What v2 got wrong: every miss except one was an ambiguous prompt that borrowed another Initiative's vocabulary, and v2 matched on the keyword. Examples: Integrations Sessions going to invoicing-v2 or k8s-upgrade, Routing going to invoicing-v2 or storage, Fleet Ops triage going to dock-scheduling, and month-end-close and vendor-contract-review swapping with each other. v3 changes the prompt text only. It gives an evidence order: first the resources actually opened and the deliverable, then the stated request, then the Team and Business Function context, where an Initiative outside the Team's area needs clear evidence. It also warns against matching on keywords or incidental tools. And it shows each Initiative's owning Business Function in the candidate list (`id: name [Engineering] — description`). It does not show `primary_teams`, usual resources or any sample text. Output schema: unchanged. Cost: about 250 more input tokens per call, still 1 call per Session.

The 15 misses left are all ambiguous prompts whose actual work belongs to the Initiative v3 picked. Examples: a Platform Session labelled incident-postmortems that only scans Helm charts for deprecated APIs, three Mobile Sessions labelled offline-sync that profile the route solver, and month-end-close/vendor-contract-review lookups of contract renewals. Fixing these would mean fitting to label noise, so I stopped at v3.

Notes for later tickets:
- **15:** `rebuild` already runs `eval_classifier score --label "rebuild: full store"` after run-all, so the latest `eval_runs` row is the full-store number. To label a manual run, use the score command above. The prompt version is always in `details_json.prompt_version`. Scoring makes no model calls.
- **17:** the closing-numbers strip reads the latest `eval_runs` row by `created_at` (15's route). Run `score` on the frozen store **last**. A later `sample` run in the same store would replace the on-stage number with a sample number. For the slide: "Initiative accuracy X% on N synthetic Sessions (clear-cut prompts about 100%, deliberately ambiguous prompts about 83%)". Take the ambiguous split from `details_json`.
- No contract changes were needed. `closing_numbers.py` is 15's; I didn't edit it.

