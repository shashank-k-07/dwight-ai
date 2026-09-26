"use client";
// Panel: Waste Pattern breakdown. Owner: 09. GET /api/initiatives/{id}/waste
import { Money } from "@/components/Money";
import { Panel, Stat } from "@/components/Panel";
import { useApi } from "@/lib/api";
import { WASTE_PATTERN_LABEL, type WasteBreakdown as WB } from "@/lib/contract";

export default function WasteBreakdown({ initiativeId }: { initiativeId: string }) {
  const { data, error, loading } = useApi<WB>(`/api/initiatives/${initiativeId}/waste`);
  return (
    <Panel title="Waste Patterns" source={data?.source} loading={loading} error={error}>
      {data && (
        <>
          <div className="stats">
            <Stat label="Measured Waste"><Money value={data.measured_total} /></Stat>
            <Stat label="Estimated Saving"><Money value={data.estimated_total} /></Stat>
          </div>
          <table className="table compact">
            <thead><tr><th>Waste Pattern</th><th>Sessions</th><th>Findings</th><th>Amount</th></tr></thead>
            <tbody>
              {data.patterns.map((p) => (
                <tr key={p.pattern}>
                  <td>{WASTE_PATTERN_LABEL[p.pattern]}</td><td>{p.session_count}</td><td>{p.finding_count}</td>
                  <td><Money value={p.amount} size="sm" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Panel>
  );
}
