# 11: Repeated Discoveries

**What to build:** The repeated-Discovery half of cross-session analysis (build-spec §4.6.2). The Discoveries in each Initiative are clustered by meaning (embeddings, then a GLM pass to merge and name each cluster). A cluster reached separately in ≥ 5 Sessions (or ≥ 20%) becomes a RecurringDiscovery of form `repeated_discovery`, with Measured `spend_usd`. Its records use the shape the Recurring Discovery panel (10) already renders from fixtures.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Runs only on stored Discoveries, never on prompt content (ADR 0008)
- [ ] Clusters are merged and named by GLM into one actionable statement each
- [ ] Thresholds are configurable (default ≥ 5 Sessions or ≥ 20%)
- [ ] `spend_usd` is the spend in each Session from its start up to the Call where the Discovery was established (`call_seq`), summed across Sessions. Labelled Measured.
- [ ] On fixture data, the planted env-var fact comes out as one repeated Discovery, and one-off Discoveries don't
- [ ] The API output matches the frozen contract, so the panel needs no changes
