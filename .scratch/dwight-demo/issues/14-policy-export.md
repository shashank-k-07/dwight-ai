# 14: Policy screen + gateway config export

**What to build:** The Policy screen. The Admin picks a Team, chooses allowed models from the Infra Profile's tiers, and sees the rendered LiteLLM team allowlist YAML. "Apply" writes the config file. The customer's gateway enforces it, not Dwight (ADR 0002). Team-targeted Recommendations of type `policy` can open this screen prefilled.

**Blocked by:** 01, 02

**Status:** done

- [x] The Team picker and model choices come from the org and the Infra Profile
- [x] The rendered config is valid LiteLLM team model-allowlist YAML
- [x] "Apply" writes the file to a configured output folder and stores the Policy record
- [x] A policy Recommendation links here with its Team and suggested models prefilled

## Comments

**Done (ticket 14).** All four policy endpoints serve `store` (`/api/health`). Logic lives in `backend/dwight/policy_export.py`; `api/routes/policy.py` is a thin wrapper. Tests: `backend/tests/test_policy.py`.

- **Options:** Teams from `org.yaml` (display names + Business Function), models from the Infra Profile tiers only: `glm-5.1` flagship, `glm-4.7` standard, `glm-4.5-air` economy. The fixture's 11-model list is gone in store mode.
- **Request validation:** `team` accepts the display name or the org id, case-insensitively ("Routing", "routing", "data-infra"). Responses always use the display name. An unknown Team or model returns **400** with a readable `detail`. Models are deduped and sorted by tier (flagship first).
- **Rendered YAML:** `teams: [{team_alias: <org team id>, models: [...], metadata: {managed_by: dwight, team, business_function}}]`, with a comment header naming ADR 0002 and the target file `kestrel/llm-gateway-config:litellm/teams/<id>.yaml`. `models` lists each model name **and** its gateway alias (`glm-4.7`, `kestrel-standard`), so the allowlist holds however Agents call the model. These are LiteLLM team-object fields (`/team/new`, `/team/update`).
- **Empty allowlist:** in LiteLLM, an empty team `models` list means every model is allowed. So render with no models returns a config that is only comments (it parses as `null`), and apply returns 400. The Apply button is disabled in that case.
- **Apply:** writes `config.POLICY_OUT_DIR/<team id>.yaml` (default `out/policies/`, override with `DWIGHT_OUT_DIR`), replacing that Team's previous file. It also inserts a new `policies` row each time (`pol-<10 hex>`), so re-applies build up a history. `output_path` is repo-relative when inside the repo, otherwise absolute. `/api/policies` lists newest first.
- **Prefill (for 09):** the Policy screen reads `/api/recommendations?target_type=policy` and lists every Recommendation that has `policy_prefill`, with its `<Money>` saving and a "Prefill" button. The URL form `/policy?team=<Team>&models=a,b[&recommendation=<id>]` also works. Without `recommendation=`, the screen finds the Recommendation that matches the team and models and shows it. Models in a prefill that aren't in the Infra Profile are listed as left out. **09:** build `policy_prefill` with `policy_export.prefill(target_id, suggested_models)`. It resolves the Team name, drops unknown models, and returns `None` when nothing is usable. The client filters on `policy_prefill` because the fixture ignores the `target_type` filter, so 09 should apply the filter in store mode.
- **15:** nothing left to switch for policy. The seeded `pol-001` row (from `derived.json`) shows up in "Applied Policies". Demo tip: set `DWIGHT_OUT_DIR` if the file shouldn't land in the repo's `out/`, which is gitignored.
- **17:** the Policy screen shows no dollar figures except Recommendation savings, and those go through `<Money>`. Cut-list item 2 ("show the rendered config only") isn't needed.
- Dev note: `npm run build` (Turbopack) fails when `dashboard/node_modules` is a symlink pointing outside the worktree. `./node_modules/.bin/next build --webpack` works, and `npm run typecheck` is unaffected.
