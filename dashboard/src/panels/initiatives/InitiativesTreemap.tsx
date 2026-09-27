"use client";
// Panel: Initiatives treemap, one Business Function at a time (dropdown; "All" shows them grouped).
// GET /api/initiatives. Tile area = Measured Waste; each Business Function keeps its colour and its
// Initiatives run light -> dark by Measured Waste share (ranked within the Function), so the darkest,
// largest tiles are where to cut first. Click a tile to open the Initiative. The dropdown is shared
// with the table below via ?bf= (lib/businessFunction.ts).
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { EChart } from "@/components/EChart";
import { formatMoney, Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import { ALL, useBusinessFunction } from "@/lib/businessFunction";
import { inkOn, shade, tooltipStyle, useChartColors } from "@/lib/chartTheme";
import type { InitiativeList, InitiativeRow } from "@/lib/contract";
import { initiativeHref } from "@/panels/overview/SpendByInitiative";

type Leaf = { name: string; value: number; row: InitiativeRow };

const pct = (part: number, whole: number) => (whole > 0 ? Math.round((100 * part) / whole) : 0);
const share = (r: InitiativeRow) => (r.spend.usd > 0 ? r.measured_waste.usd / r.spend.usd : 0);
const bfOf = (r: InitiativeRow) => r.business_function ?? "Other";

export default function InitiativesTreemap() {
  const router = useRouter();
  const c = useChartColors();
  const { data, error, loading } = useApi<InitiativeList>("/api/initiatives");
  const items = useMemo(() => data?.items ?? [], [data]);

  // Business Functions by Measured Waste; the default view is the one with the most.
  const functions = useMemo(() => {
    const m = new Map<string, { waste: number; spend: number }>();
    items.forEach((r) => {
      const cur = m.get(bfOf(r)) ?? { waste: 0, spend: 0 };
      m.set(bfOf(r), { waste: cur.waste + r.measured_waste.usd, spend: cur.spend + r.spend.usd });
    });
    return [...m.entries()].sort((a, b) => b[1].waste - a[1].waste);
  }, [items]);
  const [picked, setPicked] = useBusinessFunction(functions[0]?.[0] ?? null);
  const bf = picked === ALL || functions.some(([f]) => f === picked) ? picked : functions[0]?.[0] ?? null;

  const shown = useMemo(() => items.filter((r) => bf === ALL || bfOf(r) === bf), [items, bf]);
  const wasteful = shown.filter((r) => r.measured_waste.usd > 0).sort((a, b) => b.measured_waste.usd - a.measured_waste.usd);
  const clean = shown.filter((r) => r.measured_waste.usd <= 0);
  const single = bf !== ALL;

  const option = useMemo(() => {
    const groups = new Map<string, Leaf[]>();
    wasteful.forEach((r) => groups.set(bfOf(r), [...(groups.get(bfOf(r)) ?? []), { name: r.name, value: r.measured_waste.usd, row: r }]));
    const fill = (f: string, leaves: Leaf[], r: InitiativeRow) => {
      const ranked = [...leaves].sort((a, b) => share(a.row) - share(b.row));
      const t = ranked.length > 1 ? ranked.findIndex((l) => l.row === r) / (ranked.length - 1) : 0.5;
      return shade(c.bf(f), t, c.surface);
    };
    return {
      tooltip: {
        ...tooltipStyle(c),
        formatter: (p: { data: Leaf; name: string }) => {
          const r = p.data.row;
          if (!r) return `<b>${p.name}</b>`;
          return `<b>${r.name}</b><br/>${bfOf(r)} · ${r.session_count.toLocaleString()} Sessions`
            + `<br/>Measured Waste ${formatMoney(r.measured_waste)} (${pct(r.measured_waste.usd, r.spend.usd)}% of its Spend)`
            + `<br/>Spend ${formatMoney(r.spend)} · ${r.session_count ? formatMoney({ ...r.spend, usd: r.spend.usd / r.session_count }) : "—"} per Session`
            + `<br/>Estimated Saving ${formatMoney(r.estimated_saving)}`;
        },
      },
      series: [{
        type: "treemap", roam: false, nodeClick: false, breadcrumb: { show: false },
        top: 0, left: 0, right: 0, bottom: 0, squareRatio: 1.2, animationDurationUpdate: 450,
        upperLabel: { show: !single, height: 26, fontSize: 12, fontWeight: 600, padding: [0, 8] },
        label: {
          show: true, position: "insideTopLeft", overflow: "truncate", padding: [6, 8],
          formatter: (p: { data: Leaf }) => p.data.row
            ? `{n|${p.data.name}}\n{v|${formatMoney(p.data.row.measured_waste)}} {w|${pct(p.data.row.measured_waste.usd, p.data.row.spend.usd)}% of Spend}`
            : p.data.name,
          rich: { n: { fontSize: 13, fontWeight: 600, lineHeight: 18 }, v: { fontSize: 12, lineHeight: 16 }, w: { fontSize: 11, lineHeight: 16, opacity: 0.8 } },
        },
        levels: [
          { itemStyle: { borderWidth: 0, gapWidth: single ? 0 : 8 }, upperLabel: { show: false } },
          { itemStyle: { borderWidth: single ? 0 : 3, gapWidth: 2, borderRadius: 10 } },
          { itemStyle: { borderColor: c.surface, borderWidth: 2, borderRadius: 8 } },
        ],
        data: [...groups.entries()]
          .sort((a, b) => b[1].reduce((s, x) => s + x.value, 0) - a[1].reduce((s, x) => s + x.value, 0))
          .map(([f, leaves]) => ({
            name: f,
            itemStyle: { color: single ? c.surface : c.bf(f), borderColor: c.bf(f) },
            upperLabel: { color: inkOn(c.bf(f)), formatter: f },
            children: leaves.map((l) => {
              const col = fill(f, leaves, l.row);
              return { ...l, itemStyle: { color: col }, label: { color: inkOn(col) } };
            }),
          })),
      }],
    };
  }, [wasteful, c, single]); // eslint-disable-line react-hooks/exhaustive-deps

  const totals = functions.find(([f]) => f === bf)?.[1];
  const allWaste = functions.reduce((n, [, t]) => n + t.waste, 0);
  const top3 = wasteful.slice(0, 3);
  const top3Share = pct(top3.reduce((n, r) => n + r.measured_waste.usd, 0), wasteful.reduce((n, r) => n + r.measured_waste.usd, 0));
  const unit = wasteful[0]?.measured_waste;

  const picker = functions.length > 0 && (
    <select className="bf-select" value={bf ?? ""} onChange={(e) => setPicked(e.target.value)} aria-label="Business Function">
      {functions.map(([f]) => <option key={f} value={f}>{f}</option>)}
      <option value={ALL}>All Business Functions</option>
    </select>
  );

  return (
    <Panel title="Where the Waste is" source={data?.source} loading={loading} error={error} actions={picker}
      info="Tile area = Measured Waste: the Spend you can cut. Darker shade = a larger share of that Initiative's Spend was Waste (ranked within the Business Function). Hover for figures; click to open the Initiative.">
      {unit && (
        <p className="cut-headline">
          <span className="swatch" style={{ background: single && bf ? c.bf(bf) : c.textMuted }} />
          <Money value={{ ...unit, usd: single && totals ? totals.waste : allWaste }} /> Measured Waste
          {single && totals ? <span className="muted"> · {pct(totals.waste, totals.spend)}% of {bf}&apos;s Spend</span> : null}
          {wasteful.length > 3 && <span className="muted"> · top 3 Initiatives hold {top3Share}%</span>}
        </p>
      )}
      {wasteful.length === 0 ? (
        <p className="muted">{items.length === 0 ? "No classified Sessions yet." : "No Measured Waste here."}</p>
      ) : (
        <EChart option={option} height={single ? 380 : 440} ariaLabel={`Treemap of Measured Waste by Initiative${single ? ` in ${bf}` : ""}`}
          onClick={(p) => {
            const row = (p.data as Leaf | undefined)?.row;
            if (row) router.push(initiativeHref(row.initiative_id));
          }} />
      )}
      <div className="treemap-foot">
        {wasteful.length > 1 && single && bf && (
          <span className="small muted seq-legend">
            Waste share: lower
            <span className="seq-ramp">{[0, 0.25, 0.5, 0.75, 1].map((t) => <span key={t} style={{ background: shade(c.bf(bf), t, c.surface) }} />)}</span>
            higher
          </span>
        )}
        {clean.length > 0 && <span className="small muted">No Measured Waste: {clean.map((r) => r.name).join(", ")}</span>}
      </div>
    </Panel>
  );
}
