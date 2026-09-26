"use client";
// Panel: closing-numbers strip (demo step 7). Owner: 17 (accuracy from 08, drop from 13/16).
// GET /api/closing-numbers
import { Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import type { ClosingNumbers as CN } from "@/lib/contract";

export default function ClosingNumbers() {
  const { data, error, loading } = useApi<CN>("/api/closing-numbers");
  return (
    <Panel title="The numbers" source={data?.source} loading={loading} error={error}>
      {data && (
        <p className="closing">
          <Money value={data.spend_analysed} /> of Spend analysed · <Money value={data.measured_waste} /> Measured Waste found
          {data.draft_token_drop_pct != null && <> · Drafts cut tokens by <strong>{data.draft_token_drop_pct.toFixed(0)}%</strong> <span className="money-kind money-kind-measured">Measured</span></>}
          {data.classifier_accuracy != null && <> · classifier <strong>{(data.classifier_accuracy * 100).toFixed(0)}%</strong> accurate</>}
        </p>
      )}
    </Panel>
  );
}
