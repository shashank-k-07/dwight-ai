# 06: Initiative classifier → Initiatives table

**What to build:** The GLM classification stage. For each Session it reads the prompt content and writes a redacted one-line `summary`, an Initiative (picked from the ~15 known Initiative names, per cut list #6), `complexity`, and `discoveries[]`. Code builds the Trail from read-type tool calls. Raw prompt text is then discarded. The Initiatives screen shows a table ranked by Spend with Session count, the Waste split into Measured and Estimated, and top Waste Pattern.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] The GLM prompt returns structured JSON: summary, Initiative, complexity (low/med/high), and Discoveries (each one redacted, generalisable sentence plus the `call_seq` where it was established)
- [ ] The Discovery prompt catches the fixture's trial-and-error env-var fact and doesn't invent Discoveries for Sessions with no failed attempt or late answer
- [ ] The Trail is built by code: resource IDs from read-type tool calls, normalised (paths, doc IDs, URLs), with result tokens and `call_seq`
- [ ] Raw prompt content is deleted after classification, and the code says so (ADRs 0005, 0008)
- [ ] Initiative records carry `session_count` and `spend_usd`
- [ ] The Initiatives table is ranked by Spend and shows Session count, the Measured/Estimated Waste split (labelled) and top Waste Pattern. It reads WasteFindings from the store (fixture findings until 05 lands) and links to Initiative detail.
- [ ] The classifier never reads the ground-truth file or the planted-pattern label file
