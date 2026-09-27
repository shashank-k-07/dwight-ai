// THE way to show a dollar figure. Every figure carries its Measured or Estimated
// label (ADR 0006). The number formatter is deliberately not exported: panels
// must use <Money value={m}/> (or formatMoney(m) for chart tooltips, which also
// includes the label). Never render `m.usd` yourself.
import type { Money as MoneyT } from "@/lib/contract";

const KIND_LABEL = { measured: "Measured", estimated: "Estimated" } as const;

function usd(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1000) return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  if (abs >= 1 || abs === 0) return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2, minimumFractionDigits: 2 });
  return "$" + n.toPrecision(2); // sub-dollar (e.g. a single tracer Session)
}

/** String form for chart tooltips/axis-free text: "$1,234 (Measured)". */
export function formatMoney(m: MoneyT): string {
  return `${usd(m.usd)} (${KIND_LABEL[m.kind]}${m.note ? `, ${m.note}` : ""})`;
}

export function Money({ value, size = "md" }: { value: MoneyT; size?: "sm" | "md" | "lg" }) {
  return (
    <span className={`money money-${size}`}>
      <span className="money-amount">{usd(value.usd)}</span>
      <span className={`money-kind money-kind-${value.kind}`} title={value.note ?? undefined}>
        {KIND_LABEL[value.kind]}
        {value.note ? ` · ${value.note}` : ""}
      </span>
    </span>
  );
}
