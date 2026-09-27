# Dwight developer guide (for every ticket agent)

The build plan is `docs/build-spec.md`, the vocabulary is `CONTEXT.md` and the decisions are in `docs/adr/`. Ticket 01 froze three things: the **store schema** (`backend/dwight/schema.sql`), the **API contract** (`docs/api-contract.md` + `backend/dwight/api/contract.py`) and the **fixtures** (`backend/fixtures/`). Code against these. If one has to change, flag it; don't edit it yourself.

## Layout

```
data/prices.yaml                 list prices (Z.ai GLM + real-layer pool models, checked 2026-09-26). Spend = tokens x price.
data/company/*.yaml, company-docs/   ticket 02 content (read via backend/dwight/company.py)
data/ground-truth/               hidden labels. Only the eval (08) and acceptance checks (15) may read it.
data/otlp/                       drop OTLP JSON here (harness -> data/otlp/real/, generator -> data/otlp/synthetic/)
backend/
  dwight/config.py               every path + env var (see /.env.example)
  dwight/schema.sql, db.py       SQLite store (WAL); db.rows() decodes *_json columns
  dwight/pricing.py              call_spend(), input_rate(model, cached), cheaper_model()
  dwight/glm.py                  the one GLM wrapper: chat(), chat_json(schema=...), embed(); tier -> model from env
  dwight/company.py              infra_profile(), practices(), org(), storage_tasks(), company_doc_path()
  dwight/ingest/attributes.py    OTel GenAI + dwight.* attribute names (read this if you emit telemetry)
  dwight/ingest/otlp.py          OTLP JSON -> sessions/calls/tool_calls (+ staging_content)
  dwight/ingest/builder.py       SessionBuilder: build OTLP JSON Sessions in code (harness, generator)
  dwight/pipeline/stages/*.py    one module per stage (registry = file discovery)
  dwight/api/routes/*.py         one module per endpoint group (auto-included)
  dwight/api/contract.py         response models (the contract)
  fixtures/                      otlp/ (Sessions), store/derived.json (derived rows), api/ (one JSON per endpoint)
  tests/
dashboard/
  src/components/Money.tsx       the ONLY way to show a dollar figure
  src/components/Panel.tsx       panel card (loading/error/"fixture data" badge)
  src/lib/contract.ts, api.ts    TS contract mirror; useApi<T>(path)
  src/panels/<screen>/<Panel>.tsx   one file per panel (you own yours)
  src/app/**/page.tsx            screens: composition only, no logic
```

## Run things

Setup, once (Python 3.14 from Homebrew works, and the venv already exists at `backend/.venv`):

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd dashboard && npm install
cp .env.example .env    # add SCIFORIUM_API_KEY and the real model strings when you have them
```

All backend commands run from `backend/`:

```bash
.venv/bin/python -m pytest -q                                  # tests
.venv/bin/uvicorn dwight.api.main:app --reload --port 8000     # API  (http://localhost:8000/docs)
.venv/bin/python -m dwight.pipeline list                       # stages, owners, order
.venv/bin/python -m dwight.pipeline run ingest [paths...]      # default: data/otlp/
.venv/bin/python -m dwight.pipeline run <stage> [args]         # classify | detect | common_paths | repeated_discoveries | recommend | draft
.venv/bin/python -m dwight.pipeline run-all                    # every stage in ORDER (stubs report not_implemented)
.venv/bin/python -m dwight.pipeline run seed_fixtures          # load all fixtures into the store (see below)
.venv/bin/python -m dwight.pipeline reset                      # delete the store file
```

Demo freeze (ticket 17; see `backend/dwight/demo.py`). Order on the final store: `rebuild` → `run eval_classifier score --label "..."` LAST (the strip shows the latest eval) → `snapshot` → `export-numbers`:

```bash
DWIGHT_DB=var/demo.sqlite .venv/bin/python -m dwight.pipeline snapshot         # -> var/snapshots/demo/ (gitignored) + data/demo-snapshot.json (commit it)
DWIGHT_DB=var/demo.sqlite .venv/bin/python -m dwight.pipeline reset-demo       # restore store + Draft files, drop rehearsal Policy files; seconds, no model calls
DWIGHT_DB=var/demo.sqlite .venv/bin/python -m dwight.pipeline export-numbers   # -> docs/demo-numbers.md + .json (what the strip shows, with caveats)
```

Set the same `DWIGHT_OUT_DIR` for these as for the API. The API can stay up during `reset-demo`; reload the dashboard.

Dashboard, from `dashboard/`:

```bash
npm run dev                                   # http://localhost:3000, proxies /api/* to DWIGHT_API_URL (default http://localhost:8000)
DWIGHT_API_URL=http://host:8000 npm run build && npm start
```

In a git worktree whose `dashboard/node_modules` is a symlink to another checkout, `npm run build` (Turbopack) fails; use `./node_modules/.bin/next build --webpack` there. `npm run typecheck` is unaffected.

The default store is `backend/var/dwight.sqlite`. **Set `DWIGHT_DB=/some/scratch.sqlite` while you develop**, so your experiments don't pollute the shared store. The same env var must be set for the API process if you want it to read your scratch store. `DWIGHT_FORCE_FIXTURES=1` makes every endpoint serve fixtures.

## Fixtures

- `fixtures/otlp/tracer_session.json`: the hand-written tracer Session (3 Calls, glm-4.7, Spend $0.00334208).
- `fixtures/otlp/fixture_sessions.json`: 21 Sessions with prompt content, all `dwight.dataset=fixture`:
  - `fx-rr-01`: Redundant Read (re-reads `auth/session.py`)
  - `fx-cm-01`: Cache Miss (volatile timestamp in the system prompt, same `prompt_prefix_hash`, no cache reads)
  - `fx-rl-01`: Runaway Loop (6 identical failing `pytest` runs)
  - `fx-mo-01`: Model Overkill (glm-5.1 fixing a typo; complexity low)
  - `fx-clean-01`, `fx-clean-02`, `fx-mkt-01`: clean (`fx-mkt-01` is Marketing)
  - `fx-scr-b01..b06`: storage cost reduction, `dwight.experiment=before`, task ids t01–t06, 5/6 pass. b01–b05 fail on `blobctl` without `STORAGE_ENV`, then succeed with `STORAGE_ENV=staging` (the trial-and-error fact). All read the 4 `company-docs/`.
  - `fx-scr-07`, `fx-scr-08`: storage, no experiment tag (07 also hits the env-var fact)
  - `fx-scr-a01..a06`: `after` runs with the Draft in the prompt prefix. They read fewer docs, have no trial and error, and 6/6 pass.
- `fixtures/store/derived.json`: what classify, detect, common_paths, repeated_discoveries, recommend and draft *would* write for those Sessions: summaries, Initiatives, complexity, Trails, Discoveries (the env-var fact is worded 6 different ways, plus 2 one-offs), WasteFindings of all 4 patterns (both kinds), both RecurringDiscovery forms, Recommendations, 2 Drafts, a Policy and an eval run. The numbers come from a simplified reading of §4.2/§4.6; your stage is the authority.
- `fixtures/api/<endpoint>.json`: one response body per endpoint, with demo-scale numbers ("32 of 40 Sessions", $31K Spend). These are hand-picked and **not** consistent with the store fixtures. Per-ID endpoints use `{"_keyed_by": ..., "items": {id: body}}`, and an unknown ID falls back to the first item.
- `run seed_fixtures` ingests all the OTLP fixtures, then loads `derived.json`. It deletes staged content for the classified Sessions, like classify does. `run seed_fixtures --raw-only` ingests only (raw Sessions + staged content), for building classify or detect.
- `fixtures/generate.py` regenerates the OTLP, store and API fixtures (not the tracer). The fixtures are frozen; if you need extra fixture data, add your own file rather than changing shared ones.

## Add a pipeline stage (you own one file)

Your stub already exists at `backend/dwight/pipeline/stages/<name>.py`. Its docstring lists what it reads and writes. Replace `run()`:

```python
ORDER = 30; TICKET = "05"; DESCRIPTION = "..."
def run(conn, args: list[str]) -> str:     # parse your own args with argparse
    ...                                      # read/write tables, conn.commit()
    return "12 findings on 40 Sessions"      # one-line summary
```

A new stage is a new file in that folder; discovery is by file name, so no registry edit is needed. Set `IN_DEFAULT_RUN = False` for commands that aren't part of the pipeline (e.g. an eval). Make your stage idempotent: delete the rows you own for the Sessions/Initiatives you process, then insert.

Rules:
- Only **classify** reads `staging_content`, and it must delete a Session's rows after classifying it (ADRs 0005, 0008). Cross-session stages use only `trail_entries` and `discoveries`.
- Nothing reads `data/ground-truth/` except the eval (08) and acceptance checks (15).
- Dollars come from `dwight.pricing` in code, never from GLM output.

## Make an endpoint real

Open your route module in `backend/dwight/api/routes/`. Write `_from_store(conn, **params) -> dict`, returning the response model minus `source` and building every dollar with `serving.money(usd, "measured"|"estimated")`, then pass it in: `Endpoint("initiatives", InitiativeList, real=_from_store)`. `/api/health` then reports `store`. New endpoint groups go in a new route module (it's auto-included), but a new endpoint means a contract change, so flag it first.

## Add or own a dashboard panel

Your panel file already exists in `dashboard/src/panels/<screen>/`. It fetches its own endpoint with `useApi<T>()` and renders inside `<Panel title source loading error>`. Edit only your panel file. The pages in `src/app/` just place the panels. If you need a new panel, create a new file and ask for it to be placed on the page.

| Screen | Panel file | Owner |
|---|---|---|
| Overview | `overview/SpendTotals.tsx` | 01 / 05 |
| Overview | `overview/SpendByBusinessFunction.tsx` | 07 |
| Overview | `overview/ClosingNumbers.tsx` | 17 |
| Initiatives | `initiatives/InitiativesTable.tsx` | 06 |
| Initiative detail | `initiative/InitiativeHeader.tsx`, `initiative/SessionsList.tsx` | 06 |
| Initiative detail | `initiative/WasteBreakdown.tsx`, `initiative/Recommendations.tsx` | 09 |
| Initiative detail | `initiative/RecurringDiscoveryPanel.tsx` | 10 |
| Initiative detail | `initiative/DraftViewer.tsx` | 12 |
| Initiative detail | `initiative/BeforeAfter.tsx` | 13 |
| Policy | `policy/PolicyEditor.tsx` | 14 |

### Money: always Measured or Estimated

```tsx
import { Money, formatMoney } from "@/components/Money";
<Money value={r.saving} />            // "$540.00 [Estimated]"
<Money value={o.spend} size="lg" />   // big stat tile
formatMoney(t.spend)                  // "$1,234 (Measured)" for chart tooltips
```

`Money` takes the contract's `Money` object (`{usd, kind, note}`). `kind` is required by the type, so there is no way to render a figure without its label. The number formatter isn't exported. Never print `.usd` yourself, and label chart axes that show dollars (see `SpendByBusinessFunction.tsx`).

## Emitting telemetry (03 harness, 07 generator)

Read `backend/dwight/ingest/attributes.py`. In short:
- One Session = one `gen_ai.conversation.id`.
- Business Function, Team and Member go in resource attributes `dwight.business_function`, `dwight.team`, `dwight.member.id`. Use the display **names** from `data/company/org.yaml` ("Engineering", "Data Infrastructure") and the Member id. Set `dwight.dataset=real|synthetic`. `sessions.initiative_id` is the org.yaml Initiative `id` (e.g. `storage-cost-reduction`).
- Each `chat` span is a Call. Set `dwight.call.seq`, `gen_ai.request.model`, the usage attributes, `dwight.prompt.prefix_hash` and `dwight.prompt.prefix_tokens`, plus content in `gen_ai.input.messages` / `gen_ai.output.messages` (only the messages new since the previous Call).
- Each `execute_tool` span is a child of the chat span that requested it. Set `gen_ai.tool.name`, `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result` and `dwight.tool.result_tokens`.
- Experiment runs go on the `invoke_agent` span or the resource: `dwight.experiment=before|after`, `dwight.experiment.task_id`, `dwight.experiment.task_success`.

`dwight.ingest.builder.SessionBuilder` produces exactly this shape. Write the payloads to `data/otlp/...` or POST them to `/v1/traces`. The endpoint takes JSON only; the Python OTel SDK's default exporter sends protobuf, so use the builder or a JSON file exporter.
