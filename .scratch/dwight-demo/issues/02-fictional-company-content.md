# 02: Fictional company content: Infra Profile, Practice Library, company-docs

**What to build:** The hand-written content Dwight reasons over and that Recommendations cite: the fictional company's Infra Profile, the Practice Library, the list of known Initiatives, and the `company-docs/` folder behind the planted *storage cost reduction* Initiative. Pure content, no pipeline code, so it can run in parallel with 01.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [x] The Infra Profile YAML covers models and tiers, gateway (LiteLLM), whether prompt caching is enabled, internal docs/MCP servers, and main repositories. It is specific enough to name in Recommendations (real-sounding server names, repo names, tier names).
- [x] The Practice Library YAML is versioned and has ~15 Practices, each with `id`, `title`, `fixes` (Waste Patterns or Recurring Discovery form), `description`, `applies_when`, `infra_requirements`. It includes at least the seven named in build-spec §4.4.
- [x] Every Waste Pattern and both Recurring Discovery forms are fixed by at least one Practice whose `infra_requirements` the Infra Profile meets
- [x] The company org is defined: ~200 Members, 4–5 Business Functions (Engineering plus at least one non-engineering), ~12 Teams, ~15 named Initiatives with descriptions, and *storage cost reduction* in Engineering
- [x] `company-docs/` holds 4 docs of 3–6K tokens each, in the company's voice, that together contain what the storage cost reduction tasks need
- [x] 1–2 facts are planted that are in no doc and can only be learned by trial and error (e.g. the migration needs `STORAGE_ENV=staging`). They are recorded in a note the classifier never reads.
- [x] The ~10 storage cost reduction task prompts are written, each needing information spread across the 4 docs, with a pass/fail check per task

## Comments

Done. Start from `data/company/README.md`, which indexes the files. Things downstream agents need to know:

- **Model names (01/09/14):** the profile's tiers are flagship `glm-5.1`, standard `glm-4.7` and economy `glm-4.5-air`, all present in `data/prices.yaml`. prices.yaml's `cheaper_tier_model.flagship` is `glm-4.5-air`. That is consistent with the profile's economy tier, but the profile also has a standard tier. The default tier is flagship, which is where the Model Overkill story comes from.
- **Practice matching (09):** the rule is exact string set membership of `infra_requirements` in `infra_profile.yaml` `capabilities` (see the practices.yaml header). `cites` lists profile `ref`s or ref prefixes such as `repo:`. Use these for `infra_refs`. `semantic-response-cache` and `vector-search-docs-index` are ineligible on purpose.
- **Resource ids:** the 4 docs are `company-docs/<doc_id>.md`. Synthetic ids are `perch:<SPACE>/<slug>` and `repo:<repo>/<path>`. `tokens: real` in org.yaml means: measure the actual file.
- **Harness (03/04/16):**
  - Copy `data/company/workspace/` fresh for each task and use the workspace root as cwd.
  - Give the Agent doc tools over `company-docs/` only.
  - Keep `bin/blobctl` executable through run tools, but ideally not readable.
  - Evaluate the checks with the DSL in the header of `storage_tasks.yaml`. A throwaway reference checker passed all 10 reference solutions and rejected perturbed answers.
- **Planted facts (04):** `STORAGE_ENV=staging`, and blobctl takes bare bucket names rather than `s3://` URIs. Eight of the 10 tasks run blobctl, and each of those hits both facts on its first call. The runbook states the stale opposite ("Always pass `--bucket` as the full `s3://` URI"). That is intentional and backs the `discoveries-back-to-docs` Practice.
- **Draft check (12):** use `draft_must_keep` in `data/ground-truth/planted_facts.yaml`. The planted facts themselves are not in any doc; they belong in the memory file, not the initiative doc. The source docs total about 22K tokens (cl100k), so the ≤25% target is about 5.5K. The demo line "18K tokens" should use the measured number.
- **Month-end freeze:** the runbook mentions a Billing month-end close freeze. No task plans or applies Billing buckets. t10 asks about `kst-invoices-archive` for analysis only.
