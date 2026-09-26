# 10: Common paths → Recurring Discovery panel

**What to build:** The common-path half of cross-session analysis (build-spec §4.6.1) and the Recurring Discovery panel on Initiative detail. For each Initiative, code computes the share of Sessions whose Trail contains each resource. Resources in ≥ 60% of Sessions form the common path, with Measured `spend_usd`. The panel renders both RecurringDiscovery forms: "32 of 40 Sessions read these 4 docs" and "found separately in 14 Sessions". The second form uses fixture data until 11 lands.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Runs only on stored Trails, never on prompt content (ADR 0008)
- [ ] The share threshold is configurable, default 60%. Single resources only (itemsets are cut).
- [ ] `spend_usd` is the sum, over Sessions, of the common-path resources' tokens × the input rate each Call actually paid (the same rule as Redundant Read). Labelled Measured.
- [ ] Writes RecurringDiscovery records of form `common_path`, with session count, share and evidence Session IDs
- [ ] The panel shows both forms with counts and labelled $. The repeated-Discovery $ is labelled as a conservative upper bound.
- [ ] Unit test on fixture Trails
