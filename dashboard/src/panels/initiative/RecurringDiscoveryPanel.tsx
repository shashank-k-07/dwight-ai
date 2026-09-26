"use client";
// Panel: Recurring Discovery (common path + repeated Discovery). Owner: 10 (data from 10 + 11).
// GET /api/initiatives/{id}/recurring-discoveries
import { Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import type { RecurringDiscoveries } from "@/lib/contract";

export default function RecurringDiscoveryPanel({ initiativeId }: { initiativeId: string }) {
  const { data, error, loading } = useApi<RecurringDiscoveries>(`/api/initiatives/${initiativeId}/recurring-discoveries`);
  return (
    <Panel title="Recurring Discovery" source={data?.source} loading={loading} error={error}>
      {data && data.items.length === 0 && <p className="muted">No Recurring Discovery found.</p>}
      {data?.items.map((rd) => (
        <div key={rd.recurring_discovery_id} className="rd">
          {rd.form === "common_path" ? (
            <>
              <p><strong>{rd.session_count} of {data.initiative_session_count} Sessions</strong> read these {rd.resources.length} docs
                {rd.tokens ? ` (${(rd.tokens / 1000).toFixed(0)}K tokens)` : ""} to get started.</p>
              <ul>{rd.resources.map((r) => <li key={r.resource_id}><code>{r.resource_id}</code></li>)}</ul>
            </>
          ) : (
            <p>“{rd.statement}” was <strong>found separately in {rd.session_count} Sessions</strong>.</p>
          )}
          <p className="small">What the repetition cost: <Money value={rd.cost} size="sm" /></p>
        </div>
      ))}
    </Panel>
  );
}
