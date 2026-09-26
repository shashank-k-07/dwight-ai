# 07: Synthetic company dataset → Spend by Business Function

**What to build:** The scale layer. A generator produces 3–5K Sessions over 30 days for the fictional company, as OTLP JSON through the normal ingest. The prompt content is GLM-written so the classifier has real text to read. Overview then shows Spend by Business Function, stacked by Team, over the full dataset.

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] Uses the org from 02: ~200 Members, 4–5 Business Functions, ~12 Teams, ~15 Initiatives, Engineering at ~70% of Sessions, and at least one non-engineering Business Function
- [ ] Session shapes (call counts, token distributions, Waste Pattern rates) come from a parameter file. It is calibrated from 03's real-layer stats if present, otherwise from sensible defaults that can be updated later.
- [ ] Each synthetic Initiative has a set of "usual" docs most of its Sessions read, and a few repeated Discoveries at varied strengths
- [ ] Each Session's true Initiative is written to a separate ground-truth file the classifier never reads
- [ ] The dataset is generated and ingested through the normal OTLP path, not written straight into the store
- [ ] Overview shows Spend by Business Function, stacked by Team
