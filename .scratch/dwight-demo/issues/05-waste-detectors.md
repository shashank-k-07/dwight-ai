# 05: Waste detectors → Measured Waste and Estimated Saving on Overview

**What to build:** All four Waste Pattern detectors as a pipeline stage that writes WasteFindings. Overview shows the Measured Waste and Estimated Saving totals next to Spend, each labelled. Redundant Read, Cache Miss and Runaway Loop are pure arithmetic on Calls (Measured). Model Overkill uses the Session's `complexity` (Estimated). Pricing rules are exactly as in build-spec §4.2.

**Blocked by:** 01

**Status:** ready-for-agent

**Decision (2026-09-26, user):** Model Overkill appears in synthetic data only. The real-layer models (`deepseek-v4.1-flash`, `glm-5.3-flash`) are tier `light` in `data/prices.yaml`, so `pricing.cheaper_model()` returns None for them and the detector must produce no Model Overkill finding on those Sessions. Add a test for that.

- [ ] Redundant Read: a duplicate `result_hash` is priced on every later Call at the input rate that Call actually paid (uncached on the first Call, cache-read after that if caching is on), not all at the uncached rate
- [ ] Cache Miss: same `prompt_prefix_hash` as the previous Call, but `cache_read_tokens` well below the shared prefix. Priced as (shared prefix − cache read) × (uncached − cached input price).
- [ ] Runaway Loop: ≥ N consecutive Calls with the same tool name + args hash and no new result hash. Spend on every Call after the first repeat. N is configurable.
- [ ] Model Overkill: `complexity` = low and flagship tier. Session Spend minus the same tokens at the cheaper tier. Kind is Estimated.
- [ ] Each finding records its evidence (the Call IDs)
- [ ] Unit tests on hand-built Call sequences cover each pattern, a clean Session with no findings, and the Redundant Read cached-vs-uncached pricing rule
- [ ] Overview shows Spend, Measured Waste and Estimated Saving as separate totals, each with its label
