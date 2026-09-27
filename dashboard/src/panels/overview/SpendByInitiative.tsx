"use client";
// Panel: Spend by Initiative, stacked by Team (demo feedback: under the Business Function chart).
// GET /api/initiatives (teams: additive contract field) + /api/overview (for Team colours).
// A Team keeps the colour it has in "Spend by Business Function" (its position within its
// Business Function); every Initiative sits in one Business Function, so segments in a bar never
// share a colour. Click an Initiative (name or bar) to open it; click a Team segment to open it
// with that Team highlighted. The table below is the accessible/exact view, with the same links.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatMoney, Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import type { InitiativeList, InitiativeRow, Overview } from "@/lib/contract";

const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)",
  "var(--series-5)", "var(--series-6)", "var(--series-7)", "var(--series-8)"];

export const initiativeHref = (id: string, team?: string) =>
  `/initiatives/${encodeURIComponent(id)}${team ? `?team=${encodeURIComponent(team)}` : ""}`;

// Axis ticks only (the caption labels the axis Measured): $2.5K, $10K, $40, $0.50.
const axisUsd = (v: number) =>
  v >= 1000 ? `$${+(v / 1000).toFixed(v % 1000 && v < 10000 ? 1 : 0)}K` : v >= 1 || v === 0 ? `$${+v.toFixed(v < 10 ? 1 : 0)}` : `$${v.toPrecision(2)}`;

export default function SpendByInitiative() {
  const router = useRouter();
  const { data, error, loading } = useApi<InitiativeList>("/api/initiatives");
  const overview = useApi<Overview>("/api/overview");
  const items = data?.items ?? [];

  // Team -> colour slot and Business Function, from the Business Function chart's order.
  const teamInfo = useMemo(() => {
    const m = new Map<string, { i: number; bf: string }>();
    overview.data?.spend_by_business_function.forEach((bf) =>
      bf.teams.forEach((t, i) => m.set(t.team, { i: i % SERIES.length, bf: bf.business_function })));
    return m;
  }, [overview.data]);
  const colour = (team: string) => SERIES[teamInfo.get(team)?.i ?? 0];

  const teams = useMemo(() => {
    const seen = new Set<string>();
    items.forEach((r) => r.teams?.forEach((t) => seen.add(t.team)));
    // stack in the Business Function chart's Team order, so a Team sits in the same place in every bar
    return [...seen].sort((x, y) => (teamInfo.get(x)?.i ?? 99) - (teamInfo.get(y)?.i ?? 99));
  }, [items, teamInfo]);
  const chartData = items.map((r) => {
    const row: Record<string, unknown> = { name: r.name, id: r.initiative_id, _row: r };
    r.teams?.forEach((t) => (row[t.team] = t.spend.usd)); // chart geometry only; text goes through formatMoney
    return row;
  });
  const legend = useMemo(() => {
    const byBf = new Map<string, string[]>();
    teams.forEach((t) => {
      const bf = teamInfo.get(t)?.bf ?? "Other";
      byBf.set(bf, [...(byBf.get(bf) ?? []), t]);
    });
    byBf.forEach((ts) => ts.sort((a, b) => (teamInfo.get(a)?.i ?? 0) - (teamInfo.get(b)?.i ?? 0)));
    return [...byBf.entries()];
  }, [teams, teamInfo]);

  const hasTeams = items.some((r) => r.teams?.length);
  return (
    <Panel title="Spend by Initiative" source={data?.source} loading={loading} error={error}>
      {items.length === 0 ? (
        <p className="muted">No classified Sessions yet.</p>
      ) : (
        <>
          <p className="small muted">
            Spend (<span className="money-kind money-kind-measured">Measured</span>), stacked by Team. Click an Initiative
            to see its Waste and Recommendations, or a Team&apos;s segment to open it for that Team.
          </p>
          <div style={{ width: "100%", height: 40 + items.length * 30 }}>
            <ResponsiveContainer>
              <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 16 }} barCategoryGap={6}>
                <CartesianGrid horizontal={false} stroke="var(--grid)" />
                <XAxis type="number" tick={{ fill: "var(--text-muted)", fontSize: 12 }} axisLine={false} tickLine={false}
                  tickFormatter={axisUsd} />
                <YAxis type="category" dataKey="name" width={190} axisLine={false} tickLine={false}
                  tick={({ x, y, payload, index }) => (
                    <text className="initiative-tick" x={x} y={y} dy={4} textAnchor="end" fontSize={13} fill="var(--accent)" style={{ cursor: "pointer" }}
                      onClick={() => items[index] && router.push(initiativeHref(items[index].initiative_id))}>
                      {payload.value}
                    </text>
                  )} />
                <Tooltip cursor={{ fill: "var(--hover)" }} content={({ active, payload }) => {
                  const r = payload?.[0]?.payload?._row as InitiativeRow | undefined;
                  if (!active || !r) return null;
                  return (
                    <div className="tooltip">
                      <strong>{r.name}</strong> · {formatMoney(r.spend)}
                      {r.teams?.map((t) => (
                        <div key={t.team}>
                          <span className="swatch" style={{ background: colour(t.team) }} />
                          {t.team}: {formatMoney(t.spend)} · {t.session_count} Sessions
                        </div>
                      ))}
                      <div className="muted" style={{ marginTop: 4 }}>Click a Team&apos;s segment to open the Initiative for that Team</div>
                    </div>
                  );
                }} />
                {teams.map((team) => (
                  <Bar key={team} dataKey={team} stackId="s" fill={colour(team)} stroke="var(--surface)" strokeWidth={2}
                    isAnimationActive={false} style={{ cursor: "pointer" }}
                    onClick={(d) => {
                      const id = (d as { payload?: { id?: string } }).payload?.id;
                      if (id) router.push(initiativeHref(id, team));
                    }} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
          {hasTeams && (
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
