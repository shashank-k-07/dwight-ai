"use client";
// Panel: Waste by Business Function, as small multiples. Owner: 06. GET /api/initiatives + /api/recommendations
// One card per Business Function, each on its OWN scale, so a large Function (Engineering) doesn't
// crowd out the others' best opportunities. Bars = Measured Waste per Initiative; Estimated Saving
// (Model Overkill) is shown beside it, never added to it (ADR 0006). Plain HTML: every figure is text.
import Link from "next/link";
import { Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import { shade, useChartColors } from "@/lib/chartTheme";
import type { InitiativeList, InitiativeRow, Money as MoneyT, Recommendation, RecommendationList } from "@/lib/contract";

const sum = (rows: InitiativeRow[], k: "spend" | "measured_waste" | "estimated_saving"): MoneyT => ({
  ...rows[0][k], usd: rows.reduce((n, r) => n + r[k].usd, 0),
});
const pct = (part: number, whole: number) => (whole > 0 ? Math.round((100 * part) / whole) : 0);

export default function WasteByFunction() {
  const c = useChartColors();
  const { data, error, loading } = useApi<InitiativeList>("/api/initiatives");
  const recs = useApi<RecommendationList>("/api/recommendations");
  const items = data?.items ?? [];

  const byBf = new Map<string, InitiativeRow[]>();
  items.forEach((r) => {
    const bf = r.business_function ?? "Other";
    byBf.set(bf, [...(byBf.get(bf) ?? []), r]);
  });
  const groups = [...byBf.entries()]
    .map(([bf, rows]) => ({ bf, rows: [...rows].sort((a, b) => b.measured_waste.usd - a.measured_waste.usd) }))
    .sort((a, b) => sum(b.rows, "measured_waste").usd - sum(a.rows, "measured_waste").usd);

  const fixFor = (rows: InitiativeRow[]): { rec: Recommendation; row: InitiativeRow } | null => {
    let best: { rec: Recommendation; row: InitiativeRow } | null = null;
    recs.data?.items.forEach((rec) => {
      const row = rows.find((r) => rec.target_type === "initiative" && r.initiative_id === rec.target_id);
      if (row && (!best || rec.saving.usd > best.rec.saving.usd)) best = { rec, row };
    });
    return best;
  };

  return (
    <Panel title="Waste by Business Function" source={data?.source} loading={loading} error={error}
      info="One card per Business Function, each on its own scale, so every Function's biggest opportunities show. Bars = Measured Waste per Initiative. Estimated Saving (Model Overkill) is shown separately and never added to it.">
      {items.length === 0 ? (
        <p className="muted">No classified Sessions yet.</p>
      ) : (
        <div className="bf-cards">
          {groups.map(({ bf, rows }) => {
            const spend = sum(rows, "spend");
            const waste = sum(rows, "measured_waste");
            const est = sum(rows, "estimated_saving");
            const max = Math.max(0.0001, ...rows.map((r) => r.measured_waste.usd));
            const fix = fixFor(rows);
            return (
              <section key={bf} className="bf-card" style={{ borderTopColor: c.bf(bf) }}>
                <header>
                  <h3><span className="swatch" style={{ background: c.bf(bf) }} />{bf}</h3>
                  <div className="bf-card-stats">
                    <div><div className="stat-label">Measured Waste</div><Money value={waste} size="lg" /></div>
                    <div><div className="stat-label">of its Spend</div><span className="bf-card-pct">{pct(waste.usd, spend.usd)}%</span></div>
                    <div><div className="stat-label">Estimated Saving</div><Money value={est} /></div>
                  </div>
                </header>
                <ol className="bf-card-rows">
                  {rows.map((r, i) => (
                    <li key={r.initiative_id}>
                      <Link href={`/initiatives/${r.initiative_id}`} className="bf-card-name" title={r.name}>{r.name}</Link>
                      <span className="bf-card-track">
                        <span style={{
                          width: `${Math.max((100 * r.measured_waste.usd) / max, r.measured_waste.usd > 0 ? 2 : 0)}%`,
                          background: shade(c.bf(bf), rows.length > 1 ? 0.8 - (0.6 * i) / (rows.length - 1) : 0.6, c.surface),
                        }} />
                      </span>
                      <span className="bf-card-val">
                        {r.measured_waste.usd > 0 ? <Money value={r.measured_waste} size="sm" /> : <span className="muted">—</span>}
                        <span className="muted small"> {pct(r.measured_waste.usd, r.spend.usd)}%</span>
                      </span>
                    </li>
                  ))}
                </ol>
                {fix && (
                  <Link className="bf-card-fix" href={`/initiatives/${fix.row.initiative_id}#recommendations`}>
                    <span className="stat-label">Biggest fix</span>
                    <span className="bf-card-fix-title">{fix.rec.title}</span>
                    <span className="small">{fix.row.name} · <Money value={fix.rec.saving} size="sm" /></span>
                  </Link>
                )}
              </section>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
