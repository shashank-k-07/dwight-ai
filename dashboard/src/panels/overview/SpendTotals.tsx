"use client";
// Panel: Overview totals. Owner: 01 (Spend) / 05 (Measured Waste, Estimated Saving). GET /api/overview
// Spend, Measured Waste and Estimated Saving are separate totals, never added together (ADR 0006).
import { Money } from "@/components/Money";
import { Panel, Stat } from "@/components/Panel";
import { useApi } from "@/lib/api";
import { WASTE_PATTERN_LABEL, type Overview, type WastePattern } from "@/lib/contract";

const MEASURED: WastePattern[] = ["redundant_read", "cache_miss", "runaway_loop"];
const ESTIMATED: WastePattern[] = ["model_overkill"];

function Patterns({ patterns, basis }: { patterns: WastePattern[]; basis: string }) {
  return (
    <div className="muted small">
      {patterns.map((p) => WASTE_PATTERN_LABEL[p]).join(", ")} · {basis}
    </div>
  );
}

export default function SpendTotals() {
  const { data, error, loading } = useApi<Overview>("/api/overview");
  return (
    <Panel title="Agent Spend" source={data?.source} loading={loading} error={error}>
      {data && (
        <>
          <div className="stats">
            <Stat label="Spend">
              <Money value={data.spend} size="lg" />
              <div className="muted small">metered tokens × list price</div>
            </Stat>
            <Stat label="Measured Waste">
              <Money value={data.measured_waste} size="lg" />
              <Patterns patterns={MEASURED} basis="arithmetic on token counts" />
            </Stat>
            <Stat label="Estimated Saving">
              <Money value={data.estimated_saving} size="lg" />
              <Patterns patterns={ESTIMATED} basis="from the classifier's judgement" />
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
