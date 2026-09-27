"use client";
// Panel: Spend by Business Function, stacked by Team. Owner: 07. GET /api/overview
// Segment colour = the Team's position within its Business Function (tooltip names it);
// the collapsed table below is the accessible/exact view.
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatMoney, Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import type { Overview, TeamSpend } from "@/lib/contract";

const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)",
  "var(--series-5)", "var(--series-6)", "var(--series-7)", "var(--series-8)"];

export default function SpendByBusinessFunction() {
  const { data, error, loading } = useApi<Overview>("/api/overview");
  const rows = data?.spend_by_business_function ?? [];
  const totalSessions = rows.reduce((n, bf) => n + bf.session_count, 0);
  const maxTeams = Math.min(8, Math.max(0, ...rows.map((r) => r.teams.length)));
  const chartData = rows.map((bf) => {
    const row: Record<string, unknown> = { name: bf.business_function };
    bf.teams.slice(0, 8).forEach((t, i) => {
      row[`t${i}`] = t.spend.usd; // chart geometry only; text goes through formatMoney
      row[`t${i}_team`] = t;
    });
    return row;
  });
  return (
    <Panel title="Spend by Business Function" source={data?.source} loading={loading} error={error}
      info="Spend, stacked by Team. Hover a bar for Team figures; the table has exact numbers.">
      {rows.length === 0 ? (
        <p className="muted">No Sessions yet.</p>
      ) : (
        <>
                    <div style={{ width: "100%", height: 48 + rows.length * 44 }}>
            <ResponsiveContainer>
              <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 16 }} barCategoryGap={10}>
                <CartesianGrid horizontal={false} stroke="var(--grid)" />
                <XAxis type="number" tick={{ fill: "var(--text-muted)", fontSize: 12 }} axisLine={false} tickLine={false}
                  tickFormatter={(v: number) => (v >= 1000 ? `$${Math.round(v / 1000)}K` : v >= 1 || v === 0 ? `$${v}` : `$${v.toPrecision(2)}`)} />
                <YAxis type="category" dataKey="name" width={110} tick={{ fill: "var(--text-secondary)", fontSize: 13 }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: "var(--hover)" }} content={({ active, payload, label }) =>
                  active && payload?.length ? (
                    <div className="tooltip">
                      <strong>{label}</strong>
                      {payload.map((p) => {
                        const t = (p.payload as Record<string, TeamSpend>)[`${p.dataKey}_team`];
                        return t ? <div key={String(p.dataKey)}><span className="swatch" style={{ background: p.color }} />{t.team}: {formatMoney(t.spend)}</div> : null;
                      })}
                    </div>
                  ) : null} />
                {Array.from({ length: maxTeams }, (_, i) => (
                  <Bar key={i} dataKey={`t${i}`} stackId="s" fill={SERIES[i]} stroke="var(--surface)" strokeWidth={2}
                    radius={i === maxTeams - 1 ? [0, 4, 4, 0] : 0} isAnimationActive={false} />
                ))}
              </BarChart>
            </ResponsiveContainer>
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
                    <td><span className="swatch" style={{ background: SERIES[i % 8] }} />{t.team}</td>
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
