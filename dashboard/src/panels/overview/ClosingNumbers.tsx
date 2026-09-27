"use client";
// Panel: closing-numbers strip (demo step 7). Only the figures no other Overview panel shows
// (Spend, Measured Waste and Estimated Saving are in Agent Spend). Owner: 17 (accuracy from 08, drop from 13/16).
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
    <Panel title="Results" source={data?.source} loading={loading} error={error}>
      {data && (
        <>
          <div style={grid}>
            <Tile
              value={drop != null ? `−${pct(drop)}` : <Pending>No Measured drop yet</Pending>}
              caption="tokens per Session with the Draft"
              detail={drop != null
                ? "same tasks before and after, task success held"
                : "no before/after runs yet, or task success dropped, so it doesn't count"}
            />
            <Tile
              value={acc != null ? pct(acc * 100) : <Pending>No eval yet</Pending>}
              caption="classifier accuracy"
              detail={acc != null
                ? `Initiative labels vs ground truth${data.classifier_eval_sessions ? `, ${data.classifier_eval_sessions.toLocaleString("en-US")} Sessions` : ""}`
                : "run the classifier eval on this store"}
            />
            <Tile
              value={<Money value={data.measured_waste_real_layer} size="lg" />}
              caption="Measured Waste on the real layer"
              detail="harness runs, not synthetic"
            />
          </div>
        </>
      )}
    </Panel>
  );
}
