"use client";
// Panel: Initiatives ranked by where to cut first. Owner: 06. GET /api/initiatives + /api/recommendations
// Ranked by Measured Waste (hard dollars); Waste share and Spend per Session show how inefficient each
// Initiative is; the top fix is its largest Initiative Recommendation. Measured Waste and Estimated
// Saving stay separate columns and are never added together (ADR 0006).
import Link from "next/link";
import { useState } from "react";
import { Info, Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import { useChartColors } from "@/lib/chartTheme";
import { WASTE_PATTERN_LABEL, type InitiativeList, type InitiativeRow, type Recommendation, type RecommendationList } from "@/lib/contract";

const share = (r: InitiativeRow) => (r.spend.usd > 0 ? r.measured_waste.usd / r.spend.usd : 0);

export default function InitiativesTable() {
  const c = useChartColors();
  const { data, error, loading } = useApi<InitiativeList>("/api/initiatives");
  const recs = useApi<RecommendationList>("/api/recommendations");
  const [bf, setBf] = useState<string | null>(null);
  const all = data?.items ?? [];
  const functions = [...new Set(all.map((r) => r.business_function ?? "Other"))];
  const items = all
    .filter((r) => !bf || (r.business_function ?? "Other") === bf)
    .sort((a, b) => b.measured_waste.usd - a.measured_waste.usd);
  const sessions = items.reduce((n, r) => n + r.session_count, 0);
  const maxShare = Math.max(0.01, ...items.map(share));

  const topFix = new Map<string, Recommendation>();
  recs.data?.items
    .filter((r) => r.target_type === "initiative")
    .forEach((r) => {
      const cur = topFix.get(r.target_id);
      if (!cur || r.saving.usd > cur.saving.usd) topFix.set(r.target_id, r);
    });

  return (
    <Panel title={bf ? `Where to cut first · ${bf}` : "Where to cut first"} source={data?.source} loading={loading} error={error}
      info="Ranked by Measured Waste: the Spend that bought nothing. Waste share and Spend per Session show how token-inefficient each Initiative is. Top fix is its largest Recommendation.">
      {data && items.length === 0 ? (
        <p className="muted">No classified Sessions yet. Run the classify stage to attribute Spend to Initiatives.</p>
      ) : (
        <>
          {functions.length > 1 && (
            <div className="filter-chips" role="group" aria-label="Filter by Business Function">
              {[null, ...functions].map((f) => (
                <button key={f ?? "all"} type="button" aria-pressed={bf === f} className={`filter-chip${bf === f ? " on" : ""}`} onClick={() => setBf(f)}>
                  {f && <span className="swatch" style={{ background: c.bf(f) }} />}{f ?? "All"}
                </button>
              ))}
            </div>
          )}
          <table className="table cut-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Initiative</th>
                <th>Measured Waste</th>
                <th>Waste share</th>
                <th>Spend / Session</th>
                <th>Top Waste Pattern</th>
                <th>Top fix</th>
                <th>Spend</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r, i) => {
                const fix = topFix.get(r.initiative_id);
                const s = share(r);
                return (
                  <tr key={r.initiative_id}>
                    <td className="muted">{i + 1}</td>
                    <td>
                      <Link href={`/initiatives/${r.initiative_id}`}>{r.name}</Link>
                      <div className="muted small">{r.business_function ?? "—"} · {r.session_count.toLocaleString()} Sessions</div>
                    </td>
                    <td>{r.measured_waste.usd ? <Money value={r.measured_waste} /> : <span className="muted">—</span>}</td>
                    <td>
                      <span className="share-cell">
                        <span className="share-bar"><span style={{ width: `${(100 * s) / maxShare}%`, background: c.waste }} /></span>
                        {Math.round(s * 100)}%
                      </span>
                    </td>
                    <td>{r.session_count ? <Money value={{ ...r.spend, usd: r.spend.usd / r.session_count }} size="sm" /> : "—"}</td>
                    <td>{r.top_waste_pattern ? WASTE_PATTERN_LABEL[r.top_waste_pattern] : "—"}</td>
                    <td className="fix-cell">
                      {fix ? (
                        <Link href={`/initiatives/${r.initiative_id}#recommendations`} title={fix.title}>
                          <span className="fix-title">{fix.title}</span>
                          <Money value={fix.saving} size="sm" />
                        </Link>
                      ) : <span className="muted">—</span>}
                    </td>
                    <td className="muted"><Money value={r.spend} size="sm" /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {data && (
            <p className="muted small">
              {items.length} Initiatives · {sessions.toLocaleString()} Sessions{bf ? ` in ${bf}` : ""}
              <Info>Initiatives are inferred from each Session&apos;s content; raw prompts are discarded after classification.</Info>
            </p>
          )}
        </>
      )}
    </Panel>
  );
}
