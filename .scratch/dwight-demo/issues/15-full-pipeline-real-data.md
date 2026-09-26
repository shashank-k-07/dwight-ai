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
