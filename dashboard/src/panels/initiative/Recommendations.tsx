"use client";
// Panel: Recommendations. Owner: 09 (12: Draft link, 13: measured drop, 14: policy link).
// GET /api/initiatives/{id}/recommendations
import Link from "next/link";
import type { ReactNode } from "react";
import { Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import type { Recommendation, RecommendationList } from "@/lib/contract";

// Minimal markdown for Recommendation bodies: paragraphs, "- " lists, **bold**, `code`.
// Rendered as React nodes (no HTML injection).
function inline(text: string, key: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={`${key}-${i}`}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return <code key={`${key}-${i}`}>{part.slice(1, -1)}</code>;
    return part;
  });
}

function MarkdownBody({ source }: { source: string }) {
  const blocks = source.trim().split(/\n\s*\n/);
  return (
    <>
      {blocks.map((block, b) => {
        const lines = block.split("\n").filter((l) => l.trim());
        if (lines.length && lines.every((l) => /^\s*[-*]\s+/.test(l))) {
          return <ul key={b}>{lines.map((l, i) => <li key={i}>{inline(l.replace(/^\s*[-*]\s+/, ""), `${b}-${i}`)}</li>)}</ul>;
        }
        return <p key={b}>{inline(lines.join(" "), `${b}`)}</p>;
      })}
    </>
  );
}

// Infra Profile refs look like "mcp:perch-docs-mcp"; show the name, keep the ref as a tooltip.
function InfraRef({ refId }: { refId: string }) {
  const i = refId.indexOf(":");
  const kind = i > 0 ? refId.slice(0, i) : "";
  const name = i > 0 ? refId.slice(i + 1) : refId;
  return <span className="chip" title={refId}>{kind && <span className="muted">{kind} </span>}{name}</span>;
}

function policyHref(r: Recommendation): string | null {
  if (!r.policy_prefill) return null;
  const q = new URLSearchParams({
    team: r.policy_prefill.team,
    models: r.policy_prefill.allowed_models.join(","),
    recommendation: r.recommendation_id,
  });
  return `/policy?${q.toString()}`;
}

function RecommendationCard({ r }: { r: Recommendation }) {
  const href = policyHref(r);
  return (
    <article className="rec">
      <div className="rec-head">
        <h3>{r.title}</h3>
        <Money value={r.saving} />
      </div>
      <p className="small muted">
        Practice: <strong>{r.practice.title}</strong> <code>{r.practice.practice_id}</code>
      </p>
      <MarkdownBody source={r.body} />
      <p className="small">Infra Profile: {r.infra_refs.map((x) => <InfraRef key={x} refId={x} />)}</p>
      {r.measured_drop && (
        r.measured_drop.counts ? (
          <p className="small">
            Before/after runs: {r.measured_drop.token_drop_pct.toFixed(0)}% fewer tokens,{" "}
            <Money value={r.measured_drop.spend_drop} size="sm" /> less Spend
          </p>
        ) : (
          <p className="small muted">Before/after runs: task success dropped, so the result doesn&apos;t count.</p>
        )
      )}
      {(r.draft_id || href) && (
        <p className="small">
          {r.draft_id && <a href={`#draft-${r.draft_id}`}>View Draft</a>}
          {r.draft_id && href && " · "}
          {href && <Link href={href}>Apply as Policy</Link>}
        </p>
      )}
    </article>
  );
}

export default function Recommendations({ initiativeId }: { initiativeId: string }) {
  const { data, error, loading } = useApi<RecommendationList>(`/api/initiatives/${initiativeId}/recommendations`);
  return (
    <Panel title="Recommendations" source={data?.source} loading={loading} error={error}>
      {data && data.items.length === 0 && (
        <p className="muted">No Recommendations yet: this Initiative has no Waste or Recurring Discovery to fix.</p>
      )}
      {data?.items.map((r) => <RecommendationCard key={r.recommendation_id} r={r} />)}
    </Panel>
  );
}
