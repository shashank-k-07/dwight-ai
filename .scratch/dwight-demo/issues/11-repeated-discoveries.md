# 11: Repeated Discoveries

**What to build:** The repeated-Discovery half of cross-session analysis (build-spec §4.6.2). The Discoveries in each Initiative are clustered by meaning (embeddings, then a GLM pass to merge and name each cluster). A cluster reached separately in ≥ 5 Sessions (or ≥ 20%) becomes a RecurringDiscovery of form `repeated_discovery`, with Measured `spend_usd`. Its records use the shape the Recurring Discovery panel (10) already renders from fixtures.

**Blocked by:** 01

**Status:** done

**Decision (2026-09-26):** embeddings aren't available (Sciforium `/v1/embeddings` returns 404). Group Discoveries with a model pass only: `glm.chat_json` over each Initiative's Discoveries, batched if large, returning clusters of Discovery ids plus one merged statement per cluster. Don't call `glm.embed()`.

- [x] Runs only on stored Discoveries, never on prompt content (ADR 0008)
- [x] Clusters are merged and named by GLM into one actionable statement each
- [x] Thresholds are configurable (default ≥ 5 Sessions or ≥ 20%)
- [x] `spend_usd` is the spend in each Session from its start up to the Call where the Discovery was established (`call_seq`), summed across Sessions. Labelled Measured.
- [x] On fixture data, the planted env-var fact comes out as one repeated Discovery, and one-off Discoveries don't
- [x] The API output matches the frozen contract, so the panel needs no changes

## Comments

**Done (ticket 11).** Code: `backend/dwight/pipeline/stages/repeated_discoveries.py` (loading, thresholds, Measured spend, writes) and `backend/dwight/pipeline/stages/_discovery_clusters.py` (the model grouping pass). Tests: `backend/tests/test_repeated_discoveries.py` (the model is faked, so no live calls).

Things downstream tickets should know:
- **Rows** have exactly the fixture shape: `form='repeated_discovery'`, `statement`, `session_count`, `session_share` (rounded to 4 places), `spend_usd` (Measured, a conservative upper bound), `evidence` = sorted Session ids, `resource_ids`/`tokens` NULL. The stage deletes and rewrites only `repeated_discovery` rows, per Initiative. On a full run it also drops rows for Initiatives that no longer exist. If one Initiative's model call fails, that Initiative keeps its old rows and the stage reports `error`, naming it.
- **IDs are `rd-<initiative_id>-rep01`, `-rep02`, ...** ranked by Session count, then spend. They are not `rd-scr-env`. After this stage runs on a seeded store, the fixture Recommendation that points at `rd-scr-env` dangles until 09 re-runs. **09/12: look repeated Discoveries up by `initiative_id` + `form`, not by a hard-coded id**, and run after this stage.
- **Population = the Initiative's Sessions except `experiment=after`**, the same as 10 and the fixtures. So the fixture result is 6 of 8, share 0.75, $0.13183248, which equals the value in `derived.json`.
- **Thresholds:** repeated means found in >= `floor` (2) Sessions AND (>= 5 Sessions OR >= 20% of the population). The floor was added because 20% of a small Initiative would otherwise flag one-offs: `REDIS_URL` is 1 of 3 auth-migration Sessions, i.e. 33%. Set them with `--min-sessions`, `--min-share` and `--floor`, or with the env vars `DWIGHT_RD_MIN_SESSIONS`, `DWIGHT_RD_MIN_SHARE` and `DWIGHT_RD_FLOOR_SESSIONS`.
- **Spend:** for each Session, the Spend of Calls with `seq <= call_seq`, counted once per Session (from the earliest Discovery if the Session found the fact twice), then summed.
- **12 (Drafter):** `statement` is already one instruction-style line (live: "Set STORAGE_ENV=staging before running blobctl plan or migration commands."), so the memory file can use it as-is or polish it.
- **15 (scale):** grouping needs no embeddings. Up to `--batch-size` (default 300) Discoveries go in ONE `chat_json` call per Initiative. Larger Initiatives run in rounds of parallel batches (locality order, then half-batch-shifted, then reshuffled), followed by a pass that merges the model-named clusters, so parts of one fact grouped in separate batches end up together. Across batches this is best effort: two lone wordings in different batches can stay apart, so raise `--batch-size` rather than lower it if the model copes. `--workers` (default 4, env `DWIGHT_RD_WORKERS`) bounds the model calls in flight across all Initiatives. An Initiative whose Discoveries come from fewer than `floor` Sessions makes no model call. Only 8 Discoveries were tested live (1 call, 1.2 s). A 300-statement call has NOT been tested live, so check its latency and grouping quality in the first full run.
- The stage uses the model pool (`tier=None`) unless `--tier` is passed.
