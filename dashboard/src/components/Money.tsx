// THE way to show a dollar figure (ADR 0006). Measured is the default and carries no
// visible pill (the header says "figures are Measured unless marked Estimated"); it is
// still in the accessible name and tooltip. Estimated always shows its pill. A note
// (e.g. "conservative upper bound") is shown for both. The number formatter is
// deliberately not exported: panels use <Money value={m}/> (or formatMoney(m) for chart
// tooltips). Never render `m.usd` yourself.
import type { Money as MoneyT } from "@/lib/contract";

const KIND_LABEL = { measured: "Measured", estimated: "Estimated" } as const;

function usd(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1000) return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  if (abs >= 1 || abs === 0) return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2, minimumFractionDigits: 2 });
  return "$" + n.toPrecision(2); // sub-dollar (e.g. a single tracer Session)
}

/** String form for chart tooltips: "$1,234", "$1,234 (Estimated)", "$9 (conservative upper bound)". */
export function formatMoney(m: MoneyT): string {
  const parts = [m.kind === "estimated" ? KIND_LABEL.estimated : null, m.note].filter(Boolean);
  return parts.length ? `${usd(m.usd)} (${parts.join(", ")})` : usd(m.usd);
}

export function Money({ value, size = "md" }: { value: MoneyT; size?: "sm" | "md" | "lg" }) {
  const label = KIND_LABEL[value.kind] + (value.note ? ` · ${value.note}` : "");
  return (
    <span className={`money money-${size}`} title={label}>
      <span className="money-amount">{usd(value.usd)}</span>
      {value.kind === "estimated" ? (
        <span className="money-kind money-kind-estimated">{label}</span>
      ) : (
        <>
          <span className="sr-only">Measured</span>
          {value.note && <span className="money-note">{value.note}</span>}
        </>
      )}
    </span>
  );
}

/** Small ⓘ with the explanation in a tooltip, for copy that used to sit inline. */
export function Info({ children }: { children: string }) {
  return <span className="info" title={children} aria-label={children} role="img">ⓘ</span>;
}
