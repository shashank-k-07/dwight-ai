# 12: Drafter + Draft viewer

**What to build:** The Drafter (build-spec §4.6.3–4) and the Draft viewer on Initiative detail. For a common path, it fetches the source docs by `resource_id` from `company-docs/` (never from stored prompts). GLM then writes a consolidated initiative doc holding only what the Sessions needed, with source links, at ≤ 25% of the common path's tokens. For repeated Discoveries, it writes one memory file per Initiative, one actionable line per cluster. Each Draft is attached to the Recommendation citing the matching Practice and priced as Estimated. The viewer renders the Draft and offers a download.

**Blocked by:** 02, 09

**Status:** ready-for-agent

- [ ] GLM gets the source docs plus the Initiative's Discoveries and Session summaries, and nothing from raw prompts
- [ ] The initiative doc is ≤ 25% of the source tokens, and a check verifies every planted fact that sits in the docs is still present
- [ ] The memory file has one instruction-style line per repeated Discovery
- [ ] Each Draft is stored with `source_resource_ids` and `tokens`, and attached to a Recommendation that cites the consolidated-initiative-doc or initiative-memory-file Practice
- [ ] Estimated Saving for the doc = (common-path tokens − Draft tokens) × Sessions per month × input rate. For memory entries = the repeated Discovery's `spend_usd` scaled to a month. Both are labelled Estimated.
- [ ] The Draft viewer renders the markdown and downloads the doc and the memory file as files
