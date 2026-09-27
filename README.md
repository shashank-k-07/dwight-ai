# Dwight

Dwight shows a company running AI agents what its agent Spend bought, which part was Waste, and how to spend less, with every dollar either Measured from token counts or clearly marked Estimated.

Built at Test Flight, the Glasswing Ventures hackathon, September 26 and 27, 2026.

Team: Rajvi Gemawat (@rgemawat2000), Mark Verhoeven, Shashank Kakarlapudi (@shashank-k-07)


## The problem

Coding and ops agents bill by the token, and one Session can make dozens of model calls. The people who own that bill (a CTO, a head of platform, an IT admin) get it once a month, split by team or API key. It tells them who spent. It doesn't say what the money was for, or how much of it bought nothing.

The Waste is invisible in that view, and it adds up in two ways:

- **Inside one Session.** An agent re-reads a file it already sent. It pays full price for context the prompt cache could have served. It loops on a failing test. It runs a flagship model to fix a typo.
- **Across Sessions.** Many Sessions in the same Initiative redo the same work, because none of them can see what the earlier ones found. In our demo data, 168 of 453 "storage cost reduction" Sessions each worked out separately that a CLI needs `STORAGE_ENV=staging`.

In the fictional company's month that we generated, 16.5% of agent Spend was Measured Waste ($95.89 of $580.92 at list prices). In our 60 real agent runs, it was 8% ($0.16 of $1.98). These are our datasets, not a market figure. Existing cost dashboards can't see either kind of Waste, because it only shows up inside the traces.


## Who pays

Organisations running AI agents at scale. The buyer is whoever owns the agent bill: the CTO, head of platform or engineering, or IT. It comes out of the same AI tooling budget it watches, and it is meant to pay for itself from the Waste it finds.

Why they would sign:

- **Every dollar holds up.** Measured Waste is arithmetic on token counts. Estimated Saving is labelled as such and totalled separately. The model never produces a dollar figure (ADRs 0006, 0007).
- **The ROI is proven, not promised.** The same 10 real tasks were run before and after loading a Draft Dwight wrote: 75.4% fewer tokens per Session, with task success unchanged (10/10 → 10/10).
- **It fits what they already run.** It reads standard OpenTelemetry GenAI traces and sits outside the request path. Policies are written as config for their own gateway (LiteLLM), which does the enforcing.


## How it works

```
agents emit OTel GenAI spans ──► ingest (price every call from list prices) ──► SQLite store
                                                                                   │
   classify ─► detect ─► common paths / repeated discoveries ─► recommend ─► draft │  pipeline stages
                                                                                   ▼
                                                 FastAPI (typed contract) ──► Next.js dashboard
```

1. **Ingest** (`backend/dwight/ingest/`). Parses OTLP JSON into Sessions, Calls and tool calls, and prices every Call from `data/prices.yaml`.
2. **Classify**, with a model. One call per Session reads its transcript and returns:
   - the Initiative the work served, picked from the company's list
   - a one-line summary and a complexity rating
   - the Discoveries: facts the agent worked out that it didn't have at the start.

   The raw prompts are then deleted, and every later stage uses only derived data.
3. **Detect**, code only. Finds Redundant Read, Cache Miss, Runaway Loop and Model Overkill from token counts and hashes, and prices each finding.
4. **Recurring Discovery.**
   - Code finds the resources most Sessions read to get started.
   - A model groups Discoveries that mean the same thing but are worded differently.
   - Code counts them and prices them.
5. **Recommend**, with a model. It picks a Practice from a curated Practice Library (`data/company/practices.yaml`) and writes the Recommendation against the company's Infra Profile. Code rejects any output without a valid Practice and infra reference, or with a dollar figure in it, then attaches the dollars itself.
6. **Draft**, with a model. Writes the fix itself: a consolidated doc at no more than 25% of the source docs' tokens, and a memory file with one line per repeated Discovery.
7. **Dashboard** (`dashboard/`). Shows:
   - Spend by Business Function, Team and Initiative
   - Waste Patterns and ranked Recommendations
   - the Drafts and the before/after proof
   - the Policy screen, which writes a LiteLLM team allowlist.

**Where the AI does work that rules can't:**
- **Attributing a Session to an Initiative from free-form agent content.** It's 97.3% accurate against ground truth on 4,000 Sessions.
- **Recognising the same fact across differently worded Discoveries.** The `STORAGE_ENV` fact alone appears in dozens of wordings.
- **Turning findings into specific Recommendations,** each tied to the company's real infra.
- **Condensing four docs into one short doc** that agents can work from.

Code, not a model, does the detection and every dollar figure.

All model calls go through one wrapper, `backend/dwight/glm.py`, to Sciforium's OpenAI-compatible API (DeepSeek-V4.1-Flash).


## What's real and what's mocked

**Real:**
- **Model calls.** Classify, Discovery grouping, Recommendations and Drafts all make live calls through Sciforium.
- **The real layer: 60 Sessions from a real tool-using agent** (`backend/dwight/harness/`). It runs on DeepSeek-V4.1-Flash in a sandboxed workspace, with its own tools (read, search, run commands, write files).
  - 40 engineering tasks on the open-source repo [tomli](https://github.com/hukkin/tomli). Waste was planted in some of them on purpose: a house rule to re-read files, a timestamp at the top of the prompt, and an unpassable test with a naive retry loop.
  - 20 storage tasks in the fictional company's workspace: 10 before and 10 after loading Dwight's Draft. That pair is where the Measured 75.4% token drop comes from.
- **Token counts and Spend** come from the API responses, priced at list prices recorded in `data/prices.yaml` (checked 2026-09-26).
- **Policy "Apply"** writes a real LiteLLM config file.
- **"Run this fix with a real agent."** With `DWIGHT_LIVE_RUNS=1`, the dashboard can re-run the 10 storage tasks live with the Drafts loaded (about a minute) and measure the result.

**Synthetic or mocked:**
- **The company is fictional.** Kestrel Logistics: its org, docs, Infra Profile and the `blobctl` CLI stub are in `data/company/` and `company-docs/`.
- **4,000 of the 4,060 Sessions are synthetic.**
  - A model wrote a content library once (`data/synthetic/content_library.json`, about 60 calls).
  - Code then assembles the Sessions from it with a fixed seed. It simulates token counts and caching, and plants the Waste.
  - Hidden labels in `data/ground-truth/` are used only to score the classifier and the detectors.
- **Where some patterns show up.** Cache Miss appears only in the synthetic layer, because Sciforium reports no cached-token counts. Model Overkill does too, because the real layer runs one Flash model.
- **Dashboard extras.** "Implement" on a Recommendation is a simulation in the viewer's browser, labelled Simulated · Estimated. The demo shows prices ×100 (`DWIGHT_PRICE_MULTIPLIER=100`), with a badge in the header, because real list prices make one month look tiny.
- **Not built:**
  - connectors for Claude Code or Cursor, which would mean real customer telemetry
  - a gateway that enforces the Policy
  - auth or multi-tenancy
  - hosting in the customer's cloud (it runs on a laptop).

**What would break at real scale:**
- SQLite in one file.
- Classify makes one model call per Session. That's about 4 minutes for 4,000 Sessions at 32 workers, so millions of Sessions a month need batching or a cheaper tier.
- The pipeline rebuilds from scratch rather than running incrementally. The Recommendation stage alone took 28 minutes.
- Initiatives are picked from a fixed list rather than discovered.
- Live runs are held in one API process.


## Running it

Needs Python 3 (tested on 3.14) and Node.js 20.9 or later (tested on 26).

```bash
cp .env.example .env   # put your keys in .env, it never gets committed (SCIFORIUM_API_KEY for model calls)

cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && cd ..
cd dashboard && npm install && cd ..

# 1. Build a store (pick one)
cd backend
.venv/bin/python -m dwight.pipeline run seed_fixtures        # no key needed: a small fixture store
DWIGHT_DB=var/demo.sqlite DWIGHT_OUT_DIR=$PWD/var/out-demo \
  .venv/bin/python -m dwight.pipeline rebuild                   # the full demo: 4,060 Sessions, ~35 min, model calls

# 2. Run the API (from backend/) and the dashboard (from dashboard/)
DWIGHT_DB=var/demo.sqlite DWIGHT_OUT_DIR=$PWD/var/out-demo DWIGHT_PRICE_MULTIPLIER=100 \
  .venv/bin/uvicorn dwight.api.main:app --port 8000      # leave out DWIGHT_DB to use the fixture store
cd ../dashboard && npm run dev                           # http://localhost:3000

# Tests (no model calls)
cd backend && .venv/bin/python -m pytest -q
```

Options:
- `DWIGHT_PRICE_MULTIPLIER=1` (the default) shows real list prices.
- `DWIGHT_LIVE_RUNS=1` turns on the live agent run. It makes real model calls.
- `rebuild` re-runs the models, so its numbers can differ slightly from ours in [docs/demo-numbers.md](docs/demo-numbers.md).
- To freeze a store and restore it between rehearsals, use `python -m dwight.pipeline snapshot` and `reset-demo`.

More detail: [docs/dev.md](docs/dev.md) covers every stage, command and panel. [docs/api-contract.md](docs/api-contract.md) lists the endpoints. [docs/build-spec.md](docs/build-spec.md) is the plan. [CONTEXT.md](CONTEXT.md) is the glossary, and [docs/adr/](docs/adr/) holds the decisions.


## Brought in from before the weekend

None. The repo includes public Claude Code agent skills from [mattpocock/skills](https://github.com/mattpocock/skills) (`.claude/skills/`, `skills-lock.json`), used by our coding agents while building. They are open source and aren't part of the product.
