# 14: Policy screen + gateway config export

**What to build:** The Policy screen. The Admin picks a Team, chooses allowed models from the Infra Profile's tiers, and sees the rendered LiteLLM team allowlist YAML. "Apply" writes the config file. The customer's gateway enforces it, not Dwight (ADR 0002). Team-targeted Recommendations of type `policy` can open this screen prefilled.

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] The Team picker and model choices come from the org and the Infra Profile
- [ ] The rendered config is valid LiteLLM team model-allowlist YAML
- [ ] "Apply" writes the file to a configured output folder and stores the Policy record
- [ ] A policy Recommendation links here with its Team and suggested models prefilled
