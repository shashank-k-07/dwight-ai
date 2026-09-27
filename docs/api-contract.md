# API contract (frozen by ticket 01)

The source of truth for the response shapes is `backend/dwight/api/contract.py` (Pydantic). The TypeScript mirror is `dashboard/src/lib/contract.ts`. When the API is running, `http://localhost:8000/docs` shows the live OpenAPI docs. **If you need a shape changed, flag it. Don't change it yourself.**

## Rules that apply to every response

- **Every dollar figure is a `Money` object**: `{"usd": 12.3, "kind": "measured" | "estimated", "note": null | "conservative upper bound"}`. No response has a bare `*_usd` number (`tests/test_contract.py` checks this). Spend is always `measured`.
- **Every response has `source`**: `"store"` or `"fixture"`. The dashboard shows a red "fixture data" badge on any panel still reading fixture data. Ticket 15 is done when `/api/health` shows `store` for every endpoint. (Since ticket 15, every endpoint serves the store; the drafts endpoints fall back to fixtures only while the store has no Drafts at all, and `DWIGHT_FORCE_FIXTURES=1` still forces fixtures.)
- List responses are wrapped: `{"source": ..., "items": [...]}`.
- **Demo pricing.** `DWIGHT_PRICE_MULTIPLIER` (default `1`) multiplies every served dollar figure, in `serving.money()` (fixture bodies too). Percentages, tokens and counts are never scaled. `/api/health` reports it as `price_multiplier`, and the dashboard header shows a "Demo pricing ×N" badge whenever it isn't 1. `data/prices.yaml` and the store always hold real list prices.

## Endpoints

| Endpoint name (fixture file) | Method + path | Response model | Owner | Serves now |
|---|---|---|---|---|
| `overview` | `GET /api/overview` | `Overview` | 01 / 05 / 07 | **store** |
| `closing_numbers` | `GET /api/closing-numbers` | `ClosingNumbers` | 17 (08, 13/16) | store |
| `initiatives` | `GET /api/initiatives` | `InitiativeList` (ranked by spend) | 06 | store |
| `initiative` | `GET /api/initiatives/{initiative_id}` | `Initiative` | 06 | store |
| `initiative_sessions` | `GET /api/initiatives/{initiative_id}/sessions` | `SessionList` | 06 | store |
| `initiative_waste` | `GET /api/initiatives/{initiative_id}/waste` | `WasteBreakdown` | 09 (reads 05's findings) | store |
| `initiative_recurring_discoveries` | `GET /api/initiatives/{initiative_id}/recurring-discoveries` | `RecurringDiscoveries` (both forms) | 10 (11 writes rows) | store |
| `initiative_recommendations` | `GET /api/initiatives/{initiative_id}/recommendations` | `RecommendationList` | 09 (+12 draft_id, 13 measured_drop) | store |
| `recommendations` | `GET /api/recommendations?target_type=team\|policy\|initiative` | `RecommendationList` | 09 (14 reads policy ones) | store |
| `initiative_drafts` | `GET /api/initiatives/{initiative_id}/drafts` | `DraftList` | 12 | store |
| `draft` | `GET /api/drafts/{draft_id}` | `Draft` | 12 | store |
| (uses `draft`) | `GET /api/drafts/{draft_id}/download` | `text/markdown` attachment | 12 | store |
| `initiative_before_after` | `GET /api/initiatives/{initiative_id}/before-after` | `BeforeAfter` (`has_runs=false` hides the panel) | 13 | store |
| `policy_options` | `GET /api/policy/options` | `PolicyOptions` (teams from org, models from Infra Profile) | 14 | store |
| `policy_render` | `POST /api/policy/render` body `PolicyRequest` | `PolicyRender` (LiteLLM YAML) | 14 | store |
| `policy_apply` | `POST /api/policy/apply` body `PolicyRequest` | `Policy` (writes a file under `out/policies/`) | 14 | store |
| `policies` | `GET /api/policies` | `PolicyList` | 14 | store |
| — | `GET /api/health` | `Health`: session count and each endpoint's source | 01 | store |
| — | `POST /v1/traces` | OTLP/HTTP **JSON** trace receiver (no protobuf) | 01 | store |

`PolicyRequest` = `{"team": str, "allowed_models": [str]}`.

## Shapes, briefly (see contract.py for every field)

- `Overview`: `period{start,end}`, `session_count`, `spend`, `measured_waste`, `estimated_saving`, `spend_by_business_function[{business_function, spend, session_count, teams[{team, spend, session_count}]}]`
- `InitiativeRow`: `initiative_id, name, business_function, session_count, spend, measured_waste, estimated_saving, top_waste_pattern, teams[{team, spend, session_count}]`
- `Initiative`: `initiative_id, name, description, business_function, session_count, spend, teams[{team, spend, session_count}]`
- `WasteBreakdown`: `measured_total, estimated_total, patterns[{pattern, amount, finding_count, session_count}]`
- `RecurringDiscoveryItem`: `recurring_discovery_id, form, resources[{resource_id, tokens}]` (common_path), `statement` (repeated_discovery), `tokens, session_count, session_share (0..1), cost, evidence[session_id]`. The wrapper also carries `initiative_session_count`, for the "32 of 40" copy.
- `Recommendation`: `recommendation_id, target_type, target_id, practice{practice_id,title}, title, body (markdown), infra_refs[], saving, draft_id?, recurring_discovery_id?, measured_drop?{token_drop_pct, spend_drop, counts}, policy_prefill?{team, allowed_models}`
- `Draft`: `draft_id, recommendation_id, initiative_id, type (initiative_doc|memory), title, filename, content (markdown), source_resource_ids[], tokens, source_tokens`
- `BeforeAfter`: `has_runs, before/after{session_count, tasks_passed, tasks_total, success_rate, total_tokens, avg_tokens, spend}, token_drop_pct, spend_drop, success_held`
- `SessionRow`: `session_id, member_id, team, business_function, agent, started_at, ended_at, summary, complexity, call_count, total_tokens, spend, waste_patterns[], experiment, task_success`
- `Health`: `ok, db_path, sessions, endpoint_sources{name: source}, price_multiplier`
- `ClosingNumbers`: `spend_analysed, measured_waste, measured_waste_real_layer, estimated_saving, draft_token_drop_pct, classifier_accuracy (0..1), classifier_eval_sessions`

Waste Pattern values: `redundant_read | cache_miss | runaway_loop | model_overkill`. Display names are in `WASTE_PATTERN_LABEL` (contract.ts).

## Changes after the freeze (additive only)

| Change | Why | Where |
|---|---|---|
| `InitiativeRow.teams` and `Initiative.teams`: `[TeamSpend]`, the Initiative's Spend split by Team, ranked by Spend (default `[]`) | Overview's "Spend by Initiative, stacked by Team" chart and the Team highlight on Initiative detail | `routes/initiatives.py`, `tests/test_demo_pricing.py` |
| `Health.price_multiplier` (default `1`) | The dashboard's "Demo pricing ×N" badge | `api/main.py`, `serving.py` |
