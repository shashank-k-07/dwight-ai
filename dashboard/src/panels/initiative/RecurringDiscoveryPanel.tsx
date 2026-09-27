"use client";
// Panel: Recurring Discovery (common path + repeated Discovery). Owner: 10 (data from 10 + 11).
// GET /api/initiatives/{id}/recurring-discoveries
// Both costs are Measured. The repeated-Discovery cost arrives with note "conservative upper bound",
// which <Money> renders next to the label.
import { Info, Money } from "@/components/Money";
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
        {rd.tokens ? ` (${tokensK(rd.tokens)} tokens)` : ""} to get started.
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
        Cost of reading them: <Money value={rd.cost} size="sm" />
      </p>
    </>
  );
}

function RepeatedDiscovery({ rd, of }: { rd: RecurringDiscoveryItem; of: number }) {
  return (
    <>
      <p>
        “{rd.statement}” was <strong>found separately in {rd.session_count} Sessions</strong>
        <span className="muted small"> of {of} ({pct(rd.session_share)})</span>
      </p>
      <p className="small">
        Cost of finding it each time: <Money value={rd.cost} size="sm" />
        <Info>Spend up to the Call where it was found, summed over those Sessions.</Info>
      </p>
    </>
  );
}

export default function RecurringDiscoveryPanel({ initiativeId }: { initiativeId: string }) {
  const { data, error, loading } = useApi<RecurringDiscoveries>(`/api/initiatives/${initiativeId}/recurring-discoveries`);
  if (data && data.items.length === 0) return null;
  return (
    <Panel title="Recurring Discovery" source={data?.source} loading={loading} error={error}>
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
