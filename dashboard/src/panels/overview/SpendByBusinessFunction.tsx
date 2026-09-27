"use client";
// Panel: Spend by Business Function (inner ring) and Team (outer ring), ECharts sunburst. Owner: 07.
// GET /api/overview. Colours from lib/chartTheme.ts;
// the collapsed table below is the accessible/exact view.
import { useMemo } from "react";
import { EChart } from "@/components/EChart";
import { formatMoney, Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import { tint, tooltipStyle, useChartColors } from "@/lib/chartTheme";
import type { Money as MoneyT, Overview } from "@/lib/contract";

const TEAM_TINTS = [0, 0.3, 0.5, 0.65, 0.75]; // same as SpendByInitiative: a Team keeps its colour

type Node = { name: string; value: number; money: MoneyT; sessions: number; share: number };

export default function SpendByBusinessFunction() {
  const c = useChartColors();
  const { data, error, loading } = useApi<Overview>("/api/overview");
  const rows = useMemo(() => data?.spend_by_business_function ?? [], [data]);
  const totalSessions = rows.reduce((n, bf) => n + bf.session_count, 0);
  const total = rows.reduce((n, bf) => n + bf.spend.usd, 0);
  const teamColour = (bf: string, i: number) => tint(c.bf(bf), TEAM_TINTS[Math.min(i, TEAM_TINTS.length - 1)], c.surface);

  const option = useMemo(() => ({
    tooltip: {
      ...tooltipStyle(c),
      formatter: (p: { data: Node }) =>
        `<b>${p.data.name}</b><br/>${formatMoney(p.data.money)} · ${Math.round(p.data.share * 100)}% of Spend<br/>${p.data.sessions.toLocaleString()} Sessions`,
    },
    series: [{
      type: "sunburst", sort: undefined, radius: ["28%", "96%"], nodeClick: false,
      itemStyle: { borderColor: c.surface, borderWidth: 2, borderRadius: 5 },
      emphasis: { focus: "ancestor" },
      levels: [
        {},
        { r0: "28%", r: "58%", label: { rotate: 0, color: "#fff", fontSize: 12, fontWeight: 600, minAngle: 14, overflow: "truncate", width: 96 } },
        { r0: "58%", r: "96%", label: { rotate: "radial", fontSize: 11, minAngle: 9, overflow: "truncate", width: 90 } },
      ],
      data: rows.map((bf) => ({
        name: bf.business_function, value: bf.spend.usd, money: bf.spend, sessions: bf.session_count, share: total ? bf.spend.usd / total : 0,
        itemStyle: { color: c.bf(bf.business_function) },
        children: bf.teams.map((t, i) => {
          const col = teamColour(bf.business_function, i);
          return {
            name: t.team, value: t.spend.usd, money: t.spend, sessions: t.session_count, share: total ? t.spend.usd / total : 0,
            itemStyle: { color: col }, label: { color: i < 2 ? "#fff" : "#1b1b1f" },
          };
        }),
      })),
    }],
  }), [rows, c, total]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Panel title="Spend by Business Function" source={data?.source} loading={loading} error={error}
      info="Inner ring: Business Functions; outer ring: their Teams. Arc size = Spend. Hover for figures; the table has exact numbers.">
      {rows.length === 0 ? (
        <p className="muted">No Sessions yet.</p>
      ) : (
        <>
          <div className="bf-grid">
            <EChart option={option} height={320} ariaLabel="Sunburst of Spend by Business Function and Team" />
            <ul className="bf-legend">
              {rows.map((bf) => (
                <li key={bf.business_function}>
                  <span className="swatch" style={{ background: c.bf(bf.business_function) }} />
                  <span>{bf.business_function}</span>
                  <span className="muted small">{total ? Math.round((100 * bf.spend.usd) / total) : 0}%</span>
                  <Money value={bf.spend} size="sm" />
                </li>
              ))}
            </ul>
          </div>
          <details>
            <summary className="small">Table: every Business Function and its Teams</summary>
          <table className="table compact">
            <thead><tr><th>Business Function</th><th>Team</th><th>Sessions</th><th>Spend</th></tr></thead>
            <tbody>
              {rows.flatMap((bf) => [
                <tr key={bf.business_function}>
                  <td><strong>{bf.business_function}</strong></td>
                  <td className="muted">All Teams</td>
                  <td><strong>{bf.session_count}</strong>{totalSessions > 0 && (
                    <span className="small muted"> ({Math.round((100 * bf.session_count) / totalSessions)}%)</span>)}</td>
                  <td><Money value={bf.spend} size="sm" /></td>
                </tr>,
                ...bf.teams.map((t, i) => (
                  <tr key={bf.business_function + t.team}>
                    <td></td>
                    <td><span className="swatch" style={{ background: teamColour(bf.business_function, i) }} />{t.team}</td>
                    <td>{t.session_count}</td>
                    <td><Money value={t.spend} size="sm" /></td>
                  </tr>
                )),
              ])}
            </tbody>
          </table>
          </details>
        </>
      )}
    </Panel>
  );
}
