"use client";
// Panel: Waste by Business Function, as small multiples of ECharts bars. Owner: 06.
// GET /api/initiatives + /api/recommendations
// One mini chart per Business Function, each on its OWN scale, so a large Function (Engineering)
// doesn't crowd out the others' best opportunities. Bar = an Initiative's Measured Waste, in shades of
// the Function's colour (darker = larger). Waste share, Estimated Saving (never added to Measured
// Waste, ADR 0006) and the top fix are in the tooltip. Click a bar to open the Initiative.
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { EChart } from "@/components/EChart";
import { formatMoney, Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import { shade, tooltipStyle, useChartColors, type ChartColors } from "@/lib/chartTheme";
import type { InitiativeList, InitiativeRow, Money as MoneyT, Recommendation, RecommendationList } from "@/lib/contract";
import { initiativeHref } from "@/panels/overview/SpendByInitiative";

const total = (rows: InitiativeRow[], k: "spend" | "measured_waste"): MoneyT => ({
  ...rows[0][k], usd: rows.reduce((n, r) => n + r[k].usd, 0),
});
const pct = (part: number, whole: number) => (whole > 0 ? Math.round((100 * part) / whole) : 0);
const esc = (s: string) => s.replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]!);

function FunctionChart({ bf, rows, fixes, c }: {
  bf: string; rows: InitiativeRow[]; fixes: Map<string, Recommendation>; c: ChartColors;
}) {
  const router = useRouter();
  const option = useMemo(() => ({
    tooltip: {
      ...tooltipStyle(c),
      formatter: (p: { dataIndex: number }) => {
        const r = rows[p.dataIndex];
        const fix = fixes.get(r.initiative_id);
        return `<b>${esc(r.name)}</b><br/>Measured Waste ${formatMoney(r.measured_waste)} · ${pct(r.measured_waste.usd, r.spend.usd)}% of its Spend`
          + `<br/>Estimated Saving ${formatMoney(r.estimated_saving)}`
          + (fix ? `<br/><span style="opacity:.75">Top fix:</span> ${esc(fix.title)} (${formatMoney(fix.saving)})` : "");
      },
    },
    grid: { left: 4, right: 64, top: 4, bottom: 4, containLabel: true },
    xAxis: { type: "value", show: false, max: (v: { max: number }) => v.max * 1.02 },
    yAxis: {
      type: "category", inverse: true, data: rows.map((r) => r.name),
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: c.text, fontSize: 12, width: 170, overflow: "truncate" },
    },
    series: [{
      type: "bar", barWidth: 14, barMinHeight: 2, cursor: "pointer",
      data: rows.map((r, i) => ({
        value: r.measured_waste.usd, // geometry only; text goes through formatMoney
        itemStyle: {
          color: shade(c.bf(bf), rows.length > 1 ? 0.85 - (0.7 * i) / (rows.length - 1) : 0.6, c.surface),
          borderRadius: [0, 4, 4, 0],
        },
      })),
      label: {
        show: true, position: "right", color: c.textMuted, fontSize: 11,
        formatter: (p: { dataIndex: number }) => formatMoney(rows[p.dataIndex].measured_waste),
      },
    }],
  }), [bf, rows, fixes, c]);

  return (
    <EChart option={option} height={12 + rows.length * 30} ariaLabel={`Measured Waste by Initiative in ${bf}`}
      onClick={(p) => { const r = rows[p.dataIndex ?? -1]; if (r) router.push(initiativeHref(r.initiative_id)); }} />
  );
}

export default function WasteByFunction() {
  const c = useChartColors();
  const { data, error, loading } = useApi<InitiativeList>("/api/initiatives");
  const recs = useApi<RecommendationList>("/api/recommendations");

  const groups = useMemo(() => {
    const byBf = new Map<string, InitiativeRow[]>();
    (data?.items ?? []).forEach((r) => {
      const bf = r.business_function ?? "Other";
      byBf.set(bf, [...(byBf.get(bf) ?? []), r]);
    });
    return [...byBf.entries()]
      .map(([bf, rows]) => ({ bf, rows: [...rows].sort((a, b) => b.measured_waste.usd - a.measured_waste.usd) }))
      .sort((a, b) => total(b.rows, "measured_waste").usd - total(a.rows, "measured_waste").usd);
  }, [data]);

  const fixes = useMemo(() => {
    const m = new Map<string, Recommendation>();
    recs.data?.items.filter((r) => r.target_type === "initiative").forEach((r) => {
      const cur = m.get(r.target_id);
      if (!cur || r.saving.usd > cur.saving.usd) m.set(r.target_id, r);
    });
    return m;
  }, [recs.data]);

  return (
    <Panel title="Waste by Business Function" source={data?.source} loading={loading} error={error}
      info="Each Business Function on its own scale, so every Function's biggest opportunities show. Bars = Measured Waste per Initiative. Hover for Waste share, Estimated Saving and the top fix; click to open.">
      {groups.length === 0 ? (
        <p className="muted">No classified Sessions yet.</p>
      ) : (
        <div className="bf-cards">
          {groups.map(({ bf, rows }) => {
            const waste = total(rows, "measured_waste");
            const spend = total(rows, "spend");
            return (
              <section key={bf} className={`bf-card${rows.length > 4 ? " bf-card-wide" : ""}`}>
                <header className="bf-card-head">
                  <span className="swatch" style={{ background: c.bf(bf) }} />
                  <strong>{bf}</strong>
                  <span className="bf-card-total"><Money value={waste} /> <span className="muted small">{pct(waste.usd, spend.usd)}% of Spend</span></span>
                </header>
                <FunctionChart bf={bf} rows={rows} fixes={fixes} c={c} />
              </section>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
