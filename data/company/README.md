# Kestrel Logistics: fictional Customer content (ticket 02)

Hand-written content that Dwight reasons over. Vocabulary follows `CONTEXT.md`.

| File | What it is | Used by |
|---|---|---|
| `infra_profile.yaml` | The Infra Profile. Covers GLM tiers (flagship `glm-5.1`, standard `glm-4.7`, economy `glm-4.5-air`; names match `data/prices.yaml`), the LiteLLM gateway `kestrel-llm-gateway`, prompt caching (on), MCP servers, the Perch wiki, agents, memory and repos. It has a flat `capabilities` list, and every citable item has a stable `ref`. | 09 (Practice filtering, `infra_refs`), 14 (tiers and gateway config path), 01 (fixtures) |
| `practices.yaml` | The Practice Library, version `2026.09.2`, with 16 Practices. The matching rule is in the header: a Practice is eligible when its `fixes` matches and every `infra_requirements` string is in the profile's `capabilities`. Two Practices are deliberately ineligible for Kestrel. | 09, 12 (`consolidated-initiative-doc`, `initiative-memory-file`) |
| `org.yaml` | The company blurb, 5 Business Functions, 12 Teams, 15 Initiatives and 200 Members. Each Initiative has `usual_resources`, `repeated_discoveries` and `weight` as generator inputs. The classifier may see only the names and descriptions. | 07 (generator), 14 (Team picker), 06/08 (candidate Initiative names) |
| `storage_tasks.yaml` | The 10 storage cost reduction tasks. Each has a `prompt`, `needs_docs` and an automatable `check` (the check DSL is in the header), plus a `reference` solution. | 04 (before runs), 16 (after runs) |
| `workspace/` | The Agent's workspace, copied fresh for each task. `bin/blobctl` is a deterministic stub CLI that enforces the planted facts and writes state to `.blobctl/`. Outputs go to `out/`. | 03/04/16 (harness) |
| `../../company-docs/*.md` | The 4 source docs, 5.0–5.7K tokens each (cl100k) and about 22K in total. Their Trail `resource_id` is `company-docs/<doc_id>.md`. | 03/04 (doc tools), 12 (Drafter re-fetches them) |
| `../ground-truth/planted_facts.yaml` | The planted trial-and-error facts, how the stub enforces them, and which tasks hit them. It also has the `draft_must_keep` strings for ticket 12's check. **The classifier, Discovery extraction, cross-session analysis and Drafter must never read it.** | 04 (hit-rate check), 12 (Draft check), 17 |

The 4 docs are:

- `storage-tiering-policy`: tier to storage-class mapping, data class schedule, overrides
- `blobctl-migration-runbook`: scope, blobctl syntax, rule id convention, exception codes
- `storage-cost-dashboard`: prices, steady-state savings method, bucket inventory
- `storage-service-ownership`: teams, handles, approvers, service tiers, readers, bucket owners

Each task needs facts from all four.

Harness notes:

- Run tool commands with the workspace root as the cwd.
- Don't show the Agent anything under `data/`.
- Don't let the file-read tool open `bin/blobctl`. If the Agent reads the source it can shortcut the trial and error, although the accepted environment value is stored only as a hash.
