# 04: Planted Initiative "before" runs

**What to build:** The ~10 *storage cost reduction* tasks run through the harness against `company-docs/`, with no Draft loaded, tagged `dwight.experiment=before`, with success/fail recorded per task. These Sessions produce the real common path (the 4 docs) and the real repeated Discovery (the planted env-var fact), and they are the baseline for the before/after proof.

**Blocked by:** 02, 03

**Status:** ready-for-agent

- [ ] All ~10 tasks run on the same model and harness settings that 16 will reuse, and those settings are recorded
- [ ] The Sessions are ingested and tagged `dwight.experiment=before`, with per-task success/fail stored
- [ ] Most Trails include the 4 `company-docs/` docs
- [ ] At least 5 Sessions hit the planted fact by trial and error (a failed attempt, then success). If they don't, adjust the tasks and rerun.
