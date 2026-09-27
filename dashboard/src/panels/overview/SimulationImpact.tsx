"use client";
// Panel: the fixes this viewer applied with "Implement", across every Initiative and Team, and
// "Apply fixes" to run the simulation on the Overview totals (components/ApplyFixes.tsx).
// Shown only while something is applied (lib/simulation.ts, browser-only). The real totals above
// are untouched; everything here is labelled Simulated and computed in code from served figures.
// GET /api/overview, /api/recommendations, /api/initiatives
import ApplyFixes from "@/components/ApplyFixes";
import { useApi } from "@/lib/api";
import type { InitiativeList, Overview, Recommendation, RecommendationList } from "@/lib/contract";
import { useSimulation } from "@/lib/simulation";
import { initiativeHref } from "@/panels/overview/SpendByInitiative";

export default function SimulationImpact() {
  const sim = useSimulation();
  const active = sim.count > 0;
  const overview = useApi<Overview>(active ? "/api/overview" : null);
  const recs = useApi<RecommendationList>(active ? "/api/recommendations" : null);
  const initiatives = useApi<InitiativeList>(active ? "/api/initiatives" : null);
  if (!active) return null;
  const applied = (recs.data?.items ?? []).filter((r) => sim.isApplied(r.recommendation_id));
  const name = (iid: string) => initiatives.data?.items.find((i) => i.initiative_id === iid)?.name ?? iid;
  const labelFor = (r: Recommendation) => (r.target_type === "initiative" ? name(r.target_id) : `Team ${r.target_id}`);
  const proofHref = (r: Recommendation) =>
    `${initiativeHref(sim.state.applied[r.recommendation_id]?.initiative_id || r.target_id)}#before-after`;
  const error = overview.error ?? recs.error;
  return (
    <section className="panel sim-panel">
      <header className="panel-head">
        <h2>Applied fixes, across the company</h2>
      </header>
      {error ? (
        <p className="panel-error">Couldn&apos;t load: {error}</p>
      ) : !overview.data || !recs.data ? (
        <p className="muted">Loading…</p>
      ) : (
        <ApplyFixes scope="all" base={overview.data.spend} baseLabel="Spend" sessions={overview.data.session_count}
          recs={applied} labelFor={labelFor} proofHref={proofHref} />
      )}
    </section>
  );
}
