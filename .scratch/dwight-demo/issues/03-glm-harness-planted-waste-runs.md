# 03: GLM agent harness with planted Waste Pattern runs

**What to build:** The real layer. A small tool-using Agent harness on GLM, with OTel on, sends its telemetry to Dwight's ingest. It runs 30–50 real tasks against a real open-source repo, including planted variants that produce each Waste Pattern and clean runs as negatives. After this, real Sessions and Calls sit in the store and show on Overview.

**Note from 02:** the harness's file-read tool must not be able to open `data/company/workspace/bin/blobctl`, because reading its source would skip the trial and error that produces the planted Discovery. Read the `## Comments` section of ticket 02 before starting.

**Blocked by:** 01

**Status:** ready-for-agent

**Decision (2026-09-26, user):** the real layer runs on Sciforium's two cheap Flash models (DeepSeek-V4.1-Flash, and GLM 5.3 Flash once its model string is in `DWIGHT_GLM_MODEL_POOL`). There is no flagship model, so **don't plant Model Overkill in the real runs**, and never record a real run under a fake flagship model name. Model Overkill shows up in the synthetic layer (07) only. Pick one model per Session with `glm.model_for()` and pass it on every Call, so each Session is one model and `gen_ai.request.model` records the model actually used (the deployment path is fine: `pricing.normalise_model` reduces it to `deepseek-v4.1-flash` / `glm-5.3-flash`, both priced in `data/prices.yaml` at tier `light`).

- [ ] The harness has read-type tools (file read, doc fetch, search) and write/run tools, and emits OTel GenAI spans with Business Function/Team/Member resource attributes
- [ ] The harness can load extra context files into the Agent's starting context (needed by 16) and can tag a run with `dwight.experiment=before|after`
- [ ] Planted variants run: Redundant Read (re-reads the same files each turn), Cache Miss (volatile timestamp at the top of the prompt), Runaway Loop (retry with no exit on a failing test). **No Model Overkill variant** (see the decision note)
- [ ] Clean runs are included
- [ ] Which Session carries which planted pattern is recorded in a label file the detectors never read
- [ ] All runs are ingested, and their Spend shows on Overview
- [ ] Summary stats of the real layer (call counts, token distributions, pattern rates) are written out for ticket 07 to calibrate against
