"use client";
// Panel: closing-numbers strip (demo step 7). Owner: 17 (accuracy from 08, drop from 13/16).
// GET /api/closing-numbers. Every number comes from the endpoint; `python -m dwight.pipeline
// export-numbers` writes the same numbers, formatted the same way, for the slides.
import type { CSSProperties, ReactNode } from "react";
import { Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import type { ClosingNumbers as CN } from "@/lib/contract";

const pct = (x: number) => `${x.toFixed(1)}%`; // keep in step with dwight/demo.py pct()

const grid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
  gap: 12,
  margin: "4px 0 12px",
};
const tile: CSSProperties = {
  background: "var(--bg)",
  border: "1px solid var(--border)",
  borderRadius: 10,
  padding: "14px 16px",
  minWidth: 0,
};
const big: CSSProperties = { fontSize: 30, fontWeight: 700, lineHeight: 1.15, fontVariantNumeric: "tabular-nums" };
const caption: CSSProperties = { color: "var(--text-secondary)", fontSize: 13, marginTop: 6 };
const sub: CSSProperties = { color: "var(--text-muted)", fontSize: 12, marginTop: 4 };

function Tile({ value, caption: c, detail }: { value: ReactNode; caption: string; detail?: ReactNode }) {
  return (
    <div style={tile}>
      <div style={big}>{value}</div>
      <div style={caption}>{c}</div>
      {detail && <div style={sub}>{detail}</div>}
    </div>
  );
}

function Pending({ children }: { children: ReactNode }) {
  return <span style={{ fontSize: 15, fontWeight: 500, color: "var(--text-muted)" }}>{children}</span>;
}

export default function ClosingNumbers() {
  const { data, error, loading } = useApi<CN>("/api/closing-numbers");
  const drop = data?.draft_token_drop_pct;
  const acc = data?.classifier_accuracy;
  return (
    <Panel title="The numbers" source={data?.source} loading={loading} error={error}>
      {data && (
        <>
          <div style={grid}>
            <Tile value={<Money value={data.spend_analysed} size="lg" />} caption="of Spend analysed" />
            <Tile
              value={<Money value={data.measured_waste} size="lg" />}
              caption="Measured Waste found"
              detail={<><Money value={data.measured_waste_real_layer} size="sm" /> of it on the real layer (harness runs)</>}
            />
            <Tile
              value={drop != null
                ? <>{pct(drop)} <span className="money-kind money-kind-measured">Measured</span></>
                : <Pending>No Measured drop to show</Pending>}
              caption={drop != null ? "fewer tokens per Session with the Draft" : "Drafts: token drop"}
              detail={drop != null
                ? "same tasks before and after loading the Draft, task success held"
                : "no before/after runs yet, or task success dropped after the Draft, so it doesn't count"}
            />
            <Tile
              value={acc != null ? pct(acc * 100) : <Pending>No eval yet</Pending>}
              caption="classifier accuracy"
              detail={acc != null
                ? `Initiative labels vs ground truth${data.classifier_eval_sessions ? `, ${data.classifier_eval_sessions.toLocaleString("en-US")} Sessions` : ""}`
                : "run the classifier eval on this store"}
            />
          </div>
          <p className="closing" style={{ margin: 0 }}>
            <Money value={data.spend_analysed} /> of Spend analysed · <Money value={data.measured_waste} /> Measured Waste found
            {drop != null
              ? <> · Drafts cut tokens by <strong>{pct(drop)}</strong> <span className="money-kind money-kind-measured">Measured</span></>
              : <> · no Measured token drop from Drafts yet</>}
            {acc != null && <> · classifier <strong>{pct(acc * 100)}</strong> accurate</>}
            {" "}· plus <Money value={data.estimated_saving} /> Estimated Saving
          </p>
        </>
      )}
    </Panel>
  );
}
