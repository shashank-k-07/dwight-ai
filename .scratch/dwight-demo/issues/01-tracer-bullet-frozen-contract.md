# 01: Tracer bullet: one Session end to end, with the frozen contract and fixtures

**What to build:** The skeleton every other ticket plugs into. One hand-written OTLP JSON Session is ingested, stored, priced from `prices.yaml`, and its Spend shows on the Overview screen. The same run freezes the data model (build-spec §3) and the API contract. It also ships fixture data rich enough that every later ticket can build and test its pipeline stage and its screen panel without waiting for real data. This ticket is the prefactor that lets many agents run in parallel, so land it fast and keep it thin.

Stack: Python + FastAPI, DuckDB or SQLite, Next.js single-page dashboard (Streamlit only if Next.js blocks progress). GLM is called through one small client wrapper that takes the model tier from config.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [x] Store schema covers every entity in build-spec §3: Session, Call, Initiative, WasteFinding, RecurringDiscovery, Recommendation, Draft, Policy, plus the `dwight.experiment` tag on Sessions and per-task success/fail for experiment runs
- [x] Raw prompt content goes only into a transient staging area. The code states it is deleted once classified (ADRs 0005, 0008).
- [x] Ingest accepts OTLP JSON following the OTel GenAI semantic conventions. Business Function, Team and Member come from resource attributes (ADR 0003). Cache-token and message-content attribute names are checked against the current semconv version, and any missing ones use a `dwight.*` attribute with a code note.
- [x] `prices.yaml` has real list prices (input, output, cache read, cache write per 1M tokens) for every GLM tier in use. Spend is always tokens × price.
- [x] The GLM client wrapper exists, with the model tier as a config value and structured-JSON output support
- [x] The API contract is written down (endpoint list + response shapes) for Overview, Initiatives, Initiative detail (Waste breakdown, Recurring Discovery, Recommendations, Draft, before/after, Sessions), Policy and the closing-numbers strip. Every endpoint serves committed fixture JSON until its real stage lands.
- [x] Fixture data includes: Sessions with prompt content (including one *storage cost reduction* Session with a trial-and-error env-var fact), Call sequences that exhibit each of the four Waste Patterns plus clean ones, Trails, Discoveries, WasteFindings of both kinds, RecurringDiscoveries of both forms, Recommendations, a Draft, a before/after pair, and a Policy
- [x] The pipeline has one entry point with a registered, separately runnable stage per component (ingest, classify, detect, common paths, repeated Discoveries, recommend, draft), so each ticket adds its stage without editing a shared file
- [x] The dashboard has shells for Overview, Initiatives, Initiative detail and Policy, with one separate slot/component per panel listed in build-spec §4.5, so each ticket owns its own panel
- [x] A shared money display component always renders the Measured or Estimated label. There is no way to show a dollar figure without one.
- [x] Tracer bullet works: the hand-written Session is ingested, priced, and its Spend appears on Overview from the real store (not fixture)

## Comments

**Done (ticket 01).** Start with `docs/dev.md`: how to run things, fixtures, adding a stage or panel, Money. The contract is `docs/api-contract.md` + `backend/dwight/api/contract.py` (TS mirror: `dashboard/src/lib/contract.ts`). The schema is `backend/dwight/schema.sql`.

Things downstream agents must know:
- **SQLite, not DuckDB.** DuckDB allows only one read-write process, and the API plus many stage processes and agents' tests hit the store at once. The store is `backend/var/dwight.sqlite` (WAL). Set `DWIGHT_DB=<scratch file>` while developing.
- **Python 3.14** (Homebrew) venv at `backend/.venv`; all wheels installed fine. Dashboard: Next 16 + React 19 + Recharts 3.
- **Every $ in every response is a `Money {usd, kind, note}` object**, and every response carries `source: store|fixture`. Panels show a red "fixture data" badge until their endpoint is real. `/api/health` lists each endpoint's source (ticket 15: all must say `store`).
- **Endpoints go real per endpoint**: in your route module, pass `real=_from_store` to your `Endpoint(...)`. Only `/api/overview` is real now.
- **Initiative detail is split into one endpoint per panel** (`/waste`, `/recurring-discoveries`, `/recommendations`, `/drafts`, `/before-after`, `/sessions`), so tickets don't share files.
- **Token semantics follow OTel GenAI**: `calls.input_tokens` INCLUDES cache-read and cache-write tokens, so uncached = input − cache_read − cache_write. The cache-write attribute is `gen_ai.usage.cache_creation.input_tokens` (semconv v1.41) or `..cache_write..` (the semconv-genai repo); both are accepted.
- **Tool calls belong to the Call that requested them** (execute_tool span parent = chat span). Their results enter the input of Call seq+1. Detectors (05) and common paths (10) should price from seq+1 on.
- `calls.prompt_prefix_tokens` (`dwight.prompt.prefix_tokens`) was added beyond build-spec §3, because Cache Miss needs "shared prefix tokens". Also added: `sessions.dataset` (real/synthetic/fixture, for "Measured Waste on the real layer"), `sessions.experiment_task_id`, `sessions.task_success`, `recurring_discoveries.tokens`, `recommendations.suggested_models` / `recurring_discovery_id`, `drafts.title/filename/source_tokens`, `eval_runs`.
- **Raw content lives only in `staging_content`.** Only classify (06) may read it, and it must delete a Session's rows once classified. `seed_fixtures` mimics this.
- **Chat spans send only the new messages** in `gen_ai.input.messages`, not the full history (Dwight convention, see `dwight/ingest/attributes.py`).
- **The OTLP receiver `POST /v1/traces` takes JSON only.** The Python OTel SDK's default exporter sends protobuf. Harness (03) and generator (07): use `dwight.ingest.builder.SessionBuilder`, or write JSON files to `data/otlp/real|synthetic/` and run `pipeline run ingest`.
- **`dwight.team` / `dwight.business_function` carry the display names** from `data/company/org.yaml`. `initiative_id` = org.yaml Initiative id. Fixture names were aligned with 02's org/practices/infra ids (checked 16:10). The API fixtures' demo numbers are hand-picked and are *not* consistent with `fixtures/store/derived.json`.
- **prices.yaml**: Z.ai list prices, verified 2026-09-26. `cache_write` = 0 because Z.ai lists cached storage as "limited-time free". The pricing-side tier names are flagship/standard/light; the Infra Profile calls the cheap tier "economy". `pricing.cheaper_model()` re-prices flagship/standard at glm-4.5-air.
- **Common-path fixture analysis excludes `experiment=after` Sessions** (they ran with the Draft loaded). Ticket 10 should do the same, or the after runs dilute the share.
- **Recommendation `body` is markdown.** The Recommendations panel currently renders it as plain text; 09 may want a renderer. The Draft viewer shows markdown in a `<pre>`; 12 may want a renderer too.
- The dashboard proxies `/api/*` to `DWIGHT_API_URL` (default `http://localhost:8000`). No machine-specific paths are used anywhere.
