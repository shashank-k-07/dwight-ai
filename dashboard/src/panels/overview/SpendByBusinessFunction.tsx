"use client";
// Panel: Spend by Business Function and Team, as packed bubbles. Owner: 07. GET /api/overview
// Outer circle = a Business Function, inner bubbles = its Teams; area = Spend. Layout from
// d3-hierarchy's pack(), drawn as plain SVG. The legend beside it carries every Business
// Function's exact Spend and share, so small circles don't need labels.
// Colours from lib/chartTheme.ts: a Business Function's hue, Teams as tints of it.
import { pack, hierarchy, type HierarchyCircularNode } from "d3-hierarchy";
import { useMemo, useState } from "react";
import { formatMoney, Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import { inkOn, tint, useChartColors } from "@/lib/chartTheme";
import type { Money as MoneyT, Overview } from "@/lib/contract";

const SIZE = 420;
const TEAM_TINTS = [0, 0.2, 0.35, 0.5, 0.6]; // a Team keeps its place in its Business Function's order

type Datum = { name: string; bf?: string; i?: number; spend?: MoneyT; sessions?: number; children?: Datum[] };

const pct = (part: number, whole: number) => (whole > 0 ? (100 * part) / whole : 0);
const pctLabel = (x: number) => (x > 0 && x < 1 ? "<1%" : `${Math.round(x)}%`);
const fit = (text: string, r: number) => {
  const max = Math.floor((r * 1.7) / 6.6); // ~6.6px per character at 11px
  return text.length <= max ? text : max > 3 ? text.slice(0, max - 1) + "…" : "";
};

export default function SpendByBusinessFunction() {
  const c = useChartColors();
  const { data, error, loading } = useApi<Overview>("/api/overview");
  const rows = useMemo(
    () => [...(data?.spend_by_business_function ?? [])].sort((a, b) => b.spend.usd - a.spend.usd),
    [data],
  );
  const total = rows.reduce((n, bf) => n + bf.spend.usd, 0);
  const [hover, setHover] = useState<{ d: HierarchyCircularNode<Datum>; x: number; y: number } | null>(null);

  const nodes = useMemo(() => {
    const root = hierarchy<Datum>({
      name: "all",
      children: rows.map((bf) => ({
        name: bf.business_function, spend: bf.spend, sessions: bf.session_count,
        children: bf.teams.map((t, i) => ({ name: t.team, bf: bf.business_function, i, spend: t.spend, sessions: t.session_count })),
      })),
    }).sum((d) => (d.children ? 0 : d.spend?.usd ?? 0)); // geometry only; text goes through formatMoney
    return pack<Datum>().size([SIZE, SIZE]).padding((n) => (n.depth === 0 ? 10 : 3))(root).descendants().slice(1);
  }, [rows]);

  const teamFill = (d: Datum) => tint(c.bf(d.bf), TEAM_TINTS[Math.min(d.i ?? 0, TEAM_TINTS.length - 1)], c.surface);

  return (
    <Panel title="Spend by Business Function" source={data?.source} loading={loading} error={error}
      info="Each outer circle is a Business Function; the bubbles inside are its Teams. Area = Spend. Hover a bubble for figures.">
      {rows.length === 0 ? (
        <p className="muted">No Sessions yet.</p>
      ) : (
        <div className="bubble-grid">
          <div className="bubble-wrap" onMouseLeave={() => setHover(null)}>
            <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label="Packed bubbles: Spend by Business Function and Team">
              {nodes.map((n) => {
                const d = n.data;
                const onMove = (e: React.MouseEvent) => {
                  const box = (e.currentTarget as SVGElement).ownerSVGElement!.getBoundingClientRect();
                  setHover({ d: n, x: e.clientX - box.left, y: e.clientY - box.top });
                };
                if (n.depth === 1) {
                  return (
                    <g key={`bf-${d.name}`}>
                      <circle cx={n.x} cy={n.y} r={n.r} fill={tint(c.bf(d.name), c.dark ? 0.8 : 0.88, c.surface)}
                        stroke={c.bf(d.name)} strokeOpacity={0.35} onMouseMove={onMove} />
                      {n.r > 70 && (
                        <text x={n.x} y={n.y - n.r + 16} textAnchor="middle" fontSize={12} fontWeight={600} fill={c.text} pointerEvents="none">
                          {d.name}
                        </text>
                      )}
                    </g>
                  );
                }
                const fill = teamFill(d);
                const ink = inkOn(fill);
                const label = fit(d.name, n.r);
                return (
                  <g key={`t-${d.bf}-${d.name}`} onMouseMove={onMove} style={{ cursor: "default" }}>
                    <circle cx={n.x} cy={n.y} r={n.r} fill={fill} stroke={c.surface} strokeWidth={2}
                      opacity={hover && hover.d !== n ? 0.85 : 1} />
                    {n.r > 22 && label && (
                      <>
                        <text x={n.x} y={n.y - 1} textAnchor="middle" fontSize={11} fontWeight={600} fill={ink} pointerEvents="none">{label}</text>
                        {d.spend && n.r > 30 && (
                          <text x={n.x} y={n.y + 13} textAnchor="middle" fontSize={11} fill={ink} opacity={0.85} pointerEvents="none">
                            {formatMoney(d.spend)}
                          </text>
                        )}
                      </>
                    )}
                  </g>
                );
              })}
            </svg>
            {hover && hover.d.data.spend && (
              <div className="tooltip bubble-tip" style={{ left: hover.x + 12, top: hover.y + 12 }}>
                <strong>{hover.d.data.name}</strong>
                {hover.d.depth === 2 && <span className="muted"> · {hover.d.data.bf}</span>}
                <div>{formatMoney(hover.d.data.spend)} · {pctLabel(pct(hover.d.data.spend.usd, total))} of Spend</div>
                <div className="muted">{(hover.d.data.sessions ?? 0).toLocaleString()} Sessions</div>
              </div>
            )}
          </div>
          <ul className="bf-legend">
            {rows.map((bf) => (
              <li key={bf.business_function}>
                <span className="swatch" style={{ background: c.bf(bf.business_function) }} />
                <span>{bf.business_function}</span>
                <span className="muted small">{pctLabel(pct(bf.spend.usd, total))}</span>
                <Money value={bf.spend} size="sm" />
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}
