# 04: Planted Initiative "before" runs

**What to build:** The ~10 *storage cost reduction* tasks run through the harness against `company-docs/`, with no Draft loaded, tagged `dwight.experiment=before`, with success/fail recorded per task. These Sessions produce the real common path (the 4 docs) and the real repeated Discovery (the planted env-var fact), and they are the baseline for the before/after proof.

**Note from 02:** the task prompts refer to "the company storage docs" without naming the four files. If fewer than most Trails include all four docs, name the docs in the prompts and rerun. The four docs total about 22K tokens (the demo script's "18K" should use the measured figure).

**Blocked by:** 02, 03

**Status:** done

- [x] All ~10 tasks run on the same model and harness settings that 16 will reuse, and those settings are recorded
- [x] The Sessions are ingested and tagged `dwight.experiment=before`, with per-task success/fail stored
- [x] Most Trails include the 4 `company-docs/` docs
- [x] At least 5 Sessions hit the planted fact by trial and error (a failed attempt, then success). If they don't, adjust the tasks and rerun.

## Comments


**From 05 (merged):** the detectors need stable `result_hash` / `args_hash` values (identical results must hash identically), and `prefix_hash` + `prefix_tokens` on every Call. Cache Miss flags a Call that has the same prefix hash and model as the previous Call but cache reads below 0.5 × prefix tokens, so check what the provider reports for cached tokens (see 03's Comments).

**Done (ticket 04).** 10 before Sessions, `real-scr-b-t01` … `-t10`, in `data/otlp/real/real-scr-b-*.json` (plus their entries in `data/real_layer_runs.json` and `data/ground-truth/real_layer_labels.yaml`, variant `clean`, planted_pattern `none`).

**For 16: the settings file is `data/real_scr_settings.json`. Reuse it verbatim.** From `backend/`:

```bash
# 04 ran exactly this (before):
python -m dwight.harness storage --settings ../data/real_scr_settings.json --experiment before --prefix real-scr-b --ingest
# 16 runs this (after); only the context files differ:
python -m dwight.harness storage --settings ../data/real_scr_settings.json --experiment after --prefix real-scr-a \
    --context-file <draft.md> --context-file <memory.md> --ingest
```

- The file pins `params`: model `/deployments/506a9a37/deepseek-ai/DeepSeek-V4.1-Flash` (explicit, not the pool round-robin), max_calls 30, repeat 1, all 10 tasks, workers 4. With `--settings`, passing `--model/--max-calls/--repeat/--tasks/--workers` as well is an error.
- It also holds a `fingerprint`: system prompt sha, tool list + schema sha, temperature 0.2, max_tokens 16384, continue_on_length, thinking (unset), base URL, the task prompts + checks sha, the company-docs sha and the Kestrel workspace (blobctl) sha. Loading the file recomputes it and **refuses to run if anything drifted** since 04 ran, so an after run can't compare against different settings. If you really must change something, rerun the whole before batch and rewrite the file (`python -m dwight.harness storage-settings --model <M>`). `test_committed_settings_file_matches_the_current_harness` fails if code drifts away from the committed file.
- Code added (`backend/dwight/harness/settings.py`, tests in `backend/tests/test_harness_settings.py`): `--settings` / `storage-settings`, and two storage-only changes: `max_tokens` 16384 (was 4096) and continue-on-length. The real-layer runs (03) keep 4096 and their old behaviour.

**Why the batch was rerun once (whole batch replaced, nothing cherry-picked):** the first batch (max_tokens 4096) passed 8/10. t05 and t07 failed because the model thought past 4096 output tokens in one Call, and the loop took the cut-off reply (`finish_reason=length`, no tool call) as the final answer, so neither wrote its output file. That's a harness artefact, not a task failure. I raised the storage cap to 16384 and made a cut-off reply get a "continue" prompt instead of ending the Session, then reran all 10. In the final batch no reply hit the cap, so the continue prompt never fired. Prompts and tasks were not changed.

**Results (final batch, all on DeepSeek-V4.1-Flash):**
- **Tasks passed: 10/10** (check DSL). All tagged `dwight.experiment=before`, `dwight.experiment.task_id=<task id>`, `dwight.experiment.task_success=true`, `dwight.dataset=real`.
- **Docs read: 10/10 Sessions read all 4 `company-docs/`** (each one, via `list_docs` then 4 `read_doc` calls in Call 1). The prompts didn't need to name the docs.
- **Trial and error: 8/10 Sessions** (t01–t06, t08, t09, the 8 blobctl tasks) ran blobctl without `STORAGE_ENV`, got `E_NOENV`, then succeeded with `STORAGE_ENV=staging`. The same 8 also hit `E_BADREF` on the `s3://` form at least once and switched to the bare bucket name (some got E_NOENV first, then E_BADREF). t07 and t10 are analysis-only and don't run blobctl.
- **Tokens per Session:** 5–17 Calls (mean 11.8); input 73K–376K (mean 243K, total 2.43M); output 3.9K–12.2K (total 64.6K); Spend $0.027–$0.119 per Session, **$0.81 Measured in total**.

| task | calls | input | output | spend |
|---|---|---|---|---|
| t01 | 13 | 272,649 | 7,613 | $0.0909 |
| t02 | 15 | 327,369 | 5,990 | $0.1054 |
| t03 | 10 | 194,511 | 4,620 | $0.0639 |
| t04 | 17 | 376,340 | 5,346 | $0.1193 |
| t05 | 11 | 220,046 | 8,734 | $0.0765 |
| t06 | 12 | 243,453 | 6,154 | $0.0804 |
| t07 | 6 | 99,119 | 12,183 | $0.0444 |
| t08 | 13 | 277,458 | 5,167 | $0.0894 |
| t09 | 16 | 347,618 | 4,936 | $0.1102 |
| t10 | 5 | 73,289 | 3,860 | $0.0266 |

**Verified from the stored data** (scratch store: ingest → live `classify` → `common_paths` → `repeated_discoveries`):
- classify: 10/10 → `storage-cost-reduction`, 43 Trail entries, 16 Discoveries (2 per blobctl Session).
- **Common path:** the 4 `company-docs/` docs, **10/10 Sessions (share 1.0), 23,892 tokens**, $0.70 Measured read cost.
- **Repeated Discoveries: 2**, each 8/10 Sessions (share 0.8):
  - "Set STORAGE_ENV=staging before running blobctl; otherwise it fails with E_NOENV, and the prod/production values are denied to this credential." ($0.41)
  - "Pass the bucket to blobctl as a bare name (e.g. kst-ml-snapshots), not the s3:// URI form, which is rejected with E_BADREF." ($0.52)

**Notes for 15 / 16:**
- 15: both planted facts come out as separate repeated Discoveries, and both belong in the memory file (see `planted_facts.yaml`). Sciforium still reports no cached tokens, so ignore Cache Miss findings on these Sessions (per 03). The docs' measured size is 23.9K tokens (the store's estimate, using DeepSeek's tokens-per-character), against ~22K by cl100k. The demo line should quote the store's figure.
- 16: after runs must tag the same task ids. The harness does that automatically (Session ids `real-scr-a-t01..t10`). Run classify after ingest so the panel sees them.
- `data/real_layer_stats.json` (03's stats for 07) was not regenerated. The label file now also lists the 10 storage Sessions as `clean`, so a later `python -m dwight.harness stats` will count them.
