"use client";
// Panel: what the "Implement" simulation would do to the Overview totals. Shown only while this
// viewer has implemented something (lib/simulation.ts, browser-only). The real totals above are
// untouched; everything here is labelled Simulated and computed in code from served figures.
// GET /api/overview, /api/recommendations
import Link from "next/link";
import { Money } from "@/components/Money";
import { useApi } from "@/lib/api";
import type { InitiativeList, Overview, Recommendation, RecommendationList } from "@/lib/contract";
import { project, shareOf, useSimulation, type Projection } from "@/lib/simulation";
import { initiativeHref } from "@/panels/overview/SpendByInitiative";

/** "from $X Measured Waste + $Y Estimated Saving": the inputs, each at its own kind. */
export function SavingSources({ p }: { p: Projection }) {
  const { measured, estimated } = p.from;
  if (!measured && !estimated) return null;
  return (
    <div className="muted small">
      from {measured && <><Money value={measured} size="sm" /> of Waste</>}
      {measured && estimated && " + "}
      {estimated && <><Money value={estimated} size="sm" /> of saving</>}
      {p.capped && " (capped at Spend)"}
    </div>
  );
}

export default function SimulationImpact() {
  const sim = useSimulation();
  const active = sim.count > 0;
  const overview = useApi<Overview>(active ? "/api/overview" : null);
  const recs = useApi<RecommendationList>(active ? "/api/recommendations" : null);
  const initiatives = useApi<InitiativeList>(active ? "/api/initiatives" : null);
  if (!active) return null;
  const implemented = (recs.data?.items ?? []).filter((r) => sim.isImplemented(r.recommendation_id));
  const p = overview.data ? project(overview.data.spend, implemented) : null;
  // Grouped by what each one targets: an Initiative, or a Team (implemented from an Initiative page).
  const name = (iid: string) => initiatives.data?.items.find((i) => i.initiative_id === iid)?.name ?? iid;
  const groups = new Map<string, { label: string; href: string; recs: Recommendation[] }>();
  implemented.forEach((r) => {
    const from = sim.state[r.recommendation_id]?.initiative_id || r.target_id;
    const key = `${r.target_type}:${r.target_id}`;
    const g = groups.get(key) ?? {
      label: r.target_type === "initiative" ? name(r.target_id) : `Team ${r.target_id}`,
      href: initiativeHref(from, r.target_type === "initiative" ? undefined : r.target_id), recs: [],
    };
    g.recs.push(r);
    groups.set(key, g);
  });
  return (
    <section className="panel sim-panel">
      <header className="panel-head">
        <h2>If these were implemented <span className="badge badge-sim">Simulated · Estimated</span></h2>
        <div className="panel-actions">
          <button type="button" className="button button-quiet" onClick={sim.reset}>Reset simulation</button>
        </div>
      </header>
      {overview.error || recs.error ? (
        <p className="panel-error">Couldn&apos;t load: {overview.error ?? recs.error}</p>
      ) : !p ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
          <div className="sim-flow">
            <div>
              <div className="stat-label">Spend, as measured</div>
              <Money value={p.before} size="lg" />
            </div>
            <div className="sim-arrow" aria-hidden>→</div>
            <div>
              <div className="stat-label">Projected Spend (simulated)</div>
              <Money value={p.after} size="lg" />
            </div>
            <div>
              <div className="stat-label">Projected saving</div>
              <Money value={p.saving} size="lg" />
              <div className="muted small">{shareOf(p.saving, p.before).toFixed(1)}% of Spend</div>
              <SavingSources p={p} />
            </div>
          </div>
          <ul className="small">
            {[...groups.entries()].map(([key, g]) => (
              <li key={key}>
                <Link href={g.href}>{g.label}</Link>:{" "}
                {g.recs.map((r, i) => <span key={r.recommendation_id}>{i > 0 && "; "}{r.title} (<Money value={r.saving} size="sm" />)</span>)}
              </li>
            ))}
          </ul>
          <p className="small muted">
            Nothing was changed: this is Spend minus each implemented Recommendation&apos;s own saving, for the same Sessions,
            in this browser only. Recommendations that fix the same Waste count once
            {p.overlapping ? ` (${p.overlapping} not added again)` : ""}; different ones can still overlap, so treat the
            projection as an upper bound. The only Measured result is the before/after run on the Initiative page.
          </p>
        </>
      )}
    </section>
  );
}
