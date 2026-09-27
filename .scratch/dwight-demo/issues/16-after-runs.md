# 16: "After" runs with the Draft loaded

**What to build:** The proof. The same ~10 *storage cost reduction* tasks from 04 run again with the real Draft doc and memory file loaded into the Agent's context. Same model, same harness settings, tagged `dwight.experiment=after`, success/fail recorded. The before/after panel (13) then shows the real Measured drop.

**Blocked by:** 13, 15

**Status:** done (Draft v2: 10/10 passed, -75.4% tokens per Session, success held; the v1 attempt, 8/10, is archived and recorded in Comments)

- [x] Uses the exact model and harness settings recorded in 04
- [x] Runs are ingested, tagged `dwight.experiment=after`, with per-task success/fail stored
- [x] The before/after panel shows the real token and Spend drop, with task success side by side
- [x] If task success dropped, this is flagged and the number isn't used; report back rather than tuning quietly

## Comments


**From 13 (merged):** the Before/After panel computes everything from stored Sessions. Each after run needs `dwight.experiment=after`, the same `dwight.experiment.task_id` as its before run, `dwight.experiment.task_success`, and `dwight.dataset=real`. Run classify after ingest so the runs land in `storage-cost-reduction`: the panel selects by `sessions.initiative_id`, so an unclassified run won't appear. Once any real experiment Session exists, only real ones are used. Every run counts, so don't re-run failures until they pass.

**From 03 (merged):** run the after batch with the exact settings 04 recorded (see 04's Comments), changing only the context files: `python -m dwight.harness storage --experiment after --prefix real-scr-a --context-file <draft> --context-file <memory> --ingest`. The harness keeps before and after settings identical apart from the context files, and a test checks this. Use the same pinned model as 04; the pool round-robins otherwise.

**From 12 (merged):** the Draft files land in `out/drafts/storage-cost-reduction.md` (doc) and `out/drafts/storage-cost-reduction.memory.md`, under `DWIGHT_OUT_DIR` or else the gitignored `out/`. `draft.draft_files(iid)` returns both paths, and `GET /api/drafts/{id}/download` serves the same text. Load both as context files, doc first. **Copy 15's files somewhere stable and commit them** before running the after batch, because re-running `draft` regenerates them with different wording.

**Attempt 1, with Draft v1 (ARCHIVED; superseded by the Draft v2 attempt below). Result: 8/10 tasks passed, −28.3% tokens per Session, `success_held` false.** Task success dropped from 10/10 to 8/10, so the token drop does not count as a saving. Nothing was re-run or tuned. Archived: the OTLP was moved to `data/archive/draft-v1-after-runs/` (out of `data/otlp/`, so no ingest path picks it up), along with the v1 Draft as `draft-v1.md` / `draft-v1.memory.md`. The v1 entries in `data/real_layer_runs.json` and `data/ground-truth/real_layer_labels.yaml` now sit under `archived.draft-v1-after` (kept, not deleted). The user then approved: fix the Drafter, regenerate v2, and re-run the whole after batch once.

**Command** (from `backend/`, 04's settings file used as-is; fingerprint check passed with no drift):

```bash
python -m dwight.harness storage --settings ../data/real_scr_settings.json --experiment after --prefix real-scr-a \
    --context-file ../data/drafts/storage-cost-reduction.md --context-file ../data/drafts/storage-cost-reduction.memory.md --ingest
```

One batch, 10 Sessions, 0 harness errors, no reply hit the length cap. Outputs (now archived): `data/archive/draft-v1-after-runs/real-scr-a-t01..t10.json`, plus new entries in `data/real_layer_runs.json` and `data/ground-truth/real_layer_labels.yaml`. Every run is tagged `dwight.experiment=after`, with the same `dwight.experiment.task_id` as its before run, `task_success`, and `dwight.dataset=real`.

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

---

**Attempt 2, with Draft v2 (the result that counts). 10/10 tasks passed, −75.4% tokens per Session, `success_held` true.**

**Drafter fix** (`backend/dwight/pipeline/stages/_drafter.py`, tests in `backend/tests/test_draft.py`, mocked):
- **Columns that rules depend on.** `required_columns()` parses every markdown table in the source docs. It marks a column as required when prose in another section or doc refers to it. A multi-word header matches by its words in order (with abbreviations expanded, so "Avg object" matches "average object size"); a one-word header only matches when quoted. The table's own caption doesn't count. Each section prompt lists that doc's required columns, with the sentence that depends on each one. `repair_tables()` then puts back any required column the model still dropped from a table it kept, using the source's values for the matched rows, or `(see source)` where no row matches. On the real docs this finds Avg object, Policy compliant, Writer service and others; "Objects" is not required, correctly. Nothing is hard-coded to a bucket.
- **Header.** The Draft now says it *replaces* the source docs for this work and to open a source only if a needed value is missing. The system prompt says the same. The "open the linked source" default is gone.
- **`draft_must_keep`** (`data/ground-truth/planted_facts.yaml`) adds the section 6 override inputs that v1 lost: `38 KB`, `850 KB`, `480 MB`, `Policy compliant` and `claims-portal`, now 28 facts in all. This is the Drafter's acceptance check; no Agent sees it.
- **Draft v2** was regenerated live from a real-only store: 50 Sessions (40 real-layer + 10 before; v1's after runs excluded), through ingest → classify → detect → common_paths → repeated_discoveries → recommend → draft. `draft_check` passed first try: **4,889 tokens = 22.0% of 22,186 source tokens, 28/28 facts**. On this pass the model kept the required columns itself, so v2's inventory has Avg object (38 KB for app-logs) and Policy compliant. The memory file carries both planted facts again (wording regenerated). Committed to `data/drafts/`.

**After batch v2:** the same command, 04's settings (fingerprint unchanged), prefix `real-scr-a`, v2 as the context files. Run **once**: 10 Sessions, 0 harness errors, no re-runs, no tuning. Outputs: `data/otlp/real/real-scr-a-t01..t10.json` + manifest/label entries.

**Real-only store** (60 files in `data/otlp/real/`, live classify, 20/20 `real-scr-*` → `storage-cost-reduction`). `before_after.compute` and `GET /api/initiatives/storage-cost-reduction/before-after` (source `store`) agree:

| | before | after v1 (archived) | **after v2** |
|---|---|---|---|
| tasks passed | 10/10 | 8/10 | **10/10** |
| tokens per Session | 249,645.5 | 178,896.8 | **61,471.1** |
| token_drop_pct | | 28.3 | **75.4** |
| Spend (Measured) | $0.807079 | $0.581891 | **$0.238169** |
| spend_drop (Measured) | | $0.225188 | **$0.568910** |
| Calls | 118 | 79 | **67** |
| Sessions that read all 4 docs | 10 | 9 (+1 read 2) | **1** (t07) |
| success_held | | false | **true** |

**Per task, v2** (E_NOENV / E_BADREF = blobctl results containing that error):

| task | calls b→a | tokens b→a | drop | Spend b→a | success | E_NOENV / E_BADREF | read_doc |
|---|---|---|---|---|---|---|---|
| t01 | 13→8 | 280,262→60,343 | 78.5% | $0.0909→$0.0232 | ✓→✓ | 0 / 0 | 0 |
| t02 | 15→10 | 333,359→78,326 | 76.5% | $0.1054→$0.0293 | ✓→✓ | 1* / 0 | 0 |
| t03 | 10→6 | 199,131→44,053 | 77.9% | $0.0639→$0.0166 | ✓→✓ | 0 / 0 | 0 |
| t04 | 17→8 | 381,686→60,059 | 84.3% | $0.1193→$0.0219 | ✓→✓ | 0 / 0 | 0 |
| t05 | 11→6 | 228,780→51,293 | 77.6% | $0.0765→$0.0233 | ✓→✓ | 0 / 0 | 0 |
| t06 | 12→6 | 249,607→45,112 | 81.9% | $0.0804→$0.0178 | ✓→✓ | 0 / 0 | 0 |
| t07 | 6→6 | 111,302→150,753 | −35.4% | $0.0444→$0.0611 | ✓→✓ | n/a | 4 |
| t08 | 13→7 | 282,625→51,459 | 81.8% | $0.0894→$0.0185 | ✓→✓ | 1* / 0 | 0 |
| t09 | 16→8 | 352,554→57,904 | 83.6% | $0.1102→$0.0197 | ✓→✓ | 0 / 0 | 0 |
| t10 | 5→2 | 77,149→15,409 | 80.0% | $0.0266→$0.0067 | ✓→✓ | n/a | 0 |

\* A bare `bin/blobctl status` while exploring (t02, t08). Every plan/apply in every v2 run used `STORAGE_ENV=staging` and the bare bucket name on the first try. There was no trial and error on either planted fact: before, all 8 blobctl Sessions hit both errors.

**For 17 (closing numbers):** quote **75.4% fewer tokens per Session (249,646 → 61,471), $0.807 → $0.238 Measured Spend over 10 Sessions ($0.569 saved), task success 10/10 → 10/10**. Take them from `before_after.compute(conn, "storage-cost-reduction")` on a store built from `data/otlp/real/`.

**Caveats:**
1. **This is a second attempt.** v1 failed, the failure was diagnosed, and the Drafter was changed before v2 (approved by the user). The fix is general code, and the new must-keep facts were chosen with v1's failure in view. v1's result stays on the record above and in `data/archive/draft-v1-after-runs/`.
2. v1 → v2 changed three things at once: the column rule, the "replaces the sources" header, and the regenerated memory wording. The runs can't separate their effects. The header is the likely reason 9/10 v2 Sessions read no source docs (v1: 9/10 read all 4), and that is where most of the drop comes from. The kept columns are the likely reason t04 and t07 now price app-logs correctly.
3. t07 (analysis only) still read all 4 docs and cost 35% more than before. The drop is an average over the 10 tasks, not a gain on every task.

No contract changes. Tests: 184 passed, no live calls.
