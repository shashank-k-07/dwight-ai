# 17: Closing numbers strip + demo snapshot

**What to build:** The closing beat of the demo (build-spec §1 step 7): a strip showing "$X of Spend analysed, $Y Measured Waste found, Drafts cut tokens by Z%, classifier W% accurate". The store is also frozen into a snapshot the demo can be reset to, so the live run and the slides use the same numbers.

**Blocked by:** 08, 14, 16

**Status:** done (snapshot `5d07eff980ce` of `demo.sqlite`; numbers exported at demo pricing ×100; `reset-demo` restores in ~0.3 s)

- [x] The strip reads every number from the store and labels each $ as Measured or Estimated
- [x] The Z% comes from 16's Measured before/after runs, and W% from 08's eval
- [x] One command resets the app to the frozen demo snapshot
- [x] The numbers are exported to a short file for the slides, matching what the app shows
- [x] The demo flow in build-spec §1 steps 1–7 is clicked through with no fixture data, errors or unlabelled $

## Comments


**From 13 (merged):** take the token drop from `dwight.api.routes.before_after.compute(conn, initiative_id)` or `measured_drop(...)`, and use `token_drop_pct` only when `success_held` / `counts` is true. On the fixture pair it is 71.5% (124,548 → 35,460 tokens per Session), with tasks going from 5/6 to 6/6.

**From 14 (merged):** the only dollar figures on the Policy screen are Recommendation savings, shown through `<Money>`. Cut-list item 2 ("show the rendered config only") is no longer needed, because Apply works end to end.

**From 08 (merged):** the strip shows the latest `eval_runs` row by `created_at`, so run `python -m dwight.pipeline run eval_classifier score --label "classify-v3 thinking=off full store"` on the frozen store LAST. Run `eval_classifier sample` only in a scratch store: it re-ingests and re-classifies Sessions, and would replace the on-stage number with a sample number. Sample results (300 Sessions, reasoning off): classify-v2 0.920 → classify-v3 0.950 (clear 1.000, ambiguous 0.833; 0.975 re-weighted to the dataset's 15% ambiguous share).

**From 17 (done):**
- The strip is in `overview/ClosingNumbers.tsx`. Its numbers come from `GET /api/closing-numbers`: `token_drop_source()` gives the before/after runs behind the token drop, and `latest_eval()` gives the eval behind the accuracy.
- `python -m dwight.pipeline snapshot | reset-demo | export-numbers` lives in `dwight/demo.py`; see `docs/dev.md`.
  - A snapshot is in `backend/var/snapshots/demo/` (gitignored, 152 MB). Its manifest is committed at `data/demo-snapshot.json`.
  - `reset-demo` sha-checks the snapshot, copies it over `DWIGHT_DB`, rewrites the 16 Draft files into `<out dir>/drafts/`, and deletes Policy files applied during a rehearsal. It then re-checks the closing numbers against the manifest, all in about 0.3 s. It was checked into a scratch store and out dir: no warnings, and the Draft files were identical.
- Frozen from `backend/var/demo.sqlite`: 4,060 Sessions, eval `classify-v3 thinking=off full store` (0.973, run last).
  - At list prices: $580.92 Spend analysed, $95.89 Measured Waste ($0.16 on the real layer), $41.32 Estimated Saving, Drafts −75.4% tokens [Measured], classifier 97.3%.
- Demo pricing (added after 17 from demo feedback): `DWIGHT_PRICE_MULTIPLIER=100` scales every served $ in `serving.money()`.
  - `export-numbers` serves at the multiplier and says so at the top of `docs/demo-numbers.md`, along with the list-price line.
  - `snapshot`/`reset-demo` always record and compare at list prices, so the manifest is the same whatever the setting.
  - At ×100 the strip and `docs/demo-numbers.*` read: $58,092 Spend, $9,589 Measured Waste ($15.78 on the real layer), $4,132 Estimated Saving, 75.4%, 97.3%. The exported JSON equals `GET /api/closing-numbers` at ×100.
- Click-through (build-spec §1 steps 1–7): run against `preview.sqlite` at ×100 with a production build and headless Chrome.
  - Covered: Overview, Initiatives, all 15 Initiative pages, two `?team=` views, the Policy screen (reached via "Apply as Policy", prefilled), Recurring Discovery, Drafts, Before/After and the strip.
  - No fixture badges, no panel errors, and no $ outside `<Money>`/`formatMoney` (chart axis ticks are labelled by their captions). The only 404 was the favicon.
  - "Apply" on Policy was not pressed: it would write a Policy file into `var/out-demo/policies/`, which the snapshot would capture. The flow itself is unchanged from 14.
- For the live demo: start the API with `DWIGHT_DB=var/demo.sqlite DWIGHT_OUT_DIR=$PWD/var/out-demo DWIGHT_PRICE_MULTIPLIER=100` and run `reset-demo` between rehearsals. The "Implement" simulation is per browser, so press "Reset simulation" in the header too.
