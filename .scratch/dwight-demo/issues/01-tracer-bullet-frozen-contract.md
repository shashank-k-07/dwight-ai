# 01: Tracer bullet: one Session end to end, with the frozen contract and fixtures

**What to build:** The skeleton every other ticket plugs into. One hand-written OTLP JSON Session is ingested, stored, priced from `prices.yaml`, and its Spend shows on the Overview screen. The same run freezes the data model (build-spec §3) and the API contract. It also ships fixture data rich enough that every later ticket can build and test its pipeline stage and its screen panel without waiting for real data. This ticket is the prefactor that lets many agents run in parallel, so land it fast and keep it thin.

Stack: Python + FastAPI, DuckDB or SQLite, Next.js single-page dashboard (Streamlit only if Next.js blocks progress). GLM is called through one small client wrapper that takes the model tier from config.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Store schema covers every entity in build-spec §3: Session, Call, Initiative, WasteFinding, RecurringDiscovery, Recommendation, Draft, Policy, plus the `dwight.experiment` tag on Sessions and per-task success/fail for experiment runs
- [ ] Raw prompt content goes only into a transient staging area. The code states it is deleted once classified (ADRs 0005, 0008).
- [ ] Ingest accepts OTLP JSON following the OTel GenAI semantic conventions. Business Function, Team and Member come from resource attributes (ADR 0003). Cache-token and message-content attribute names are checked against the current semconv version, and any missing ones use a `dwight.*` attribute with a code note.
- [ ] `prices.yaml` has real list prices (input, output, cache read, cache write per 1M tokens) for every GLM tier in use. Spend is always tokens × price.
- [ ] The GLM client wrapper exists, with the model tier as a config value and structured-JSON output support
- [ ] The API contract is written down (endpoint list + response shapes) for Overview, Initiatives, Initiative detail (Waste breakdown, Recurring Discovery, Recommendations, Draft, before/after, Sessions), Policy and the closing-numbers strip. Every endpoint serves committed fixture JSON until its real stage lands.
- [ ] Fixture data includes: Sessions with prompt content (including one *storage cost reduction* Session with a trial-and-error env-var fact), Call sequences that exhibit each of the four Waste Patterns plus clean ones, Trails, Discoveries, WasteFindings of both kinds, RecurringDiscoveries of both forms, Recommendations, a Draft, a before/after pair, and a Policy
- [ ] The pipeline has one entry point with a registered, separately runnable stage per component (ingest, classify, detect, common paths, repeated Discoveries, recommend, draft), so each ticket adds its stage without editing a shared file
- [ ] The dashboard has shells for Overview, Initiatives, Initiative detail and Policy, with one separate slot/component per panel listed in build-spec §4.5, so each ticket owns its own panel
- [ ] A shared money display component always renders the Measured or Estimated label. There is no way to show a dollar figure without one.
- [ ] Tracer bullet works: the hand-written Session is ingested, priced, and its Spend appears on Overview from the real store (not fixture)
