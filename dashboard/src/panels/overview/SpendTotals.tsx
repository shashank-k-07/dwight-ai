"use client";
// Panel: Overview totals. Owner: 01 (Spend) / 05 (Measured Waste, Estimated Saving). GET /api/overview
// Spend, Measured Waste and Estimated Saving are separate totals, never added together (ADR 0006).
import { Money } from "@/components/Money";
import { Panel, Stat } from "@/components/Panel";
import { useApi } from "@/lib/api";
import type { Overview } from "@/lib/contract";

export default function SpendTotals() {
  const { data, error, loading } = useApi<Overview>("/api/overview");
  return (
    <Panel title="Agent Spend" source={data?.source} loading={loading} error={error}
      info="Spend = metered tokens × list price. Measured Waste = Redundant Read, Cache Miss and Runaway Loop, from arithmetic on token counts. Estimated Saving = Model Overkill, from the classifier's judgement. The three are never added together.">
      {data && (
        <>
          <div className="stats">
            <Stat label="Spend">
              <Money value={data.spend} size="lg" />
            </Stat>
            <Stat label="Measured Waste">
              <Money value={data.measured_waste} size="lg" />
            </Stat>
            <Stat label="Estimated Saving">
              <Money value={data.estimated_saving} size="lg" />
            </Stat>
          </div>
          <p className="muted small">
            {data.session_count.toLocaleString()} Sessions
            {data.period.start && data.period.end
              ? ` · ${data.period.start.slice(0, 10)} to ${data.period.end.slice(0, 10)}`
              : ""}
          </p>
        </>
      )}
    </Panel>
  );
}
