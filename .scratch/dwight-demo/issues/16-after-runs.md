# 16: "After" runs with the Draft loaded

**What to build:** The proof. The same ~10 *storage cost reduction* tasks from 04 run again with the real Draft doc and memory file loaded into the Agent's context. Same model, same harness settings, tagged `dwight.experiment=after`, success/fail recorded. The before/after panel (13) then shows the real Measured drop.

**Blocked by:** 13, 15

**Status:** done (task success dropped 10/10 → 8/10, so the drop does NOT count; see Comments)

- [x] Uses the exact model and harness settings recorded in 04
- [x] Runs are ingested, tagged `dwight.experiment=after`, with per-task success/fail stored
- [x] The before/after panel shows the real token and Spend drop, with task success side by side
- [x] If task success dropped, this is flagged and the number isn't used; report back rather than tuning quietly

## Comments


**From 13 (merged):** the Before/After panel computes everything from stored Sessions. Each after run needs `dwight.experiment=after`, the same `dwight.experiment.task_id` as its before run, `dwight.experiment.task_success`, and `dwight.dataset=real`. Run classify after ingest so the runs land in `storage-cost-reduction`: the panel selects by `sessions.initiative_id`, so an unclassified run won't appear. Once any real experiment Session exists, only real ones are used. Every run counts, so don't re-run failures until they pass.

**From 03 (merged):** run the after batch with the exact settings 04 recorded (see 04's Comments), changing only the context files: `python -m dwight.harness storage --experiment after --prefix real-scr-a --context-file <draft> --context-file <memory> --ingest`. The harness keeps before and after settings identical apart from the context files, and a test checks this. Use the same pinned model as 04; the pool round-robins otherwise.

**From 12 (merged):** the Draft files land in `out/drafts/storage-cost-reduction.md` (doc) and `out/drafts/storage-cost-reduction.memory.md`, under `DWIGHT_OUT_DIR` or else the gitignored `out/`. `draft.draft_files(iid)` returns both paths, and `GET /api/drafts/{id}/download` serves the same text. Load both as context files, doc first. **Copy 15's files somewhere stable and commit them** before running the after batch, because re-running `draft` regenerates them with different wording.

**Done (ticket 16). Task success dropped from 10/10 to 8/10, so `success_held` is false and the token drop does not count as a saving.** Nothing was re-run or tuned.

**Command** (from `backend/`, 04's settings file used as-is; fingerprint check passed with no drift):

```bash
python -m dwight.harness storage --settings ../data/real_scr_settings.json --experiment after --prefix real-scr-a \
    --context-file ../data/drafts/storage-cost-reduction.md --context-file ../data/drafts/storage-cost-reduction.memory.md --ingest
```

One batch, 10 Sessions, 0 harness errors, no reply hit the length cap. Outputs: `data/otlp/real/real-scr-a-t01..t10.json`, plus new entries in `data/real_layer_runs.json` and `data/ground-truth/real_layer_labels.yaml`. Every run is tagged `dwight.experiment=after`, with the same `dwight.experiment.task_id` as its before run, `task_success`, and `dwight.dataset=real`.

**Verified on a real-only store** (fresh store, ingest all 60 files in `data/otlp/real/`, live `classify --dataset real`): 20/20 `real-scr-*` Sessions → `storage-cost-reduction`. `before_after.compute(conn, "storage-cost-reduction")` and `GET /api/initiatives/storage-cost-reduction/before-after` (source `store`) agree:

| | before | after |
|---|---|---|
| Sessions | 10 | 10 |
| tasks passed | **10/10** | **8/10** |
| tokens per Session | 249,645.5 | 178,896.8 |
| total tokens | 2,496,455 | 1,788,968 |
| Spend (Measured) | $0.807079 | $0.581891 |
| Calls | 118 | 79 |

`token_drop_pct` 28.3, `spend_drop` $0.225188 Measured, **`success_held` false**. For 17: **do not quote 28.3% or $0.23 as a saving.** Measured over only the 8 tasks that passed on both sides, the drop is 25.0% (2,003,467 → 1,501,960 tokens; $0.6434 → $0.4884). That's context only: the panel's rule excludes it, and so should the demo.

**Per task** (E_NOENV / E_BADREF = blobctl results containing that error):

| task | calls b→a | tokens b→a | drop | success b→a | after: E_NOENV / E_BADREF | after: docs read |
|---|---|---|---|---|---|---|
| t01 | 13→8 | 280,262→193,041 | 31.1% | ✓→✓ | 0 / 0 | 4 |
| t02 | 15→9 | 333,359→222,588 | 33.2% | ✓→✓ | 1* / 0 | 4 |
| t03 | 10→8 | 199,131→191,593 | 3.8% | ✓→✓ | 0 / 0 | 4 |
| t04 | 17→9 | 381,686→137,091 | 64.1% | ✓→**✗** | 0 / 0 | 2 |
| t05 | 11→8 | 228,780→197,852 | 13.5% | ✓→✓ | 0 / 0 | 4 |
| t06 | 12→9 | 249,607→222,434 | 10.9% | ✓→✓ | 0 / 0 | 4 |
| t07 | 6→7 | 111,302→149,917 | −34.7% | ✓→**✗** | n/a (no blobctl) | 4 |
| t08 | 13→8 | 282,625→192,460 | 31.9% | ✓→✓ | 0 / 0 | 4 |
| t09 | 16→8 | 352,554→190,256 | 46.0% | ✓→✓ | 0 / 0 | 4 |
| t10 | 5→5 | 77,149→91,736 | −18.9% | ✓→✓ | n/a (no blobctl) | 4 |

\* t02 ran a bare `blobctl status` once before its plan. Every plan/apply in every after run used `STORAGE_ENV=staging` and the bare bucket name on the first try.

**What worked:** the memory file removed the trial and error completely. Before: 8/8 blobctl Sessions hit E_NOENV and E_BADREF (15 E_BADREFs in total). After: 0 E_BADREF, and no E_NOENV on any plan/apply. Most of the drop comes from that: Calls went 118 → 79.

**What didn't:**
1. **The two failures are the same policy mistake, and the Draft probably contributed.** Both t04 and t07 priced `kst-app-logs-prod` with a Warm (STANDARD_IA) 30–90d band: after = $4,310 and saving = $2,820, where the correct answer is $6,095 / $1,035. The bucket's average object is 38 KB, so §6.1 (small objects < 128 KB) keeps it Hot until expiry. **The Draft's §7 inventory table dropped the source's "Avg object" column** (along with Writer service, Objects and Policy compliant), so the Draft states the §6.1 rule but not the value that triggers it. Both runs did also read `storage-cost-dashboard` itself, so the model had the value and missed it. t07 even wrote the correct 31,054.20 first, then recomputed and overwrote it with 35,941.54, which also contains other schedule errors (e.g. pod-images Warm from 30d). So it's model variance too, not only the Draft. Suggested fix for the drafter (12/15), **not applied here**: keep the per-bucket columns that §6 overrides depend on (Avg object, Writer service, Policy compliant), and add `38 KB` / the app-logs small-objects outcome to `draft_must_keep`. Any fix means regenerating the Draft and re-running the whole after batch.
2. **The Draft did not replace the common path.** 9/10 after runs still read all 4 `company-docs/` (t04 read 2). The system prompt points to `list_docs`/`read_doc`, the task prompts say "Using the company storage docs", and the Draft itself says "For anything not covered here, open the linked source". The Draft also adds about 4.7K tokens to every Call's system prompt. That's why the analysis-only tasks got more expensive (t07 −34.7%, t10 −18.9%) and the doc-heavy plan tasks saved little (t03 3.8%).

No contract changes. Tests: 176 passed, no live calls.
