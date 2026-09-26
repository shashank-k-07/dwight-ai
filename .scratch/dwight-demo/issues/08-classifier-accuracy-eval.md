# 08: Classifier accuracy eval

**What to build:** Score the classifier against the synthetic ground truth and show the accuracy number in the app, so it can go on stage (build-spec §5). This is also the loop for improving the classifier prompt.

**Blocked by:** 06, 07

**Status:** ready-for-agent

- [ ] An eval command reports the share of Sessions placed in the right Initiative, plus a per-Initiative confusion summary
- [ ] The number is stored and served by the API for the closing-numbers strip
- [ ] At least one round of prompt improvement is run, with the before and after accuracy recorded

## Comments


**From 06 (merged):** the classifier is callable as functions in `backend/dwight/classifier/` (`model.py`: one `glm.chat_json` call per Session; `run.py`: thread pool). Classifying deletes staging, so to re-score after a prompt change, re-ingest the OTLP files and rerun the stage. Label eval runs with `classifier.model.PROMPT_VERSION`. The model sees only each Initiative's id, name and description from `org.yaml` plus the Session's team and Business Function. It always picks one of the 15 known Initiatives, so there's no "none" answer (the tracer Session lands in `k8s-upgrade`).
