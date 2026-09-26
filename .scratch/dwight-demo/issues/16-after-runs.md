# 16: "After" runs with the Draft loaded

**What to build:** The proof. The same ~10 *storage cost reduction* tasks from 04 run again with the real Draft doc and memory file loaded into the Agent's context. Same model, same harness settings, tagged `dwight.experiment=after`, success/fail recorded. The before/after panel (13) then shows the real Measured drop.

**Blocked by:** 13, 15

**Status:** ready-for-agent

- [ ] Uses the exact model and harness settings recorded in 04
- [ ] Runs are ingested, tagged `dwight.experiment=after`, with per-task success/fail stored
- [ ] The before/after panel shows the real token and Spend drop, with task success side by side
- [ ] If task success dropped, this is flagged and the number isn't used; report back rather than tuning quietly
