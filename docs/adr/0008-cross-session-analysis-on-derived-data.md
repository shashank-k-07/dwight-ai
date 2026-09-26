# Cross-session analysis runs on Trails and Discoveries, not kept prompts

Finding Recurring Discovery means comparing many Sessions in one Initiative, which could tempt us to keep raw prompts after all. We don't. When a Session is classified, Dwight stores its Trail (resource identifiers and token counts) and its Discoveries (short, redacted statements), then discards the raw prompt as ADR 0005 requires. All cross-session analysis runs on those stored fields. When drafting a doc for an Initiative, Dwight fetches the source docs fresh from wherever they live in the Customer's tenant instead of keeping copies.

## Consequences

- Drafts are delivered as files that the Customer puts in place (a doc, or a memory/context file loaded by their Agents). Dwight doesn't host a shared memory service, since that would put it in the runtime path of every agent run and contradict ADR 0002.
- If a Discovery is worded badly when it's first extracted, it can't be re-derived later, because the prompt is gone. That makes the Discovery extraction prompt worth getting right.
