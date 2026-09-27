"use client";
// Panel: fix everything, company-wide. "Implement all" applies every Initiative fix Dwight found
// (lib/simulation.ts, browser-only), and "Apply fixes" runs the simulation on the Overview totals
// (components/ApplyFixes.tsx), one row per Initiative, no Initiative saving more than its own
// Spend. Team-wide fixes are left out of "Implement all": they remove the same Model Overkill as
// the Initiatives' routing fixes. Policy fixes are applied for real on the Policy screen.
// The real totals above are untouched; everything here is labelled Simulated.
// GET /api/overview, /api/recommendations, /api/initiatives
import ApplyFixes from "@/components/ApplyFixes";
import { Info } from "@/components/Money";
import { useApi } from "@/lib/api";
import type { InitiativeList, Overview, Recommendation, RecommendationList } from "@/lib/contract";
import { useSimulation } from "@/lib/simulation";
import { initiativeHref } from "@/panels/overview/SpendByInitiative";

export default function SimulationImpact() {
  const sim = useSimulation();
  const overview = useApi<Overview>("/api/overview");
  const recs = useApi<RecommendationList>("/api/recommendations");
  const initiatives = useApi<InitiativeList>("/api/initiatives");
  const error = overview.error ?? recs.error ?? initiatives.error;
  if (error) return <section className="panel sim-panel"><p className="panel-error">Couldn&apos;t load: {error}</p></section>;
  if (!overview.data || !recs.data || !initiatives.data) return null;

  const items = recs.data.items;
  const inits = initiatives.data.items;
  const companyFixes = items.filter((r) => r.target_type === "initiative");
  const notYet = companyFixes.filter((r) => !sim.isApplied(r.recommendation_id));
  const applied = items.filter((r) => sim.isApplied(r.recommendation_id));
  const withFixes = new Set(companyFixes.map((r) => r.target_id)).size;
  const name = (iid: string) => inits.find((i) => i.initiative_id === iid)?.name ?? iid;
  const caps = Object.fromEntries(inits.map((i) => [`initiative:${i.initiative_id}`, i.spend.usd]));
  const groupBy = (r: Recommendation) =>
    r.target_type === "initiative" ? { key: `initiative:${r.target_id}`, label: name(r.target_id) } : { key: `team:${r.target_id}`, label: `Team ${r.target_id} (team-wide)` };
  const proofHref = (r: Recommendation) => `${initiativeHref(r.target_id)}#before-after`;

  return (
    <section className="panel sim-panel">
      <header className="panel-head">
        <h2>
          Fix everything Dwight found
          <Info>Implement all applies every Initiative fix in this browser (a simulation; nothing changes in your systems). Team-wide fixes are left out because they remove the same Model Overkill as the Initiatives&apos; routing fixes; Policy fixes are applied for real on the Policy screen.</Info>
        </h2>
        <div className="panel-actions">
          {notYet.length > 0 ? (
            <button type="button" className="button button-cta" onClick={() => sim.applyAll(notYet, (r) => r.target_id)}>
              Implement all ({notYet.length})
            </button>
          ) : (
            <button type="button" className="button button-quiet" onClick={() => sim.undoAll(companyFixes.map((r) => r.recommendation_id))}>
              Undo all
            </button>
          )}
        </div>
      </header>
      {applied.length === 0 ? (
        <p className="small muted">
          {companyFixes.length} fixes across {withFixes} Initiatives. Implement them all, then Apply fixes to see what the company would have spent.
        </p>
      ) : (
        <ApplyFixes scope="all" base={overview.data.spend} baseLabel="Spend" sessions={overview.data.session_count}
          recs={applied} groupBy={groupBy} caps={caps} proofHref={proofHref} />
      )}
    </section>
  );
}
