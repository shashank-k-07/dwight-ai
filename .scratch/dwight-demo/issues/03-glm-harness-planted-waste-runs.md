# 03: GLM agent harness with planted Waste Pattern runs

**What to build:** The real layer. A small tool-using Agent harness on GLM, with OTel on, sends its telemetry to Dwight's ingest. It runs 30–50 real tasks against a real open-source repo, including planted variants that produce each Waste Pattern and clean runs as negatives. After this, real Sessions and Calls sit in the store and show on Overview.

**Note from 02:** the harness's file-read tool must not be able to open `data/company/workspace/bin/blobctl`, because reading its source would skip the trial and error that produces the planted Discovery. Read the `## Comments` section of ticket 02 before starting.

**Blocked by:** 01

**Status:** done

**Decision (2026-09-26, user):** the real layer runs on Sciforium's two cheap Flash models (DeepSeek-V4.1-Flash, and GLM 5.3 Flash once its model string is in `DWIGHT_GLM_MODEL_POOL`). There is no flagship model, so **don't plant Model Overkill in the real runs**, and never record a real run under a fake flagship model name. Model Overkill shows up in the synthetic layer (07) only. Pick one model per Session with `glm.model_for()` and pass it on every Call, so each Session is one model and `gen_ai.request.model` records the model actually used (the deployment path is fine: `pricing.normalise_model` reduces it to `deepseek-v4.1-flash` / `glm-5.3-flash`, both priced in `data/prices.yaml` at tier `light`).

- [x] The harness has read-type tools (file read, doc fetch, search) and write/run tools, and emits OTel GenAI spans with Business Function/Team/Member resource attributes
- [x] The harness can load extra context files into the Agent's starting context (needed by 16) and can tag a run with `dwight.experiment=before|after`
- [x] Planted variants run: Redundant Read (re-reads the same files each turn), Cache Miss (volatile timestamp at the top of the prompt), Runaway Loop (retry with no exit on a failing test). **No Model Overkill variant** (see the decision note)
- [x] Clean runs are included
- [x] Which Session carries which planted pattern is recorded in a label file the detectors never read
- [x] All runs are ingested, and their Spend shows on Overview
- [x] Summary stats of the real layer (call counts, token distributions, pattern rates) are written out for ticket 07 to calibrate against

## Comments

**Done (ticket 03).** The harness is `backend/dwight/harness/` (read its `__init__.py` first). The CLI is `python -m dwight.harness --help`, run from `backend/`. Tests are in `backend/tests/test_harness.py`; they use a scripted fake client, so they make no live calls.

**Real layer: 40 Sessions**, in `data/otlp/real/real-001..040.json`:

| planted_pattern | Sessions | ids |
|---|---|---|
| none (clean) | 14 | real-001..014 |
| redundant_read | 9 | real-015..023 |
| cache_miss | 9 | real-024..032 |
| runaway_loop | 8 | real-033..040 |

- The tasks run against **tomli 2.4.1** (MIT, https://github.com/hukkin/tomli, pinned commit `c5f44690c68c5ed29534faa8f9df18882113728c` in `workspace.OSS_REPO`). It is cloned on demand into `backend/var/oss/tomli` (gitignored). Each Session gets a fresh copy under `$TMPDIR/dwight-harness/workspaces/<session_id>` (override with `DWIGHT_HARNESS_DIR`). The copy sits outside the repo so pytest doesn't pick up `backend/pytest.ini`.
- All 40 Sessions ran on `/deployments/506a9a37/deepseek-ai/DeepSeek-V4.1-Flash`, the only model in the pool. That is the string recorded in `gen_ai.request.model`, which normalises to `deepseek-v4.1-flash`. There are 290 Calls in total, the Spend is **$0.93 Measured**, and all of it is attributed to Engineering across 7 Teams.
- Other files:
  - Labels: `data/ground-truth/real_layer_labels.yaml`. It holds `planted_pattern` plus what the harness itself observed (duplicate tool results, identical consecutive tool-call streaks, volatile prefix, cache reporting). Only 15 and the evals may read it.
  - Run manifest: `data/real_layer_runs.json`. It holds the model and harness settings per Session (temperature 0.2, max_calls, max_tokens 4096, tools, system prompt sha, context files) and the outcome. It has no labels.
  - **Stats for 07: `data/real_layer_stats.json`**. It holds calls/Session, input/output tokens per Call and per Session, prefix tokens, tool mix, result tokens and Spend, overall and per variant, plus the pattern rates. Regenerate it with `python -m dwight.harness stats`.
- Ingest: `python -m dwight.pipeline run ingest ../data/otlp/real` (or pass `--ingest` to the harness).

**How the plants work** (see the `tasks.py` docstring):
- **Redundant Read:** a house-rule system prompt, plus a harness reminder after each turn that lists the opened files. Every Session re-read `_parser.py` or other files; `duplicate_tool_results` is 1 to 12 per Session. real-018 was re-run once because the first attempt finished in 2 Calls without re-reading.
- **Cache Miss:** `[kestrel-devagent session header] generated <timestamp> request <id>` sits at the top of the system prompt and is regenerated on every Call. `dwight.prompt.prefix_hash` hashes the *stable* instructions + tool schema without that header, so it is constant within a Session, as in the fixtures. `gen_ai.system_instructions` is re-emitted on every Call that changes it.
- **Runaway Loop:** a planted test fails with a CI-looking infrastructure error (ECONNRESET, a held lock, ENOSPC). The Agent gets only a `run_tests` tool, a "flaky, keep re-running" prompt and a naive retry wrapper that re-prompts whenever it stops while the last run failed. The harness cap of 10 Calls is the only exit. Every one of the 8 Sessions has **≥ 3 consecutive Calls with an identical run_tests call and an identical result** (streaks of 3 to 4). The model then refuses in text, and the wrapper re-prompts it.
- There is no Model Overkill variant, and no fake model names.

**Notes for other tickets:**
- **05 / 15, Cache Miss (important):** Sciforium reports **no cache usage at all**. `usage.prompt_tokens_details` is `null`, and there is no `prompt_cache_hit_tokens`. I tried `stream_options.include_usage` and several `extra_body` flags; none report it. The harness leaves the cache-read attribute out when the API doesn't report it, so the store has `cache_read_tokens=0` on all 290 Calls. Nothing is invented; the harness records it if the provider starts reporting it. Consequence: with 05's rule, **every multi-Call real Session, clean ones included, looks like a Cache Miss**. The telemetry cannot tell clean runs from the planted ones. 15 needs a decision here. One option is to skip Cache Miss on models that never report cache reads, and mark the 9 planted Cache Miss Sessions "not observable on this provider". The latency does halve on repeated prefixes, so the provider probably caches but doesn't bill or report it.
- **05 / 15, Redundant Read overlap:** Runaway Loop Sessions also contain duplicate result hashes, so expect redundant_read findings on them too. real-031 (cache_miss) also re-read a file twice by itself. The label file's `observed` block shows these cases.
- **05:** tool results are deterministic. The workspace path becomes `.`, `in 0.12s` becomes `in <duration>`, and pytest runs with `-p no:cacheprovider`. So identical results hash identically.
- **04 / 16:** run with `python -m dwight.harness storage --experiment before --prefix real-scr-b --ingest`. For 16, add `--experiment after --prefix real-scr-a --context-file <draft.md> --context-file <memory.md>`. The context files are appended to the system prompt under "# Context files". They are part of the prefix hash, so after runs get a different prefix hash from before runs.
  - The settings are identical between the two runs; only the context files differ (`test_storage_specs_share_settings_between_before_and_after`). `task_id` is always set, and `task_success` comes from `harness/checks.py`, which implements the check DSL in `storage_tasks.yaml`. The reference solution for t01 passes, and the wrong 14317.70 answer fails.
  - Session ids are `<prefix>-t01` … `-t10`, and output goes to `data/otlp/real/`.
  - Smoke runs of t01 and t04 (scratch output, not committed) both **passed**. Each read all 4 docs in one Call, then hit E_NOENV, used `STORAGE_ENV=staging`, hit E_BADREF, and switched to the bare bucket name. That is exactly the planted trial and error, in 12 to 14 Calls and about 250 to 300K input tokens.
  - In t01 the Agent's first command was `cat bin/blobctl`, and it was refused. The real stub lives outside the workspace (`bin/blobctl` is a shim). `read_file`/`search` refuse it, and `run_command` refuses any command that names blobctl other than as the program being run (`.blobctl/` state stays readable). On macOS, commands also run under `sandbox-exec`: no network, and writes only inside the workspace.
  - Tools: `list_docs`/`read_doc {doc_id}` (read-type, matching the fixture shape), `read_file {path}`, `list_files`, `search`, `write_file`, `run_command {cmd}`. Repo tasks also have `run_tests {path}`.
- **06:** read-type tools are `read_file`, `list_files`, `search`, `list_docs` and `read_doc`. `read_doc` args are `{"doc_id": "storage-tiering-policy"}`; map them to `company-docs/<id>.md`. Assistant output messages include the model's `reasoning` parts. The real OSS Sessions are tomli maintenance work and don't match any org.yaml Initiative well, so expect them to be spread across Engineering Initiatives or classified loosely.
- **07:** the model thinks by default, so output tokens are high. p50 is 218 per Call, and a few Calls hit the 4096 max_tokens cap. The p50 input per Call is 4.4K tokens and p90 is 18.8K.
- `dwight.prompt.prefix_tokens` and `dwight.tool.result_tokens` are estimates: characters × the Session's measured tokens-per-character from Call 0's `prompt_tokens`. We have no tokenizer for DeepSeek. The input and output tokens come straight from the API.
- `tool_choice="required"` is broken on Sciforium (raw `<｜DSML｜ invoke>` markup comes back in `content`), so don't use it. Bare model names are rejected; the `/deployments/...` path is required.
