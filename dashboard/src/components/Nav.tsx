"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useApi } from "@/lib/api";
import type { Health } from "@/lib/contract";
import { useSimulation } from "@/lib/simulation";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/initiatives", label: "Initiatives" },
  { href: "/policy", label: "Policy" },
];

export function Nav() {
  const path = usePathname();
  const { data: health } = useApi<Health>("/api/health");
  const sim = useSimulation();
  const mult = health?.price_multiplier ?? 1;
  return (
    <nav className="nav">
      <span className="brand">Dwight</span>
      {LINKS.map((l) => {
        const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
        return (
          <Link key={l.href} href={l.href} className={active ? "active" : ""}>
            {l.label}
          </Link>
        );
      })}
      <span className="nav-right">
        <span className="nav-legend" title="Measured = arithmetic on metered token counts × list price. Estimated = depends on a model judgement.">
          $ figures are Measured unless marked <span className="money-kind money-kind-estimated">Estimated</span>
        </span>
        {sim.count > 0 && (
          <span className="badge badge-sim" title="Implemented in this browser only. Nothing was changed in the store.">
            Simulation: {sim.count} implemented ·{" "}
            <button type="button" className="linklike" onClick={sim.reset}>Reset simulation</button>
          </span>
        )}
        {mult !== 1 && (
          <span className="badge badge-demo-pricing"
            title={`DWIGHT_PRICE_MULTIPLIER=${mult}: every $ figure is list price × ${mult} for the demo. Percentages are unchanged. Real list prices are in data/prices.yaml.`}>
            Demo pricing ×{mult}
          </span>
        )}
      </span>
    </nav>
  );
}
