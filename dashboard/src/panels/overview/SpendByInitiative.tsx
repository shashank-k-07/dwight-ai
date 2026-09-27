"use client";
// Panel: Spend by Initiative, stacked by Team (demo feedback: under the Business Function chart). ECharts.
// GET /api/initiatives (teams: additive contract field) + /api/overview (for Team colours).
// A Team keeps the colour it has in "Spend by Business Function" (its position within its
// Business Function); every Initiative sits in one Business Function, so segments in a bar never
// share a colour. Click an Initiative (name or bar) to open it; click a Team segment to open it
// with that Team highlighted. The table below is the accessible/exact view, with the same links.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { EChart } from "@/components/EChart";
import { formatMoney, Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import { tint, tooltipStyle, useChartColors } from "@/lib/chartTheme";
import type { InitiativeList, Overview } from "@/lib/contract";

export const initiativeHref = (id: string, team?: string) =>
  `/initiatives/${encodeURIComponent(id)}${team ? `?team=${encodeURIComponent(team)}` : ""}`;

// Axis ticks only (Measured by default, per the header legend): $2.5K, $10K, $40, $0.50.
const axisUsd = (v: number) =>
  v >= 1000 ? `$${+(v / 1000).toFixed(v % 1000 && v < 10000 ? 1 : 0)}K` : v >= 1 || v === 0 ? `$${+v.toFixed(v < 10 ? 1 : 0)}` : `$${v.toPrecision(2)}`;

// A Team is its Business Function's hue, lighter the further down that Function's Team order it sits.
const TEAM_TINTS = [0, 0.3, 0.5, 0.65, 0.75];

export default function SpendByInitiative() {
  const router = useRouter();
  const c = useChartColors();
  const { data, error, loading } = useApi<InitiativeList>("/api/initiatives");
  const overview = useApi<Overview>("/api/overview");
  const items = useMemo(() => data?.items ?? [], [data]);

  // Team -> position within its Business Function and the Function, from the overview's order.
  const teamInfo = useMemo(() => {
    const m = new Map<string, { i: number; bf: string }>();
    overview.data?.spend_by_business_function.forEach((bf) =>
      bf.teams.forEach((t, i) => m.set(t.team, { i, bf: bf.business_function })));
    return m;
  }, [overview.data]);
  const colour = (team: string) => {
    const t = teamInfo.get(team);
    return tint(c.bf(t?.bf), TEAM_TINTS[Math.min(t?.i ?? 0, TEAM_TINTS.length - 1)], c.surface);
  };

  const teams = useMemo(() => {
    const seen = new Set<string>();
    items.forEach((r) => r.teams?.forEach((t) => seen.add(t.team)));
    return [...seen].sort((x, y) => (teamInfo.get(x)?.i ?? 99) - (teamInfo.get(y)?.i ?? 99));
  }, [items, teamInfo]);
  const legend = useMemo(() => {
    const byBf = new Map<string, string[]>();
    teams.forEach((t) => {
      const bf = teamInfo.get(t)?.bf ?? "Other";
      byBf.set(bf, [...(byBf.get(bf) ?? []), t]);
    });
    return [...byBf.entries()];
  }, [teams, teamInfo]);

  const option = useMemo(() => ({
    tooltip: {
      ...tooltipStyle(c), trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: "rgba(127,127,127,.08)" } },
      formatter: (ps: { dataIndex: number }[]) => {
        const r = items[ps[0]?.dataIndex];
        if (!r) return "";
        return `<b>${r.name}</b> · ${formatMoney(r.spend)}<br/>`
          + (r.teams ?? []).map((t) => `<span style="display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px;background:${colour(t.team)}"></span>${t.team}: ${formatMoney(t.spend)} · ${t.session_count} Sessions`).join("<br/>")
          + `<br/><span style="opacity:.7">Click a Team's segment to open the Initiative for that Team</span>`;
      },
    },
    grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "value", axisLabel: { color: c.textMuted, formatter: axisUsd }, splitLine: { lineStyle: { color: c.grid } } },
    yAxis: {
      type: "category", inverse: true, triggerEvent: true, data: items.map((r) => r.name),
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: c.spend, fontSize: 12, width: 180, overflow: "truncate" },
    },
    series: teams.map((team) => ({
      name: team, type: "bar", stack: "s", barWidth: 16,
      itemStyle: { color: colour(team), borderColor: c.surface, borderWidth: 1, borderRadius: 3 },
      emphasis: { focus: "series" },
      data: items.map((r) => r.teams?.find((t) => t.team === team)?.spend.usd ?? 0), // geometry only; text goes through formatMoney
    })),
  }), [items, teams, c, teamInfo]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Panel title="Spend by Initiative" source={data?.source} loading={loading} error={error}
      info="Spend, stacked by Team (each Team in its Business Function's colour). Click an Initiative to see its Waste and Recommendations, or a Team's segment to open it for that Team.">
      {items.length === 0 ? (
        <p className="muted">No classified Sessions yet.</p>
      ) : (
        <>
          <EChart option={option} height={24 + items.length * 30} ariaLabel="Bar chart of Spend by Initiative, stacked by Team"
            onClick={(p) => {
              const r = items.find((x) => x.name === (p.name ?? (p as { value?: string }).value)) ?? items[p.dataIndex ?? -1];
              if (r) router.push(initiativeHref(r.initiative_id, p.seriesName));
            }} />
          {teams.length > 0 && (
            <p className="small legend">
              {legend.map(([bf, ts]) => (
                <span key={bf} className="legend-group">
                  <span className="muted">{bf}:</span>
                  {ts.map((t) => <span key={t} className="legend-item"><span className="swatch" style={{ background: colour(t) }} />{t}</span>)}
                </span>
              ))}
            </p>
          )}
          <details>
            <summary className="small">Table: every Initiative and its Teams</summary>
            <table className="table compact">
              <thead><tr><th>Initiative</th><th>Business Function</th><th>Sessions</th><th>Spend</th><th>Teams (open for a Team)</th></tr></thead>
              <tbody>
                {items.map((r) => (
                  <tr key={r.initiative_id}>
                    <td><Link href={initiativeHref(r.initiative_id)}>{r.name}</Link></td>
                    <td>{r.business_function ?? "—"}</td>
                    <td>{r.session_count.toLocaleString()}</td>
                    <td><Money value={r.spend} size="sm" /></td>
                    <td>
                      {r.teams?.map((t) => (
                        <Link key={t.team} href={initiativeHref(r.initiative_id, t.team)} className="chip" title={formatMoney(t.spend)}>
                          <span className="swatch" style={{ background: colour(t.team) }} />{t.team} <Money value={t.spend} size="sm" />
                        </Link>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </Panel>
  );
}
