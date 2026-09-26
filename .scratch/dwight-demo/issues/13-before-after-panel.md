# 13: Before/after panel

**What to build:** The before/after panel on Initiative detail. When an Initiative has `dwight.experiment=before|after` Sessions, it shows tokens, Spend and task success side by side, with the drop labelled Measured. The Recommendation carrying the Draft shows that Measured drop next to its Estimated Saving. Built on the fixture before/after pair and computed from the store, so real runs (16) drop in with no code change.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] The API computes per-experiment totals from stored Sessions (tokens, Spend, success rate), not from a hand-entered number
- [ ] The panel shows before vs after tokens, Spend, and task success, plus the % drop, labelled Measured
- [ ] If task success drops, the panel says the result doesn't count and won't show the drop as a saving
- [ ] The panel is hidden when an Initiative has no experiment runs
- [ ] The matching Recommendation shows the Measured drop next to its Estimated Saving
