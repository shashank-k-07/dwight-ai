# 04: Planted Initiative "before" runs

**What to build:** The ~10 *storage cost reduction* tasks run through the harness against `company-docs/`, with no Draft loaded, tagged `dwight.experiment=before`, with success/fail recorded per task. These Sessions produce the real common path (the 4 docs) and the real repeated Discovery (the planted env-var fact), and they are the baseline for the before/after proof.

**Note from 02:** the task prompts refer to "the company storage docs" without naming the four files. If fewer than most Trails include all four docs, name the docs in the prompts and rerun. The four docs total about 22K tokens (the demo script's "18K" should use the measured figure).

**Blocked by:** 02, 03

**Status:** ready-for-agent

- [ ] All ~10 tasks run on the same model and harness settings that 16 will reuse, and those settings are recorded
- [ ] The Sessions are ingested and tagged `dwight.experiment=before`, with per-task success/fail stored
- [ ] Most Trails include the 4 `company-docs/` docs
- [ ] At least 5 Sessions hit the planted fact by trial and error (a failed attempt, then success). If they don't, adjust the tasks and rerun.

## Comments


**From 05 (merged):** the detectors need stable `result_hash` / `args_hash` values (identical results must hash identically), and `prefix_hash` + `prefix_tokens` on every Call. Cache Miss flags a Call that has the same prefix hash and model as the previous Call but cache reads below 0.5 × prefix tokens, so check what the provider reports for cached tokens (see 03's Comments).
