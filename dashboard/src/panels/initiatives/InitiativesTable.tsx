"use client";
// Panel: Initiatives ranked by Spend. Owner: 06. GET /api/initiatives
import Link from "next/link";
import { Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import { WASTE_PATTERN_LABEL, type InitiativeList } from "@/lib/contract";

export default function InitiativesTable() {
  const { data, error, loading } = useApi<InitiativeList>("/api/initiatives");
  return (
    <Panel title="Initiatives by Spend" source={data?.source} loading={loading} error={error}>
      <table className="table">
        <thead>
          <tr><th>Initiative</th><th>Business Function</th><th>Sessions</th><th>Spend</th><th>Measured Waste</th><th>Estimated Saving</th><th>Top Waste Pattern</th></tr>
        </thead>
        <tbody>
          {data?.items.map((r) => (
            <tr key={r.initiative_id}>
              <td><Link href={`/initiatives/${r.initiative_id}`}>{r.name}</Link></td>
              <td>{r.business_function ?? "—"}</td>
              <td>{r.session_count}</td>
              <td><Money value={r.spend} size="sm" /></td>
              <td><Money value={r.measured_waste} size="sm" /></td>
              <td><Money value={r.estimated_saving} size="sm" /></td>
              <td>{r.top_waste_pattern ? WASTE_PATTERN_LABEL[r.top_waste_pattern] : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
