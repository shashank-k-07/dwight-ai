"use client";
// Panel: Recommendations. Owner: 09 (12: Draft link, 13: measured drop, 14: policy link).
// GET /api/initiatives/{id}/recommendations
import Link from "next/link";
import { Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import type { RecommendationList } from "@/lib/contract";

export default function Recommendations({ initiativeId }: { initiativeId: string }) {
  const { data, error, loading } = useApi<RecommendationList>(`/api/initiatives/${initiativeId}/recommendations`);
  return (
    <Panel title="Recommendations" source={data?.source} loading={loading} error={error}>
      {data?.items.map((r) => (
        <article key={r.recommendation_id} className="rec">
          <div className="rec-head">
            <h3>{r.title}</h3>
            <Money value={r.saving} />
          </div>
          <p className="small muted">Practice: {r.practice.title} <code>{r.practice.practice_id}</code></p>
          <p>{r.body}</p>
          <p className="small">Infra: {r.infra_refs.map((x) => <span key={x} className="chip">{x}</span>)}</p>
          {r.measured_drop && (
            <p className="small">Before/after runs: {r.measured_drop.token_drop_pct.toFixed(0)}% fewer tokens, <Money value={r.measured_drop.spend_drop} size="sm" /> less Spend
              {!r.measured_drop.counts && " (task success dropped: doesn't count)"}</p>
          )}
          {r.draft_id && <p className="small"><a href={`#draft-${r.draft_id}`}>View Draft</a></p>}
          {r.policy_prefill && (
            <p className="small"><Link href={`/policy?team=${encodeURIComponent(r.policy_prefill.team)}&models=${encodeURIComponent(r.policy_prefill.allowed_models.join(","))}`}>Apply as Policy</Link></p>
          )}
        </article>
      ))}
    </Panel>
  );
}
