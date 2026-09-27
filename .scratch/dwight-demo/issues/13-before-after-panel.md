# 13: Before/after panel

**What to build:** The before/after panel on Initiative detail. When an Initiative has `dwight.experiment=before|after` Sessions, it shows tokens, Spend and task success side by side, with the drop labelled Measured. The Recommendation carrying the Draft shows that Measured drop next to its Estimated Saving. Built on the fixture before/after pair and computed from the store, so real runs (16) drop in with no code change.

**Blocked by:** 01

**Status:** done

- [x] The API computes per-experiment totals from stored Sessions (tokens, Spend, success rate), not from a hand-entered number
- [x] The panel shows before vs after tokens, Spend, and task success, plus the % drop, labelled Measured
- [x] If task success drops, the panel says the result doesn't count and won't show the drop as a saving
- [x] The panel is hidden when an Initiative has no experiment runs
- [x] The matching Recommendation shows the Measured drop next to its Estimated Saving (13 provides `attach_measured_drops()`; 09 calls it in its `_from_store`, see Comments)

## Comments

**Done (ticket 13).** `GET /api/initiatives/{id}/before-after` now serves `store`. Code: `backend/dwight/api/routes/before_after.py` (rules in its docstring), panel `dashboard/src/panels/initiative/BeforeAfter.tsx`, tests `backend/tests/test_before_after.py`. On the fixture pair (`fx-scr-b01..b06` vs `fx-scr-a01..a06`) it computes 124,548 → 35,460 tokens/Session (71.5% drop), $0.167727 → $0.06402 Spend, 5/6 → 6/6 tasks, success held.

How the numbers are computed (all from `sessions`):
- Experiment Sessions = the Initiative's Sessions (`initiative_id`) with `experiment` before|after. **If any are `dataset='real'`, only real ones are used**, so leftover fixture/synthetic runs never mix into the real proof.
- When both sides have task ids, only task ids present on **both** sides are compared. Every run of those tasks counts (re-runs are not deduplicated).
- tokens = input + output. `token_drop_pct` compares tokens **per Session**. `spend_drop` = (before Spend/Session − after Spend/Session) × after runs, which is plain before − after when run counts match. Both Measured.
- `success_held` = both sides recorded `task_success` and the after success rate ≥ the before rate. Unrecorded success counts as not held.
- `has_runs` is true as soon as either side exists. With only before runs, the panel shows them and says the after runs aren't in yet.

Notes for other tickets:
- **09 (Recommendations):** in your `_from_store`, after building the Recommendation dicts, call `from dwight.api.routes.before_after import attach_measured_drops; attach_measured_drops(conn, items)`. It sets `measured_drop` on every `target_type=initiative` Recommendation with a `draft_id` whose Initiative has before and after runs (both the doc and the memory Recommendation, since the after runs load both Drafts). 13 did **not** touch `recommendations.py` or `Recommendations.tsx`. Suggestion for your panel: when `measured_drop.counts` is false, hide the `spend_drop` Money instead of showing it with a "doesn't count" suffix (the ticket says a failed run must not be shown as a saving).
- **16 (after runs):** tag each run `dwight.experiment=after` with the **same `dwight.experiment.task_id`** as its before run and set `dwight.experiment.task_success`. Runs must be `dwight.dataset=real`. They must also be **classified into `storage-cost-reduction`** (run classify after ingest), because the panel selects by `sessions.initiative_id`: an unclassified or misclassified after run won't show. Tasks without an after run are dropped from both sides automatically. Don't re-run failures until they pass: every run counts.
- **17 (closing numbers):** use `before_after.compute(conn, initiative_id)` or `measured_drop(conn, initiative_id)`; take `token_drop_pct` only when `success_held` / `counts` is true. Initiatives with runs: `SELECT DISTINCT initiative_id FROM sessions WHERE experiment IS NOT NULL`.
- No contract changes needed.
