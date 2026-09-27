# 05: Waste detectors → Measured Waste and Estimated Saving on Overview

**What to build:** All four Waste Pattern detectors as a pipeline stage that writes WasteFindings. Overview shows the Measured Waste and Estimated Saving totals next to Spend, each labelled. Redundant Read, Cache Miss and Runaway Loop are pure arithmetic on Calls (Measured). Model Overkill uses the Session's `complexity` (Estimated). Pricing rules are exactly as in build-spec §4.2.

**Blocked by:** 01

**Status:** done

**Decision (2026-09-26, user):** Model Overkill appears in synthetic data only. The real-layer models (`deepseek-v4.1-flash`, `glm-5.3-flash`) are tier `light` in `data/prices.yaml`, so `pricing.cheaper_model()` returns None for them and the detector must produce no Model Overkill finding on those Sessions. Add a test for that.

- [x] Redundant Read: a duplicate `result_hash` is priced on every later Call at the input rate that Call actually paid (uncached on the first Call, cache-read after that if caching is on), not all at the uncached rate
- [x] Cache Miss: same `prompt_prefix_hash` as the previous Call, but `cache_read_tokens` well below the shared prefix. Priced as (shared prefix − cache read) × (uncached − cached input price).
- [x] Runaway Loop: ≥ N consecutive Calls with the same tool name + args hash and no new result hash. Spend on every Call after the first repeat. N is configurable.
- [x] Model Overkill: `complexity` = low and flagship tier. Session Spend minus the same tokens at the cheaper tier. Kind is Estimated.
- [x] Each finding records its evidence (the Call IDs)
- [x] Unit tests on hand-built Call sequences cover each pattern, a clean Session with no findings, and the Redundant Read cached-vs-uncached pricing rule
- [x] Overview shows Spend, Measured Waste and Estimated Saving as separate totals, each with its label

## Comments

**Done (ticket 05).** Stage `backend/dwight/pipeline/stages/detect.py`, tests `backend/tests/test_detect.py`. `run detect` rebuilds every Session's findings (`--session ID` repeatable, `--loop-min N` default 3, `--cache-miss-ratio R` default 0.5). It deletes and re-inserts a Session's rows, so it is idempotent. Finding ids are `wf-<session_id>-<k>`. The pure function is `find_waste(calls, complexity)` over the `Call`/`ToolCall` dataclasses, and `load_calls(conn, session_id)` reads them from the store.

How the §4.2 rules were read (the tests pin each one):
- **Redundant Read:** matched on `result_hash` alone, for any tool. One finding per later duplicate. Its tokens are billed on every Call after the requesting Call: uncached on the first of those Calls, then cache-read on each Call with `cache_read_tokens > 0` (that's "caching is on"), otherwise uncached. Evidence = the requesting Call plus the billed Calls. A duplicate requested on the last Call costs $0 and gives no finding.
- **Cache Miss:** fires when the previous Call has the same `prompt_prefix_hash` and model, and `cache_read_tokens < 0.5 × prompt_prefix_tokens`. Priced (prefix − cache_read) × (input − cache_read price). One finding per Session; evidence = the Calls that missed.
- **Runaway Loop:** needs ≥ N consecutive Calls with the same (tool name, args_hash) set and no new `result_hash`. A missing hash never extends a run. The first Call of the run is legitimate; the Spend of every later Call in the run is the Waste. Evidence = every Call in the run. (The old fixture priced one extra Call after the run.)
- **No double counting:** a Call priced in full by a loop is not billed again by Redundant Read or Cache Miss, and a loop's repeats are not Redundant Reads. If the loop is shorter than N, the repeats fall back to being Redundant Reads.
- **Model Overkill:** needs `complexity = 'low'`. Only Calls whose model is tier `flagship` and has a `cheaper_model()` are re-priced, using `call_spend` from the tokens. Kind `estimated`. `standard` is not re-priced, even though prices.yaml maps it: §4.2 says flagship. A NULL complexity (Session not classified yet) gives no Model Overkill; the measured patterns still run.
- **Real layer:** `deepseek-v4.1-flash` and `glm-5.3-flash` are tier light, so they never give Model Overkill. This is tested.

Fixture results (raw fixtures + derived.json complexity): fx-rr-01 has 2 Redundant Reads ($0.00276 + $0.002232), fx-cm-01 a Cache Miss ($0.00588), fx-rl-01 a Runaway Loop ($0.004392, Calls 1–6), fx-mo-01 Model Overkill ($0.00520872, Estimated). Every other fixture Session, clean and storage, has no findings.

Notes for later tickets:
- **09 (WasteBreakdown / Recommendations):** read `waste_findings` directly. `usd` is unrounded; round only through `serving.money`. For Recommendation dollars, sum findings by pattern per Initiative. Overview's Measured/Estimated totals already come from `waste_findings` grouped by `kind`, so I left `overview.py` unchanged.
- **15 (real data):** the pipeline order must be classify (20) → detect (30), or Model Overkill sees NULL complexity. Re-run `detect` after any re-classify. **Watch for Cache Miss on real Sessions.** If the Sciforium pool doesn't report `cache_read_tokens` (or doesn't cache), every multi-Call real Session with a stable `prompt_prefix_hash` gets flagged. The data can't tell that apart from fx-cm-01. Check one real Session's cache reads before quoting "Measured Waste on the real layer". If the provider doesn't cache, exclude those Sessions or drop the prefix hash for them.
- **03/04/07 (emitters):** Redundant Read and Runaway Loop depend on stable `result_hash` values (same content, same hash) and on `args_hash`. Cache Miss needs `dwight.prompt.prefix_hash` + `dwight.prompt.prefix_tokens` on every Call. To plant a Runaway Loop, use ≥ 3 identical consecutive tool calls with an identical result.
- **07 (synthetic):** Model Overkill only fires for flagship models (`glm-5.1`, `glm-5`, `glm-4.5-x`) with `complexity = low`.

**Coordinator change after 03 merged (2026-09-26):** two detector fixes on `build`.
1. **Cache Miss isn't observable on Sciforium.** It returns no cached-token fields (`prompt_tokens_details` is null), so `cache_read_tokens` is 0 on every real Call, and the detector flagged every clean multi-Call real Session. `data/prices.yaml` now marks the pool models `reports_cache_usage: false` (`pricing.reports_cache_usage()`), and `_cache_misses` skips those Calls. Like Model Overkill, **Cache Miss shows up in synthetic data only.** 03's 9 planted Cache Miss Sessions stay in the dataset, but can't be detected on this provider. Say so if asked; don't fake cache tokens.
2. **Runaway Loop compared each Call's tool calls as an ordered tuple with duplicates,** but DeepSeek often sends the same `run_tests` 1–3 times in one Call, which broke the run. It now compares the set of distinct (name, args hash).

Scored against 03's labels on the real layer: clean runs 14/14 with no findings, Redundant Read 9/9, Runaway Loop 8/8, Cache Miss 0/9 (not observable). Extra findings are genuine: Redundant Reads outside the loop run in the Runaway Loop Sessions, a spontaneous loop in real-017, and a re-read in real-031. Real layer: 40 Sessions, $0.93 Measured Spend, $0.158 Measured Waste.
