# 17: Closing numbers strip + demo snapshot

**What to build:** The closing beat of the demo (build-spec §1 step 7): a strip showing "$X of Spend analysed, $Y Measured Waste found, Drafts cut tokens by Z%, classifier W% accurate". The store is also frozen into a snapshot the demo can be reset to, so the live run and the slides use the same numbers.

**Blocked by:** 08, 14, 16

**Status:** ready-for-agent

- [ ] The strip reads every number from the store and labels each $ as Measured or Estimated
- [ ] The Z% comes from 16's Measured before/after runs, and W% from 08's eval
- [ ] One command resets the app to the frozen demo snapshot
- [ ] The numbers are exported to a short file for the slides, matching what the app shows
- [ ] The demo flow in build-spec §1 steps 1–7 is clicked through with no fixture data, errors or unlabelled $

## Comments


**From 13 (merged):** take the token drop from `dwight.api.routes.before_after.compute(conn, initiative_id)` or `measured_drop(...)`, and use `token_drop_pct` only when `success_held` / `counts` is true. On the fixture pair it is 71.5% (124,548 → 35,460 tokens per Session), with tasks going from 5/6 to 6/6.

**From 14 (merged):** the only dollar figures on the Policy screen are Recommendation savings, shown through `<Money>`. Cut-list item 2 ("show the rendered config only") is no longer needed, because Apply works end to end.
