# Dwight demo build

The spec is [docs/build-spec.md](../../docs/build-spec.md). Vocabulary is [CONTEXT.md](../../CONTEXT.md); decisions are in [docs/adr/](../../docs/adr/).

## End product

A website: the Next.js dashboard, run locally for the live demo. Hosting is decided later, so keep it deployable: the API base URL comes from an env var, and no paths are specific to one machine.

## Running these tickets in parallel

Every ticket after 01 builds against the fixture data and API contract that 01 freezes. So most tickets need only 01 (and 02 for company content), and many agents can run at once. Checking against real data happens in ticket 15.

| Wave | Tickets | Starts when |
|---|---|---|
| 0 | 01, 02 | now |
| 1 | 03, 05, 06, 10, 11, 13 | 01 is done |
| 1 | 07, 09, 14 | 01 and 02 are done |
| 2 | 04, 08, 12 | their blockers are done |
| 3 | 15 | the pipeline pieces are done |
| 4 | 16 | 15 is done (the "after" runs need the real Draft) |
| 5 | 17 | everything else is done |

Critical path: 01 → 03 → 04 → 15 → 16 → 17. The real Draft must exist by Sunday 11:00 for 16.

Rules for every agent:
- Stay inside the module, pipeline stage and dashboard panel slot that 01 set up for your ticket. If you need to change the frozen schema or API contract, stop and flag it; don't change it yourself.
- A dollar figure never appears without its Measured or Estimated label. The LLM never produces dollar figures (ADRs 0006, 0007).
- Use the glossary terms in code and UI copy.

Left out on purpose (build-spec cut list): Session detail screen, resource-set itemsets, clustering of Initiatives (the classifier picks from the known names).
