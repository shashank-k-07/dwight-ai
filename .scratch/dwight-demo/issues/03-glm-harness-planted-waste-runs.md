# 03: GLM agent harness with planted Waste Pattern runs

**What to build:** The real layer. A small tool-using Agent harness on GLM, with OTel on, sends its telemetry to Dwight's ingest. It runs 30–50 real tasks against a real open-source repo, including planted variants that produce each Waste Pattern and clean runs as negatives. After this, real Sessions and Calls sit in the store and show on Overview.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] The harness has read-type tools (file read, doc fetch, search) and write/run tools, and emits OTel GenAI spans with Business Function/Team/Member resource attributes
- [ ] The harness can load extra context files into the Agent's starting context (needed by 16) and can tag a run with `dwight.experiment=before|after`
- [ ] Planted variants run: Redundant Read (re-reads the same files each turn), Cache Miss (volatile timestamp at the top of the prompt), Runaway Loop (retry with no exit on a failing test), Model Overkill (flagship tier doing trivial edits)
- [ ] Clean runs are included
- [ ] Which Session carries which planted pattern is recorded in a label file the detectors never read
- [ ] All runs are ingested, and their Spend shows on Overview
- [ ] Summary stats of the real layer (call counts, token distributions, pattern rates) are written out for ticket 07 to calibrate against
