"use client";
// Panel: Initiatives treemap. Area = Spend, grouped and coloured by Business Function
// (lib/chartTheme.ts). Click a tile to open the Initiative. GET /api/initiatives
// The table below it (InitiativesTable) is the exact/accessible view.
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { EChart } from "@/components/EChart";
import { formatMoney } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import { tint, tooltipStyle, useChartColors } from "@/lib/chartTheme";
import type { InitiativeList, InitiativeRow } from "@/lib/contract";
import { initiativeHref } from "@/panels/overview/SpendByInitiative";

type Leaf = { name: string; value: number; row: InitiativeRow };

const pct = (part: number, whole: number) => (whole > 0 ? Math.round((100 * part) / whole) : 0);

export default function InitiativesTreemap() {
  const router = useRouter();
  const c = useChartColors();
  const { data, error, loading } = useApi<InitiativeList>("/api/initiatives");
  const items = useMemo(() => data?.items ?? [], [data]);

  const option = useMemo(() => {
    const groups = new Map<string, Leaf[]>();
    items.forEach((r) => {
      const bf = r.business_function ?? "Other";
      groups.set(bf, [...(groups.get(bf) ?? []), { name: r.name, value: r.spend.usd, row: r }]);
    });
    // Within its Business Function's hue, a tile is darker the larger its Measured Waste share.
    const share = (r: InitiativeRow) => (r.spend.usd > 0 ? r.measured_waste.usd / r.spend.usd : 0);
    const maxShare = Math.max(0.01, ...items.map(share));
    const fill = (bf: string, r: InitiativeRow) => tint(c.bf(bf), 0.42 * (1 - share(r) / maxShare), c.surface);
    // Ink by luminance: white on dark fills, near-black on light ones.
    const ink = (hex: string) => {
      const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
      return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.55 ? "#1b1b1f" : "#ffffff";
    };
    return {
      tooltip: {
        ...tooltipStyle(c),
        formatter: (p: { data: Leaf & { children?: Leaf[] }; name: string }) => {
          const r = p.data.row;
          if (!r) return `<b>${p.name}</b>`;
          return `<b>${r.name}</b><br/>${r.business_function ?? ""} · ${r.session_count.toLocaleString()} Sessions`
            + `<br/>Spend ${formatMoney(r.spend)}`
            + `<br/>Measured Waste ${formatMoney(r.measured_waste)} (${pct(r.measured_waste.usd, r.spend.usd)}%)`
            + `<br/>Estimated Saving ${formatMoney(r.estimated_saving)}`;
        },
      },
      series: [{
        type: "treemap",
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        top: 0, left: 0, right: 0, bottom: 0,
        squareRatio: 1.2,
        animationDurationUpdate: 500,
        upperLabel: { show: true, height: 26, fontSize: 12, fontWeight: 600, padding: [0, 8] },
        label: {
          show: true, position: "insideTopLeft", overflow: "truncate", padding: [6, 8],
          formatter: (p: { data: Leaf }) => p.data.row
            ? `{n|${p.data.name}}\n{v|${formatMoney(p.data.row.spend)}} {w|${pct(p.data.row.measured_waste.usd, p.data.row.spend.usd)}% waste}`
            : p.data.name,
          rich: { n: { fontSize: 12, fontWeight: 600, lineHeight: 17 }, v: { fontSize: 12, lineHeight: 16 }, w: { fontSize: 11, lineHeight: 16, opacity: 0.8 } },
        },
        levels: [
          { itemStyle: { borderWidth: 0, gapWidth: 8 }, upperLabel: { show: false } },
          { itemStyle: { borderWidth: 3, gapWidth: 2, borderRadius: 10 } },
          { itemStyle: { borderColor: c.surface, borderWidth: 2, borderRadius: 6 } },
        ],
        data: [...groups.entries()]
          .sort((a, b) => b[1].reduce((s, x) => s + x.value, 0) - a[1].reduce((s, x) => s + x.value, 0))
          .map(([bf, leaves]) => ({
            name: bf,
            itemStyle: { color: c.bf(bf), borderColor: c.bf(bf) },
            upperLabel: { color: ink(c.bf(bf)), formatter: `${bf}` },
            children: leaves.map((l) => {
              const col = fill(bf, l.row);
              return { ...l, itemStyle: { color: col }, label: { color: ink(col) } };
            }),
          })),
      }],
    };
  }, [items, c]);

  return (
    <Panel title="Where the Spend goes" source={data?.source} loading={loading} error={error}
      info="Tile area = Spend, grouped and coloured by Business Function; a darker tile has a larger Measured Waste share. Hover for Waste and Saving; click to open the Initiative.">
      {items.length === 0 ? (
        <p className="muted">No classified Sessions yet.</p>
      ) : (
        <EChart option={option} height={items.length > 8 ? 440 : 320} ariaLabel="Treemap of Spend by Initiative, grouped by Business Function"
          onClick={(p) => {
            const row = (p.data as Leaf | undefined)?.row;
            if (row) router.push(initiativeHref(row.initiative_id));
          }} />
      )}
    </Panel>
  );
}
