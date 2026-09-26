# 07: Synthetic company dataset → Spend by Business Function

**What to build:** The scale layer. A generator produces 3–5K Sessions over 30 days for the fictional company, as OTLP JSON through the normal ingest. The prompt content is GLM-written so the classifier has real text to read. Overview then shows Spend by Business Function, stacked by Team, over the full dataset.

**Blocked by:** 01, 02

**Status:** done

**Decision (2026-09-26, user):** the synthetic layer is the **only** source of Model Overkill (03 plants no Model Overkill runs). Give it a meaningful rate: low-complexity Sessions on the flagship tier (`glm-5.1`) in some Teams. The synthetic layer keeps the fictional company's GLM tiers (`glm-5.1` / `glm-4.7` / `glm-4.5-air`). Any GLM calls the generator makes to write prompt content go through `dwight.glm` (Sciforium pool), which is separate from the model names recorded in the synthetic telemetry.

- [x] Uses the org from 02: ~200 Members, 4–5 Business Functions, ~12 Teams, ~15 Initiatives, Engineering at ~70% of Sessions, and at least one non-engineering Business Function
- [x] Session shapes (call counts, token distributions, Waste Pattern rates) come from a parameter file. It is calibrated from 03's real-layer stats if present, otherwise from sensible defaults that can be updated later.
- [x] Each synthetic Initiative has a set of "usual" docs most of its Sessions read, and a few repeated Discoveries at varied strengths
- [x] Each Session's true Initiative is written to a separate ground-truth file the classifier never reads
- [x] The dataset is generated and ingested through the normal OTLP path, not written straight into the store
- [x] Overview shows Spend by Business Function, stacked by Team

## Comments


**Coordinator note (2026-09-26):** Sciforium reports no cached tokens, so Cache Miss can't be observed on the real layer. Like Model Overkill, **Cache Miss appears only in synthetic data**. Your synthetic GLM-tier models (`reports_cache_usage` defaults to true) must report realistic `cache_read_tokens` on clean Calls, and near-zero on planted misses.

**Done (ticket 07).** Code: `backend/dwight/synth/` (params, content, generate, calibrate, CLI). Tests: `backend/tests/test_synth.py` (no live model calls).

Regenerate, from `backend/`:

```bash
.venv/bin/python -m dwight.synth build --ingest   # content (cached, 0 calls) + OTLP + ground truth + ingest into DWIGHT_DB
.venv/bin/python -m dwight.synth calibrate        # re-fit shapes from data/otlp/real/ -> data/synthetic/calibration.yaml, then build again
.venv/bin/python -m dwight.synth content --refresh  # only to rewrite the GLM content (60 jobs, ~17 min)
```

Generation is deterministic from `seed` (same seed = same bytes) and takes a few seconds. `build --ingest` uses `dwight.ingest.otlp.ingest_file`, the same function the `ingest` stage uses. `python -m dwight.pipeline run ingest` with no args also picks up `data/otlp/synthetic/`.

Files:
- `data/synthetic/params.yaml`: every knob (sessions=4000, 30 days from 2026-08-27, model mix per Team, complexity mix, shapes, Waste Pattern rates, usual-doc read probabilities, content job sizes). `calibration.yaml` overlays it. It is calibrated from the committed real layer (40 Sessions): the med Session length and the per-Call output/command-result tokens. Low/high lengths and agent prompt prefixes keep their defaults, because the harness's ~0.7K system prompt isn't kestrel-devagent's. Pattern rates stay hand-set, because the real layer's rates are planted (`--rates-from` exists if you want to use them).
- `data/synthetic/content_library.json` (1.4MB, committed): GLM-written tasks (40 per Initiative, tagged low/med/high and ambiguous), usual-doc excerpts, extra docs, work steps, failing steps, Discovery scripts and one-offs. It was built with 60 jobs (67 attempts, 7 retried on truncated JSON), 4 concurrent, in 997s. storage-cost-reduction uses the real `company-docs/` text and the real `blobctl` error strings.
- `data/otlp/synthetic/day-*.jsonl`: ~197MB, **gitignored**. Regenerate it.
- `data/ground-truth/synthetic_sessions.jsonl` (committed): one row per Session with the true `initiative_id`, `complexity`, `ambiguous`, `waste_patterns`, `reread_call_seqs` / `loop_call_seqs` / `cache_miss_call_seqs`, `discoveries[{statement, kind: repeated|one_off, call_seq}]`, `usual_resources_read` and `spend_usd`. `synthetic_summary.json` has the counts.
- **`data/synthetic/` is label-bearing** (keyed by Initiative). Like `data/ground-truth/`, no pipeline stage may read it.

Dataset (seed 7): 4000 Sessions, 199 Members, 12 Teams, 15 Initiatives. Engineering has 73% of Sessions (2927). Spend is $579 Measured in total ($513 of it Engineering); GLM list prices are cheap, so raise `shapes`/`sessions` if you want a bigger number. Models: glm-5.1 2148, glm-4.7 1397, glm-4.5-air 455. Planted patterns: Redundant Read 453, Cache Miss 847, Runaway Loop 166, Model Overkill 608 (low complexity on glm-5.1). 2258 Sessions are clean. There are 611 ambiguous prompts and 118 one-off Discoveries.

Checks run on the full dataset:
- `detect.find_waste` with ground-truth complexity agreed with the planted labels on all 4000 Sessions (0 false positives, 0 false negatives).
- `classifier.trail.build_trail` yields exactly the org.yaml resource ids.
- A 24-Session `classify` sample (on a copy of the store) placed 23/24 in the right Initiative. The miss was an ambiguous prompt. All 6 truly-low Sessions came back `low`.

Notes for later tickets:
- **06 / 15 (classify):** that sample took **478s for 24 Sessions at 4 workers**, about 80s per Session per worker. The full 4000 would take roughly 22h at 4 workers. Plan for more workers, a lighter tier, or classifying a sample (e.g. `--limit`) plus the real layer.
- **06 (Trail):** read tools are `read_doc {"doc_id": "<company doc id>"}`, `perch.get_page {"page_id": "perch:SPACE/slug"}` and `code.read_file {"path": "repo:kestrel/<repo>/<path>"}`. Ids are pre-namespaced so `trail.py` keeps them as is. Some work tools (e.g. `incidents.get {"id": ...}`) are read-like and may add odd Trail entries; they don't reach 60%.
- **05 (detect):** Cache Miss Sessions keep the same `prompt_prefix_hash` (`<agent>/sys-v13-header`, with a timestamp header in the system prompt) and read 0 cache tokens on Call 1 and ~85% of later Calls. Clean Calls read the previous Call's input rounded down to 128. Loops repeat one tool per Call, 5–9 times. Re-reads are never on consecutive Calls.
- **08 (eval):** score against `data/ground-truth/synthetic_sessions.jsonl` (`initiative_id`, plus `complexity` if useful). Filter to Sessions that were actually classified. `ambiguous=true` rows are the hard cases.
- **10 (common paths):** every Initiative's usual docs are read by 62–77% of its Sessions (varied), and extra docs by well under 60%. storage-cost-reduction's synthetic Sessions (~370) will dominate its common path over the real layer's ~40. All 4 `company-docs/` are at 0.70 or above (min 0.696), so it still comes out as the 4 docs.
- **11 (repeated Discoveries):** each org.yaml repeated Discovery is planted at roughly its `strength` (17–41% of the Initiative's Sessions), worded consistently in the Agent's note after the fix. One-offs are about 1–3 Sessions each, but some small Initiatives may still reach the ≥5-Session threshold for a one-off. `vendor-contract-review` and `incident-postmortems` have no repeated Discovery (negatives).
- **15:** the synthetic dataset has `dwight.dataset=synthetic`, so "Measured Waste on the real layer" can filter on `sessions.dataset='real'`.
- `backend/dwight/api/routes/overview.py` needed no change: Spend by Business Function stacked by Team was already computed from the store over all Sessions. The panel now also shows a subtotal row per Business Function with its share of Sessions.
