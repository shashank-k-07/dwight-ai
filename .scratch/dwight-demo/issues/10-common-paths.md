# 10: Common paths → Recurring Discovery panel

**What to build:** The common-path half of cross-session analysis (build-spec §4.6.1) and the Recurring Discovery panel on Initiative detail. For each Initiative, code computes the share of Sessions whose Trail contains each resource. Resources in ≥ 60% of Sessions form the common path, with Measured `spend_usd`. The panel renders both RecurringDiscovery forms: "32 of 40 Sessions read these 4 docs" and "found separately in 14 Sessions". The second form uses fixture data until 11 lands.

**Blocked by:** 01

**Status:** done

- [x] Runs only on stored Trails, never on prompt content (ADR 0008)
- [x] The share threshold is configurable, default 60%. Single resources only (itemsets are cut).
- [x] `spend_usd` is the sum, over Sessions, of the common-path resources' tokens × the input rate each Call actually paid (the same rule as Redundant Read). Labelled Measured.
- [x] Writes RecurringDiscovery records of form `common_path`, with session count, share and evidence Session IDs
- [x] The panel shows both forms with counts and labelled $. The repeated-Discovery $ is labelled as a conservative upper bound.
- [x] Unit test on fixture Trails

## Comments

**Done (ticket 10).** The stage is `backend/dwight/pipeline/stages/common_paths.py` (`run common_paths [--threshold 0.6] [--min-sessions 3] [--initiative ID ...]`). The endpoint `/api/initiatives/{id}/recurring-discoveries` now serves **store** data for both forms. Tests are in `backend/tests/test_common_paths.py`. On fixtures, the storage Initiative's common path is the 4 `company-docs/` docs: 7 of 8 Sessions, 19,700 tokens, $0.161389 Measured. That matches `derived.json`, worked out by hand.

The rules, so other stages match:
- **Population.** The stage analyses an Initiative's Sessions minus `experiment='after'` runs: `common_paths.analysed_session_ids(conn, iid)`. The API's `initiative_session_count` uses the same function.
- **Common path.** Every resource whose Trail share is ≥ threshold. It is one row per Initiative, id `rd-cp-<initiative_id>`, with `resource_ids` sorted. `evidence`/`session_count`/`session_share` = the Sessions whose Trail contains **every** common-path resource, so "7 of 8 Sessions read these 4 docs" is literally true. `tokens` = the sum over resources of mean tokens per read, which is one read of the whole path. The API returns each resource's mean tokens per read in `resources[].tokens`.
- **`spend_usd` (Measured)** = the sum over **all** analysed Sessions of every Trail read of a common-path resource. That includes partial readers like fx-scr-08, and re-reads. Each read is requested by Call `call_seq` and billed on every later Call: at the uncached rate on the first Call that carries it, then at the cache-read rate on each later Call whose `cache_read_tokens > 0`, else uncached again. Every Call is priced at its own model. A read requested by the last Call costs 0. The helper is `common_paths.read_cost(calls, call_seq, tokens)`.
- **Idempotent.** A full run deletes every `form='common_path'` row, including those of Initiatives that no longer have Sessions, and rewrites them. `--initiative` scopes the delete. It never touches `repeated_discovery` rows. Initiatives with fewer than 3 analysed Sessions get no common path.

For later tickets:
- **05 (Redundant Read):** I read "cache-read rate after that if caching is on" per Call, as `cache_read_tokens > 0` on that Call. Please use the same rule, or tell me yours, so both "Measured" figures agree. You can import `read_cost` if it fits.
- **11:** The route serves your rows as they are. `statement`, `session_count`, `session_share` and `evidence` come straight from the row. `cost` = `money(spend_usd, "measured", "conservative upper bound")`. Your `session_share` denominator should be `analysed_session_ids()` (non-`after` Sessions), so it agrees with `initiative_session_count`. Items are ordered common_path first, then repeated Discoveries by `session_count` desc. Delete only `form='repeated_discovery'` rows.
- **12 (Drafter/pricing):** the common-path row's `resource_ids` are the Draft's source docs. `tokens` is the "common-path tokens" in the Saving formula and the base for the ≤ 25% target. Its id is `rd-cp-<initiative_id>`, not the fixture's `rd-scr-path`, so after `run common_paths` the fixture Recommendation's `recurring_discovery_id` is dangling until 09/12 regenerate Recommendations. Link to `common_paths.common_path_id(iid)`.
- **15:** Run `common_paths` after classify has written Trails. The real-layer `after` runs are excluded automatically. If the real storage Initiative mixes in Sessions that aren't storage tasks, the share may drop below 60%. `--threshold` is the knob.
