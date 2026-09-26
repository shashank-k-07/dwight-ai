"use client";
// Panel: before/after proof. Owner: 13. Hidden when the Initiative has no experiment runs.
// GET /api/initiatives/{id}/before-after
import { Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import type { BeforeAfter as BA, ExperimentTotals } from "@/lib/contract";

function Col({ label, t }: { label: string; t: ExperimentTotals }) {
  return (
    <div className="stat">
      <div className="stat-label">{label} ({t.session_count} Sessions)</div>
      <div>{Math.round(t.avg_tokens).toLocaleString()} tokens / Session</div>
      <div><Money value={t.spend} size="sm" /></div>
      <div>{t.tasks_passed}/{t.tasks_total} tasks passed</div>
    </div>
  );
}

export default function BeforeAfter({ initiativeId }: { initiativeId: string }) {
  const { data, error, loading } = useApi<BA>(`/api/initiatives/${initiativeId}/before-after`);
  if (data && !data.has_runs) return null;
  return (
    <Panel title="Before / after the Draft" source={data?.source} loading={loading} error={error}>
      {data?.before && data.after && (
        <>
          <div className="stats"><Col label="Before" t={data.before} /><Col label="After" t={data.after} /></div>
          {data.success_held ? (
            <p><strong>{data.token_drop_pct?.toFixed(0)}% fewer tokens</strong>{data.spend_drop && <> · <Money value={data.spend_drop} /> less Spend</>}</p>
          ) : (
            <p className="panel-error">Task success dropped, so this result doesn&apos;t count.</p>
          )}
        </>
      )}
    </Panel>
  );
}
