# 08: Classifier accuracy eval

**What to build:** Score the classifier against the synthetic ground truth and show the accuracy number in the app, so it can go on stage (build-spec §5). This is also the loop for improving the classifier prompt.

**Blocked by:** 06, 07

**Status:** ready-for-agent

- [ ] An eval command reports the share of Sessions placed in the right Initiative, plus a per-Initiative confusion summary
- [ ] The number is stored and served by the API for the closing-numbers strip
- [ ] At least one round of prompt improvement is run, with the before and after accuracy recorded
