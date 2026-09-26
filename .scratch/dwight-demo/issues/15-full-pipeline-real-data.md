# 15: Full pipeline run over real + synthetic data

**What to build:** Integration. Run every stage in order over the real layer and the synthetic dataset, switch every API endpoint from fixtures to the real store, and check the spec's acceptance criteria against real data. This produces the real Draft for the planted Initiative that 16 needs.

**Blocked by:** 03, 04, 05, 06, 07, 09, 10, 11, 12

**Status:** ready-for-agent

**Decision (2026-09-26, user):** the real layer has no planted Model Overkill runs (see 03). Model Overkill findings are expected from the synthetic layer only; on the real layer, check that there are none.

- [ ] The pipeline runs end to end with one command from an empty store
- [ ] Detectors flag every planted run from 03 with its pattern, and clean runs show no Measured findings (checked against 03's label file)
- [ ] Measured Waste on the real layer alone is reported separately from the full dataset
- [ ] The planted Initiative produces both RecurringDiscovery forms: the 4 `company-docs/` docs as the common path, and the planted env-var fact as a repeated Discovery
- [ ] The real Draft for the planted Initiative is ≤ 25% of the source tokens and keeps every planted fact that sits in the docs
- [ ] The top 3 Initiatives each have ≥ 2 Recommendations, each citing a real Practice and a real Infra Profile item
- [ ] No endpoint still serves fixture data, and every screen renders from the real store
- [ ] Any gaps found are fixed, or written up as new tickets

## Comments


**From 14 (merged):** policy endpoints are already served from the store, so there's nothing to switch. Apply writes `<out dir>/<team id>.yaml`; set `DWIGHT_OUT_DIR` if it shouldn't write into the repo's (gitignored) `out/`.

**From 10 (merged):** run `common_paths` after classify. `experiment='after'` runs are excluded automatically, and Initiatives with fewer than 3 analysed Sessions get no common path (`--min-sessions`). If the real storage Initiative's share falls below 60%, adjust it with `--threshold`. Redundant Read (05) and common paths should use the same per-Call cache rule (`cache_read_tokens > 0` on that Call), so their Measured figures agree; `common_paths.read_cost()` implements it.

**From 05 (merged):** classify must run before detect, or Model Overkill sees no complexity. **Risk:** if Sciforium doesn't report `cache_read_tokens` (or doesn't cache), every multi-Call real Session with a stable prefix hash is flagged as Cache Miss, and the data can't tell that apart from a genuine miss. Check one real Session's raw usage before quoting "Measured Waste on the real layer" (03's Comments should record what the provider returns). Detector options: `--loop-min` (default 3) and `--cache-miss-ratio` (default 0.5). Runaway Loop Waste is the Spend of every Call in the run after the first. Model Overkill is flagship + low complexity only (never the real layer's Flash models).

**From 11 (merged):** a cluster becomes a repeated Discovery when it's found in ≥ 2 Sessions AND (≥ 5 Sessions OR ≥ 20%). Tune with `--min-sessions`, `--min-share`, `--floor` or `DWIGHT_RD_*`. Only an 8-Discovery call has been tried live; a full 300-statement batch is untested for speed and grouping quality, so check the first full run. Grouping across batches is best effort: raise `--batch-size` if the model copes rather than lowering it. `--workers` (default 4) caps model calls in flight. Initiatives whose Discoveries come from fewer than 2 Sessions make no model call.

**From 06 (merged):** classify runs at about 3 Sessions/s with 8 workers, so 5K Sessions take about 30 min (`--workers` to raise it, `--dataset`/`--limit` to select, and it resumes, since only Sessions with staged content are classified). Run it after the final ingest, because it deletes content. The "Serves now" column in `docs/api-contract.md` still says "fixture" for endpoints that are now store-backed; update it here.

**From 09 (merged):** recommend runs at ORDER 60. Flags: `--initiative`, `--no-teams`, `--no-glm` (fallback text only, offline), `--tier`, `--workers`. The real layer has no Model Overkill, so it produces no Policy Recommendations. The harness agent name `dwight-harness` isn't in the Infra Profile, so ref hints fall back to the Business Function's agents. `infra_refs` hold Infra Profile ref ids (`mcp:perch-docs-mcp`), while the API fixtures show display names; both are strings.

**Integration check on build after 05/06/09/10/11 merged (live, raw fixtures):** classify → detect → common_paths → repeated_discoveries → recommend all ok. 22/22 classified, 5 findings, 1 common path, 1 repeated Discovery, 11 Recommendations with 0 rejected and 0 fallbacks.

**Coordinator change after 03 merged (2026-09-26):** two detector fixes on `build`.
1. **Cache Miss isn't observable on Sciforium.** It returns no cached-token fields (`prompt_tokens_details` is null), so `cache_read_tokens` is 0 on every real Call, and the detector flagged every clean multi-Call real Session. `data/prices.yaml` now marks the pool models `reports_cache_usage: false` (`pricing.reports_cache_usage()`), and `_cache_misses` skips those Calls. Like Model Overkill, **Cache Miss shows up in synthetic data only.** 03's 9 planted Cache Miss Sessions stay in the dataset, but can't be detected on this provider. Say so if asked; don't fake cache tokens.
2. **Runaway Loop compared each Call's tool calls as an ordered tuple with duplicates,** but DeepSeek often sends the same `run_tests` 1–3 times in one Call, which broke the run. It now compares the set of distinct (name, args hash).

Scored against 03's labels on the real layer: clean runs 14/14 with no findings, Redundant Read 9/9, Runaway Loop 8/8, Cache Miss 0/9 (not observable). Extra findings are genuine: Redundant Reads outside the loop run in the Runaway Loop Sessions, a spontaneous loop in real-017, and a re-read in real-031. Real layer: 40 Sessions, $0.93 Measured Spend, $0.158 Measured Waste.
