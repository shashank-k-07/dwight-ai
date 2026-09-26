# 09: Recommendation engine → Initiative detail: Waste breakdown + Recommendations

**What to build:** The Recommendation stage (build-spec §4.4) and the first two Initiative detail panels. For each Initiative, and for each Team as Policy candidates, code collects WasteFindings by pattern and filters the Practice Library to Practices whose `fixes` match and whose `infra_requirements` the Infra Profile meets. GLM then picks and writes tailored Recommendations as structured JSON, and code attaches `usd` and `kind`. Initiative detail shows the Waste Pattern breakdown and the Recommendations.

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] Each Recommendation cites a real `practice_id` and at least one real `infra_refs` item from the Infra Profile. Output that fails this check is rejected and retried.
- [ ] The GLM output contains no dollar figures. `usd` and `kind` come from the findings in code (ADRs 0006, 0007).
- [ ] The engine accepts RecurringDiscovery records too, so the consolidated-initiative-doc and initiative-memory-file Practices can be recommended (the Draft is attached in 12)
- [ ] On fixture data, the top 3 Initiatives each get at least 2 Recommendations
- [ ] The Initiative detail Waste Pattern breakdown panel shows $ per pattern with its label
- [ ] The Recommendations panel shows title, body, the cited Practice, infra refs, and $ with its label
