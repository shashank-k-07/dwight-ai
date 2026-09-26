# Dwight: hackathon build spec

**Deadline:** code freeze at 2:00 PM Sunday, followed by a live demo to the judges (Glasswing "Enterprise-Ready AI").
**Team:** 3 engineers with plenty of compute and access to GLM models.
**Vocabulary:** [CONTEXT.md](../CONTEXT.md). **Decisions:** [docs/adr/](adr/). Use the glossary terms in code, UI copy and the pitch.

## 1. What we're demoing

An Admin (the CTO or IT admin) opens Dwight for a fictional company and, in about 3 minutes:

1. Sees last month's agent **Spend** split by **Business Function**, with **Measured Waste** and **Estimated Saving** shown as separate totals.
2. Opens the **Initiatives** view, ranked by Spend, and sees that *"storage cost reduction"* is the most expensive work in Engineering.
3. Opens that Initiative and sees:
   - which **Waste Patterns** drove its cost
   - **Recommendations** aimed at it, each citing a **Practice** and naming parts of the company's infra
   - a dollar figure on each Recommendation
4. Sees the Initiative's **Recurring Discovery**: "32 of 40 Sessions read the same 4 docs (18K tokens) to get started, and 14 Sessions separately worked out that the migration needs `STORAGE_ENV=staging`." Opens the **Draft** Dwight wrote: a consolidated 3K-token doc for the Initiative, plus memory entries.
5. Sees the proof: the same 10 real tasks run **before and after** loading the Draft. "Next 10 Sessions: 38% fewer tokens" (whatever the real figure turns out to be; this is Measured).
6. Applies one Recommendation as a **Policy** (limit a Team's model access), and Dwight produces the gateway config.
7. Closes on the numbers: "$X of Spend analysed, $Y Measured Waste found, Drafts cut tokens by Z%, classifier W% accurate."

The judges require **measurable ROI** and a **path to deployment**. Steps 5 and 7 cover the first. The second is covered by one architecture slide: runs in the customer's cloud, OTel rollout, raw prompts discarded (ADR 0005).

## 2. Architecture

```
 Agent harness (GLM, OTel on) ──┐
                                ├──► OTLP JSON ──► Ingest ──► Store (Sessions, Calls)
 Synthetic generator ───────────┘                               │
                                          ┌─────────────────────┼─────────────────────┐
                                          ▼                     ▼                     ▼
                                 Initiative classifier   Waste detectors      Infra Profile
                                     (GLM)               (arithmetic + GLM    (inferred + declared)
                                          │               for Model Overkill)          │
                                          └──────────┬──────────┘                      │
                                                     ▼                                 │
                                          │  Trails + Discoveries                      │
                                          ▼                                            │
                                 Cross-session analysis                                │
                                 (code: common paths · GLM: repeated Discoveries)      │
                                          │                                            │
                                          ▼                                            │
                                 Recommendation engine (GLM + Practice Library) ◄──────┘
                                          │  └──► Drafter (GLM; re-fetches source docs)
                                          ▼
                              API ──► Dashboard ──► Policy export (gateway config)
                                                └──► Draft export (doc / memory file)
```

Dwight never sits in the request path (ADR 0002). Everything is batch over stored telemetry. That's fine for the demo, and it's the honest architecture.

**Proposed stack (decide in the first 30 minutes, then don't revisit):**
- Python + FastAPI for the backend.
- DuckDB or SQLite for storage.
- A Next.js single-page dashboard with a chart library. If nobody wants to own frontend, fall back to Streamlit.
- GLM called through one small client wrapper, so the model tier is a config value.

## 3. Data model

Freeze this by **1:00 PM Saturday**. Every workstream codes against it.

**Session**
- `session_id`, `member_id`, `team`, `business_function`, `agent`
- `started_at`, `ended_at`
- *Derived:* `initiative_id`, `summary` (redacted, one line), `spend_usd`, `complexity` (low / med / high)
- *Derived:* `trail[]`: ordered `{resource_id, tokens, call_seq}`, where `resource_id` is a normalised path/URL/doc ID
- *Derived:* `discoveries[]`: short redacted statements plus the `call_seq` where each was established

**Call** (one model request inside a Session)
- `call_id`, `session_id`, `seq`, `model`
- `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`
- `tool_calls[]`: name, args hash, result hash, result tokens
- `prompt_prefix_hash`, `spend_usd`

**Other entities**
- **Initiative:** `initiative_id`, `name`, `description`, `session_count`, `spend_usd`
- **WasteFinding:** `session_id`, `pattern` (redundant_read | cache_miss | runaway_loop | model_overkill), `kind` (measured | estimated), `usd`, `evidence` (the call IDs involved)
- **RecurringDiscovery:**
  - `initiative_id`, `form` (common_path | repeated_discovery)
  - `resource_ids[]` (for a common path) or `statement` (for a repeated Discovery)
  - `session_count`, `session_share`, `spend_usd` (Measured: what the repetition cost), `evidence` (session IDs)
- **Recommendation:**
  - `target_type` (initiative | team | policy), `target_id`, `practice_id`
  - `title`, `body`, `infra_refs[]`, `usd`, `kind` (measured | estimated), `draft_id?`
- **Draft:** `draft_id`, `recommendation_id`, `type` (initiative_doc | memory), `content` (markdown), `source_resource_ids[]`, `tokens`
- **Policy:** `team`, `allowed_models[]`, `rendered_config`

**Pricing:** keep a `prices.yaml` table (per-model USD per 1M tokens: input, output, cache read, cache write). Fill it with real list prices. Spend always equals tokens × price, and the LLM never produces dollar figures.

**Ingest:** OTLP JSON following the OpenTelemetry GenAI semantic conventions (`gen_ai.request.model`, `gen_ai.usage.input_tokens` / `output_tokens`, and so on). Business function, team and member go in resource attributes (ADR 0003). **Before relying on them, check which cache-token and message-content attribute names are in the current semconv version.** If one is missing, use a `dwight.*` attribute in its place and note that in the code.

## 4. Components

### 4.1 Demo data: *owner E1*

Two layers:

- **Real layer (credibility).** A small tool-using agent harness on GLM with OTel on, run for 30–50 real tasks against a real open-source repo. Include planted variants that produce each Waste Pattern:
  - **Redundant Read:** the agent re-reads the same files each turn.
  - **Cache Miss:** a timestamp or other volatile text at the top of the prompt.
  - **Runaway Loop:** a retry with no exit condition on a failing test.
  - **Model Overkill:** the flagship tier doing trivial edits.
  Also include clean runs, so the detectors have negatives.
- **Recurring Discovery in the real layer.** Choose one Initiative (e.g. *storage cost reduction*) and write about 10 tasks for it that all need the same information, but spread across 4 docs of 3–6K tokens each. Put these docs in a `company-docs/` folder written in the style of the fictional company. Plant 1–2 facts that aren't in any doc and can only be learned by trial and error (e.g. an env var the migration script needs). These give you the common path and the repeated Discovery.
- **Before/after runs (the proof).** Run the same ~10 tasks twice: first without the Draft, then with the Draft doc and memory file loaded into the agent's context. Same model, same harness. Record both sets through OTel like any other Sessions, tagged `dwight.experiment=before|after`. Owned by E1; needs the Draft from §4.6 by **11:00 Sunday**.
- **Synthetic layer (scale).** A fictional company of about 200 Members across 4–5 Business Functions, about 12 Teams, about 15 Initiatives, and 3–5K Sessions over 30 days.
  - Sample Session shapes (call counts, token distributions, pattern rates) from the real layer's statistics.
  - Generate realistic prompt content with GLM, so the classifier has real text to read.
  - Give each synthetic Initiative a set of "usual" docs that most of its Sessions read, and a few repeated Discoveries, at varied strengths, so cross-session analysis has something to find beyond the one real Initiative.
  - Put Engineering at about 70% of Sessions and include at least one non-engineering Business Function.
- **Ground truth.** The generator records each Session's true Initiative in a **separate file the classifier never sees**. We use it to report accuracy on stage (§5).
- **Infra Profile for the fictional company.** A hand-written YAML covering:
  - models and tiers available
  - gateway (LiteLLM or Azure API Management)
  - whether prompt caching is enabled
  - internal docs/MCP servers
  - main repositories
  The Recommendations cite these, so make them specific.

### 4.2 Waste detectors: *owner E1, after the data is in*

Measured detectors are pure arithmetic on Calls. They are deterministic and unit-tested against the planted runs.

| Pattern | Detection | Dollars |
|---|---|---|
| **Redundant Read** | A tool result whose `result_hash` already appeared earlier in the Session | Agents resend the whole context on every Call, so the duplicate copy is billed again on each Call from where it appears through the end of the Session. Waste = for each of those Calls, result tokens × the input rate that Call actually paid for them: the uncached rate on the first Call, and the cache-read rate after that if caching is on (Measured). Don't price every copy at the uncached rate; that overstates a number we call measured. |
| **Cache Miss** | A Call whose `prompt_prefix_hash` matches the previous Call's, but where `cache_read_tokens` is much smaller than the shared prefix | (shared prefix tokens − cache_read_tokens) × (uncached − cached input price) (Measured) |
| **Runaway Loop** | ≥ N consecutive Calls with the same tool name + args hash and no new result hash | spend on every Call after the first repeat (Measured) |
| **Model Overkill** | The Session's `complexity` = low (from the classifier) and its model is the flagship tier | Session spend − the same tokens priced at the cheaper tier (**Estimated**) |

**Acceptance:** every planted run is flagged with its pattern, and the clean runs show no measured findings.

### 4.3 Initiative classifier: *owner E2*

1. For each Session, GLM reads its prompt content and produces:
   - a redacted one-line `summary`
   - a free-text initiative phrase
   - `complexity`
   - `discoveries[]`: facts the Agent worked out during the Session that it didn't have at the start. Signs to look for: a failed attempt followed by a success, or an answer that finally turns up in a tool result. Keep each to one sentence, redacted, and generalisable ("the migration script needs `STORAGE_ENV=staging`", not "I ran it and it worked").
2. **Trail** is built by code, not GLM: take the resource identifiers from read-type tool calls (file paths, doc IDs, URLs), normalise them, and record their result tokens.
3. Group the initiative phrases into Initiatives. Embeddings plus clustering is one option; a second GLM pass to name and merge groups is another. Each Initiative gets a clear `name`.
4. Throw away the raw prompt text after classification. Store only the derived fields, and state this in the code (ADRs 0005, 0008). A badly extracted Discovery can't be re-derived later, so check the Discovery prompt on the planted real runs before running it over the full dataset.

**Acceptance:** evaluated against the ground-truth file, reported as the share of Sessions placed in the right Initiative. Get a first number by Saturday evening, then improve the prompt.

### 4.4 Practice Library + Recommendation engine: *owner E2*

- **Practice Library.** About 15 practices in a versioned YAML. Each has:
  - `id`, `title`, `fixes` (Waste Patterns), `description`, `applies_when`, `infra_requirements`
  - an example: *cache-friendly prompt layout* (fixes Cache Miss), *shared context file per service* (fixes Redundant Read), *step budget + loop breaker* (fixes Runaway Loop), *tier routing by complexity* (fixes Model Overkill), *point agents at the internal docs server* (fixes Redundant Read), *consolidated initiative doc* (fixes Recurring Discovery, common path), *initiative memory file* (fixes Recurring Discovery, repeated Discovery)
- **Engine, for each Initiative** (plus per Team for Policy candidates):
  1. **Code** collects the Initiative's Waste findings, grouped by pattern, with dollar totals.
  2. **Code** narrows to Practices whose `fixes` match and whose `infra_requirements` the Infra Profile meets.
  3. **GLM** picks the Practices that fit best and writes a Recommendation tailored to this Initiative and infra. It must cite `practice_id` and name specific `infra_refs`, and it outputs structured JSON.
  4. **Code** attaches `usd` and `kind` from the findings. The LLM never outputs dollar figures (ADRs 0006, 0007).

**Acceptance:** the top 3 Initiatives each get at least 2 Recommendations. Every one cites a real Practice and at least one real item from the Infra Profile.

### 4.6 Cross-session analysis + Drafts: *common paths E1, everything else E2*

Runs per Initiative, on stored Trails and Discoveries only (ADR 0008).

1. **Common paths** (code, E1)
   - For each `resource_id`, compute the share of the Initiative's Sessions whose Trail contains it.
   - Resources read in ≥ 60% of Sessions make up the common path. If you have time, find resource *sets* co-read in ≥ 60% (frequent itemsets); single resources are enough for the demo.
   - `spend_usd` = Σ over Sessions of the common-path resources' tokens × the input rate each Call actually paid. This uses the same pricing rule as Redundant Read, so it's Measured.
2. **Repeated Discoveries** (GLM, E2)
   - Cluster the Initiative's Discoveries by meaning (embeddings, then a GLM pass to merge and name each cluster).
   - A cluster reached separately in ≥ 5 Sessions (or ≥ 20%) becomes a repeated Discovery.
   - `spend_usd` = the spend in each Session from its start up to the Call where that Discovery was established (`call_seq`), summed across Sessions. It's Measured, and a conservative upper bound on what the memory entry saves; label it that way in the UI.
3. **Drafter** (GLM, E2). For each RecurringDiscovery above threshold:
   - *Common path → initiative doc.* Fetch the source docs by `resource_id` from where they live (for the demo, `company-docs/`; never from stored prompts). Give GLM those docs plus the Initiative's Discoveries and Session summaries, and ask for a consolidated doc containing **only what these Sessions actually needed**, with source links. Target at most 25% of the common path's tokens.
   - *Repeated Discovery → memory entries.* One line per cluster, written as an instruction an Agent can act on, grouped into one memory file per Initiative.
   - Attach the Draft to a Recommendation that cites the matching Practice.
4. **Price the Recommendation** (code)
   - Initiative doc: Estimated Saving = (common-path tokens − Draft tokens) × Sessions per month × input rate.
   - Memory entries: Estimated Saving = the repeated Discovery's measured `spend_usd`, scaled to a month.
   - Both stay **Estimated** until a before/after run exists for that Initiative. When it does, show the Measured drop from the runs next to the estimate.

**Acceptance:**
- The planted real Initiative produces both forms of RecurringDiscovery: its 4 docs as the common path, and the planted env-var fact as a repeated Discovery.
- The Draft doc is at most 25% of the source tokens and still contains every planted fact that sits in those docs.
- The before/after runs show a token drop, with no loss in task success. Record success/fail per task; if success drops, the number doesn't count.

### 4.5 API + dashboard + Policy export: *owner E3*

Start on **fixture JSON on Saturday afternoon**; don't wait for the real pipeline.

**Screens, in priority order:**
1. **Overview.** Spend, Measured Waste and Estimated Saving totals, plus Spend by Business Function (stacked by Team).
2. **Initiatives.** A table ranked by Spend with Session count, Waste split measured/estimated, and top Waste Pattern.
3. **Initiative detail.** Waste Pattern breakdown, **Recurring Discovery** panel ("32 of 40 Sessions read these 4 docs"; "found separately in 14 Sessions"), Recommendations (showing the Practice, infra refs and $ with a measured/estimated badge), a **Draft viewer** with a download button, a **before/after** panel when runs exist (tokens, Spend and task success, side by side), and a list of Sessions.
4. **Policy.** Pick a Team, choose allowed models, see the rendered gateway config (a LiteLLM team allowlist YAML is enough) and click "Apply" (which writes the file).
5. *(Stretch)* **Session detail.** A timeline of Calls with the flagged calls highlighted.

**Rule:** a dollar figure never appears without its Measured or Estimated label.

## 5. Numbers we must have on stage

| Claim | Source |
|---|---|
| Spend analysed, Measured Waste, Estimated Saving | Detector output over the full dataset |
| Measured Waste on the **real** layer, not synthetic | Detector output over the harness runs only |
| Classifier accuracy | §4.3 eval against ground truth |
| Token and Spend drop from a Draft, with task success unchanged | §4.1 before/after runs (real layer, Measured) |
| "What it replaces / what it costs" | Pitch: cost dashboards (CloudZero and similar) show *who* spent; Dwight shows *what for* and *what was waste*. About $20 per tracked developer per month, set against the waste it finds. |

## 6. Timeline

| When | Milestone |
|---|---|
| Sat 11:30–1:00 | Stack chosen, data model frozen, repo scaffolded, first drafts of the Infra Profile and Practice Library YAML, `company-docs/` written for the planted Initiative |
| Sat 1:00–5:00 | Harness runs, including the ~10 "before" tasks (E1) · classifier v1 with Discoveries, run on the planted runs first (E2) · dashboard screens 1–2 on fixtures (E3) |
| Sat 5:00–8:00 | Full dataset ingested · detectors pass on planted runs · common paths computed · first accuracy number · Recommendations v1 · dashboard wired to the real API |
| Sun 9:30–11:00 | Repeated Discoveries + Drafter produce the Draft for the planted Initiative (E2) · screens 3–4 (E3) |
| Sun 11:00–12:00 | "After" runs with the Draft loaded (E1) · before/after panel (E3) · polish Recommendation copy · Policy export |
| Sun 12:00–12:30 | **Feature freeze.** Fix bugs only after this. |
| Sun 12:30–2:00 | Rehearse the demo 3+ times. Record a backup screen capture in case live fails. Freeze numbers for the slides. |

## 7. Cut list (cut from the top if behind)

1. Session detail screen
2. Policy "Apply" (show the rendered config only)
3. Resource-set itemsets (single-resource common paths are enough)
4. Cross-session analysis on synthetic Initiatives (do it on the planted real Initiative only)
5. Memory entries (keep the initiative doc)
6. Clustering (have the classifier pick from the ~15 known Initiative names instead; say so if asked)
7. Before/after runs (show the Estimated Saving only; this loses the best number on stage, so it's close to last)
8. The real layer (synthetic only; the "real waste" number is lost, so this is the last resort)

**Never cut:** the measured/estimated labels, Practice citations on Recommendations, the accuracy number, or the initiative doc Draft for the planted Initiative.

## 8. Out of scope

- Enforcement in the request path
- A hosted shared-memory service (Drafts are files; ADR 0008)
- Seat-licensed chat tools
- Cursor and Claude Code connectors
- Hosting in the customer's tenant (it goes on a slide, not in code)
- Counterfactual replay
- Auth and multi-tenancy
