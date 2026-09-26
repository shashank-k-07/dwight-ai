"use client";
// Panel: Initiatives ranked by Spend. Owner: 06. GET /api/initiatives
// Spend is Measured; Waste is split into Measured Waste and Estimated Saving, each labelled by <Money>.
import Link from "next/link";
import { Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import { WASTE_PATTERN_LABEL, type InitiativeList } from "@/lib/contract";

export default function InitiativesTable() {
  const { data, error, loading } = useApi<InitiativeList>("/api/initiatives");
  const items = data?.items ?? [];
  const sessions = items.reduce((n, r) => n + r.session_count, 0);
  return (
    <Panel title="Initiatives by Spend" source={data?.source} loading={loading} error={error}>
      {data && items.length === 0 ? (
        <p className="muted">No classified Sessions yet. Run the classify stage to attribute Spend to Initiatives.</p>
      ) : (
        <>
          <table className="table">
            <thead>
              <tr>
                <th>#</th>
                <th>Initiative</th>
                <th>Business Function</th>
                <th>Sessions</th>
                <th>Spend</th>
                <th>Measured Waste</th>
                <th>Estimated Saving</th>
                <th>Top Waste Pattern</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r, i) => (
                <tr key={r.initiative_id}>
                  <td className="muted">{i + 1}</td>
                  <td><Link href={`/initiatives/${r.initiative_id}`}>{r.name}</Link></td>
                  <td>{r.business_function ?? "—"}</td>
                  <td>{r.session_count.toLocaleString()}</td>
                  <td><Money value={r.spend} size="sm" /></td>
                  <td><Money value={r.measured_waste} size="sm" /></td>
                  <td><Money value={r.estimated_saving} size="sm" /></td>
                  <td>{r.top_waste_pattern ? WASTE_PATTERN_LABEL[r.top_waste_pattern] : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data && (
            <p className="muted small">
              {items.length} Initiatives · {sessions.toLocaleString()} Sessions. Initiatives are inferred from each
              Session&apos;s content; raw prompts are discarded after classification.
            </p>
          )}
        </>
      )}
    </Panel>
  );
}
