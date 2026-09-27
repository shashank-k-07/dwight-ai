"use client";
// Panel: Recurring Discovery (common path + repeated Discovery). Owner: 10 (data from 10 + 11).
// GET /api/initiatives/{id}/recurring-discoveries
// Both costs are Measured. The repeated-Discovery cost arrives with note "conservative upper bound",
// which <Money> renders next to the label.
import { Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import type { RecurringDiscoveries, RecurringDiscoveryItem } from "@/lib/contract";

function tokensK(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}K` : String(n);
}

function pct(share: number): string {
  return `${Math.round(share * 100)}%`;
}

function CommonPath({ rd, of }: { rd: RecurringDiscoveryItem; of: number }) {
  const n = rd.resources.length;
  return (
    <>
      <p>
        <strong>{rd.session_count} of {of} Sessions</strong> read {n === 1 ? "this doc" : `these ${n} docs`}
        {rd.tokens ? ` (${tokensK(rd.tokens)} tokens per read of the path)` : ""} to get started.
        <span className="muted small"> Common path · {pct(rd.session_share)} of Sessions</span>
      </p>
      <ul>
        {rd.resources.map((r) => (
          <li key={r.resource_id}>
            <code>{r.resource_id}</code>
            {r.tokens ? <span className="muted small"> {tokensK(r.tokens)} tokens</span> : null}
          </li>
        ))}
      </ul>
      <p className="small">
        What reading them cost: <Money value={rd.cost} size="sm" />
      </p>
    </>
  );
}

function RepeatedDiscovery({ rd, of }: { rd: RecurringDiscoveryItem; of: number }) {
  return (
    <>
      <p>
        “{rd.statement}” was <strong>found separately in {rd.session_count} Sessions</strong>
        <span className="muted small"> ({rd.session_count} of {of} · {pct(rd.session_share)})</span>
      </p>
      <p className="small">
        Spend up to the Call where it was found: <Money value={rd.cost} size="sm" />
      </p>
    </>
  );
}

export default function RecurringDiscoveryPanel({ initiativeId }: { initiativeId: string }) {
  const { data, error, loading } = useApi<RecurringDiscoveries>(`/api/initiatives/${initiativeId}/recurring-discoveries`);
  return (
    <Panel title="Recurring Discovery" source={data?.source} loading={loading} error={error}>
      {data && data.items.length === 0 && <p className="muted">No Recurring Discovery found.</p>}
      {data?.items.map((rd) => (
        <div key={rd.recurring_discovery_id} className="rd">
          {rd.form === "common_path" ? (
            <CommonPath rd={rd} of={data.initiative_session_count} />
          ) : (
            <RepeatedDiscovery rd={rd} of={data.initiative_session_count} />
          )}
        </div>
      ))}
    </Panel>
  );
}
