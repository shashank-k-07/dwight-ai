# 02: Fictional company content: Infra Profile, Practice Library, company-docs

**What to build:** The hand-written content Dwight reasons over and that Recommendations cite: the fictional company's Infra Profile, the Practice Library, the list of known Initiatives, and the `company-docs/` folder behind the planted *storage cost reduction* Initiative. Pure content, no pipeline code, so it can run in parallel with 01.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] The Infra Profile YAML covers models and tiers, gateway (LiteLLM), whether prompt caching is enabled, internal docs/MCP servers, and main repositories. It is specific enough to name in Recommendations (real-sounding server names, repo names, tier names).
- [ ] The Practice Library YAML is versioned and has ~15 Practices, each with `id`, `title`, `fixes` (Waste Patterns or Recurring Discovery form), `description`, `applies_when`, `infra_requirements`. It includes at least the seven named in build-spec §4.4.
- [ ] Every Waste Pattern and both Recurring Discovery forms are fixed by at least one Practice whose `infra_requirements` the Infra Profile meets
- [ ] The company org is defined: ~200 Members, 4–5 Business Functions (Engineering plus at least one non-engineering), ~12 Teams, ~15 named Initiatives with descriptions, and *storage cost reduction* in Engineering
- [ ] `company-docs/` holds 4 docs of 3–6K tokens each, in the company's voice, that together contain what the storage cost reduction tasks need
- [ ] 1–2 facts are planted that are in no doc and can only be learned by trial and error (e.g. the migration needs `STORAGE_ENV=staging`). They are recorded in a note the classifier never reads.
- [ ] The ~10 storage cost reduction task prompts are written, each needing information spread across the 4 docs, with a pass/fail check per task
