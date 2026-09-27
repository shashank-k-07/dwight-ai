# 09: Recommendation engine → Initiative detail: Waste breakdown + Recommendations

**What to build:** The Recommendation stage (build-spec §4.4) and the first two Initiative detail panels. For each Initiative, and for each Team as Policy candidates, code collects WasteFindings by pattern and filters the Practice Library to Practices whose `fixes` match and whose `infra_requirements` the Infra Profile meets. GLM then picks and writes tailored Recommendations as structured JSON, and code attaches `usd` and `kind`. Initiative detail shows the Waste Pattern breakdown and the Recommendations.

**Blocked by:** 01, 02

**Status:** done

- [x] Each Recommendation cites a real `practice_id` and at least one real `infra_refs` item from the Infra Profile. Output that fails this check is rejected and retried.
- [x] The GLM output contains no dollar figures. `usd` and `kind` come from the findings in code (ADRs 0006, 0007).
- [x] The engine accepts RecurringDiscovery records too, so the consolidated-initiative-doc and initiative-memory-file Practices can be recommended (the Draft is attached in 12)
- [x] On fixture data, the top 3 Initiatives each get at least 2 Recommendations
- [x] The Initiative detail Waste Pattern breakdown panel shows $ per pattern with its label
- [x] The Recommendations panel shows title, body, the cited Practice, infra refs, and $ with its label

## Comments

**Done (ticket 09).** Stage `backend/dwight/pipeline/stages/recommend.py`, engine in `backend/dwight/recommend/` (`library.py` = Practice Library + Infra Profile lookups, `engine.py` = targets, prompt, validation, pricing). `/initiatives/{id}/waste`, `/initiatives/{id}/recommendations` and `/recommendations` now serve from the store.

How it works:
- **Targets:** every Initiative with WasteFindings or RecurringDiscoveries, plus every Team with Model Overkill findings (the Policy candidates). A **Group** is one Waste Pattern's findings (`key` = pattern) or one RecurringDiscovery (`key` = `rd:<id>`). Candidate Practices per Group follow the practices.yaml rule (`fixes` match plus exact `infra_requirements` ⊆ `capabilities`).
- **GLM never sees a dollar figure.** The prompt carries token, Session and finding counts only, and `$` amounts in detector `detail` text are redacted. Output is rejected and retried (up to 3 attempts, with the errors fed back) when any of these hold: the practice_id isn't a candidate for its Group, a practice is used twice, an infra_ref isn't a real Infra Profile `ref`, there are no refs, the text contains a currency amount (`engine.MONEY_RE`), a Group is uncovered, a REQUIRED practice is missing, or the count is out of range. If it still fails, code writes a plain fallback from the Practice's own text, citing real refs. The stage summary counts rejections and fallbacks.
- **Pricing is code only:** `usd`/`kind` = the Group's total from the store. Pattern Groups carry their findings' kind; RecurringDiscovery Groups carry the RD's `spend_usd` as **estimated** (placeholder until 12 re-prices it). Recommendations for the same Group share its figure; the API adds the note "same Waste as above, not additive" to the second one. Repeated-Discovery ones get "conservative upper bound".
- **Count:** at least 2 per Initiative (1 per Team), at most one per Group plus one alternative. On fixture data (live, DeepSeek-V4.1-Flash via Sciforium), the 4 Initiatives with Waste get 3/2/3/2 Recommendations, plus 1 Routing Policy: 12 total, 0 rejected, 0 fallbacks, ~6s.
- **`infra_refs` are Infra Profile `ref` ids** (`mcp:perch-docs-mcp`, `tier:economy`, `repo:kestrel/blobctl`), not display names like the API fixtures use. The panel shows them as `kind name` chips.
- **Ids are stable:** `r-<slug(target_id)>-<practice_id>`, e.g. `r-storage-cost-reduction-consolidated-initiative-doc`. Idempotent: each target's rows are deleted and re-inserted, and a full run drops stale targets.

Notes for later tickets:
- **12 (Drafter):** find the Recommendation to attach to with `target_type='initiative' AND target_id=<iid> AND recurring_discovery_id=<rd id> AND practice_id IN ('consolidated-initiative-doc','initiative-memory-file')` (constants in `library.DRAFT_PRACTICE`). Every RD with an eligible draftable Practice gets exactly one (it's REQUIRED). UPDATE its `draft_id`, `usd` (your §4.6.4 Estimated Saving; mine is just the RD's measured `spend_usd`) and `kind='estimated'`, and write `drafts.recommendation_id` = that id. If recommend re-runs, it keeps `draft_id`/`usd`/`kind` on any row that already has a `draft_id`. It also re-links from `drafts.recommendation_id` when the id matches. The panel links "View Draft" to `#draft-<draft_id>`, so give the Draft element that `id`.
- **13:** the recommendations endpoint calls `before_after.attach_measured_drops`. The panel hides the spend_drop figure when `counts` is false.
- **14:** Team targets write `target_type='policy'` for `team-model-allowlist-policy`, with `suggested_models` = `library.policy_models()` (non-flagship Infra Profile tiers: glm-4.7, glm-4.5-air). `policy_prefill` comes from `policy_export.prefill()`. `/api/recommendations?target_type=` now filters in store mode. "Apply as Policy" links to `/policy?team=..&models=..&recommendation=<id>`. Policy Recommendations target Teams only; they don't appear on Initiative detail.
- **15:** run `recommend` after detect/common_paths/repeated_discoveries (ORDER 60) and before draft (70). Flags: `--initiative ID..`, `--no-teams`, `--no-glm` (fallback text only, offline), `--tier`, `--workers` (default 4). The real layer has no Model Overkill, so its only Policy Recommendations come from synthetic Teams. Session `agent` values that aren't in the Infra Profile (the harness is `dwight-harness`) fall back to the Business Function's agents (`agent:kestrel-devagent` for Engineering) as ref hints.

