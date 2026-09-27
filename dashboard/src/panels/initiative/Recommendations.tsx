"use client";
// Panel: Recommendations, the visual focus of Initiative detail. Owner: 09 (12: Draft link,
// 13: measured drop, 14: policy link; demo feedback: prominence, Team highlight, "Implement").
// GET /api/initiatives/{id}/recommendations, /api/initiatives/{id}, /api/initiatives/{id}/before-after,
// and with ?team=: /api/recommendations (the Team's own Recommendations).
// Simulation, per viewer (lib/simulation.ts; nothing is written anywhere):
//   * "Implement" applies a Recommendation's fix (no numbers yet);
//   * "Apply fixes" (components/ApplyFixes.tsx) runs the simulation over this Initiative's applied
//     fixes and shows Spend before -> after and the money saved, labelled Simulated · Estimated.
//   * Team-wide fixes count in the Overview simulation; Policy Recommendations aren't simulated:
//     "Apply as Policy" writes the real gateway config.
// The first Draft Recommendation also carries the live agent run (LiveAgentRun.tsx): real, Measured.
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { Info, Money } from "@/components/Money";
import { useApi } from "@/lib/api";
import type { BeforeAfter, Initiative, Recommendation, RecommendationList } from "@/lib/contract";
import { isSimulatable, shareOf, useSimulation } from "@/lib/simulation";
import ApplyFixes from "@/components/ApplyFixes";
import LiveAgentRun from "@/panels/initiative/LiveAgentRun";

// Minimal markdown for Recommendation bodies: paragraphs, "- " lists, **bold**, `code`.
// Rendered as React nodes (no HTML injection).
function inline(text: string, key: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={`${key}-${i}`}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return <code key={`${key}-${i}`}>{part.slice(1, -1)}</code>;
    return part;
  });
}

function MarkdownBody({ source, collapsed }: { source: string; collapsed: boolean }) {
  const blocks = source.trim().split(/\n\s*\n/);
  return (
    <>
      {(collapsed ? blocks.slice(0, 1) : blocks).map((block, b) => {
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

/** The real before/after runs, when this Recommendation's Draft was what the after runs loaded. */
const measuredProof = (r: Recommendation, ba: BeforeAfter | null) =>
  r.measured_drop?.counts && ba?.has_runs && ba.success_held && ba.before && ba.after ? ba : null;

function RecommendationCard({ r, rank, initiativeId, scope, live }: {
  r: Recommendation; rank?: number; initiativeId: string; scope?: string; live?: boolean;
}) {
  const sim = useSimulation();
  const [open, setOpen] = useState(false);
  const href = policyHref(r);
  const done = sim.isApplied(r.recommendation_id);
  const long = r.body.trim().split(/\n\s*\n/).length > 1;
  return (
    <article className={`rec-card${rank === 0 ? " rec-top" : ""}${done ? " rec-done" : ""}`}>
      <div className="rec-main">
        <p className="rec-kicker">
          {rank === 0 ? <span className="badge badge-top">Recommended first</span> : rank != null && <span className="muted">#{rank + 1}</span>}
          {scope && <span className="chip">{scope}</span>}
          <span className="chip chip-practice" title={`Practice Library: ${r.practice.practice_id}`}>
            Practice · <strong>{r.practice.title}</strong>
          </span>
        </p>
        <h3>{r.title}</h3>
        <div className="rec-body">
          <MarkdownBody source={r.body} collapsed={long && !open} />
          {long && (
            <button type="button" className="linklike small" onClick={() => setOpen((v) => !v)}>
              {open ? "Show less" : "Read the whole Recommendation"}
            </button>
          )}
        </div>
        {r.infra_refs.length > 0 && <p className="small">Infra Profile: {r.infra_refs.map((x) => <InfraRef key={x} refId={x} />)}</p>}
        {live && <LiveAgentRun recommendationId={r.recommendation_id} />}
        {done && (
          <p className="fix-applied small">
            <strong>✓ Fix applied</strong> <span className="badge badge-sim">Simulation</span>{" "}
            {r.target_type === "initiative"
              ? <>Press <a href={`#applied-fixes-${initiativeId}`}>Apply fixes</a> to see the money saved.</>
              : <>Team-wide, so it&apos;s counted in the Overview simulation.</>}{" "}
            <button type="button" className="linklike" onClick={() => sim.undo(r.recommendation_id)}>Undo</button>
          </p>
        )}
      </div>
      <aside className="rec-side">
        <div className="stat-label">{r.saving.kind === "measured" ? "Measured Waste it removes" : "Estimated Saving"}</div>
        <Money value={r.saving} size="lg" />
        <div className="rec-actions">
          {isSimulatable(r) && (done ? (
            <button type="button" className="button button-done" onClick={() => sim.undo(r.recommendation_id)} title="Un-apply this fix">
              ✓ Fix applied
            </button>
          ) : (
            <button type="button" className="button button-cta" onClick={() => sim.apply(r, initiativeId)}
              title="Apply this fix in the simulation, then press Apply fixes to see the money saved">
              Implement
            </button>
          ))}
          {href && (
            <Link className={`button ${isSimulatable(r) ? "button-quiet" : "button-cta"}`} href={href}
              title="Writes the real gateway config on the Policy screen">Apply as Policy</Link>
          )}
          {r.draft_id && <a className="button button-quiet" href={`#draft-${r.draft_id}`}>View Draft</a>}
        </div>
      </aside>
    </article>
  );
}

export default function Recommendations({ initiativeId, team }: { initiativeId: string; team?: string | null }) {
  const { data, error, loading } = useApi<RecommendationList>(`/api/initiatives/${initiativeId}/recommendations`);
  const initiative = useApi<Initiative>(`/api/initiatives/${initiativeId}`);
  const hasDrop = !!data?.items.some((r) => r.measured_drop);
  const ba = useApi<BeforeAfter>(hasDrop ? `/api/initiatives/${initiativeId}/before-after` : null);
  const all = useApi<RecommendationList>(team ? "/api/recommendations" : null);
  const sim = useSimulation();

  const items = data?.items ?? [];
  const spend = initiative.data?.spend ?? null;
  const teamRecs = team
    ? (all.data?.items ?? []).filter((r) => (r.target_type === "team" || r.target_type === "policy") && r.target_id === team)
    : [];
  const teamHere = initiative.data?.teams?.find((t) => t.team === team);
  const doneHere = items.filter((r) => sim.isApplied(r.recommendation_id));
  const ranHere = !!sim.runFor(initiativeId, doneHere);
  const proof = items.map((r) => measuredProof(r, ba.data)).find(Boolean) ?? null;
  // The live agent run sits on the first Draft Recommendation: the run loads all of the Initiative's Drafts.
  const liveRec = items.find((r) => r.target_type === "initiative" && r.draft_id)?.recommendation_id;

  return (
    <section className="panel rec-panel" id="recommendations">
      <header className="panel-head">
        <h2>
          Recommendations {items.length > 0 && <span className="muted">({items.length})</span>}
          <Info>In Dwight&apos;s recommended order. Each applies a Practice from Dwight&apos;s Practice Library to this Initiative and the Infra Profile. Dollar figures come from the Waste findings in code, never from the model. Press Implement to apply a fix, then Apply fixes to see the money saved (a simulation).</Info>
        </h2>
        <div className="panel-actions">
          {data?.source === "fixture" && <span className="badge badge-fixture">fixture data</span>}
          {sim.count > 0 && <button type="button" className="button button-quiet" onClick={sim.reset}>Reset simulation</button>}
        </div>
      </header>
      {error ? <p className="panel-error">Couldn&apos;t load: {error}</p> : loading ? <p className="muted">Loading…</p> : (
        <>
          {items.length === 0 ? (
            <p className="muted">No Recommendations yet: this Initiative has no Waste or Recurring Discovery to fix.</p>
          ) : (
            proof && (
              <p className="small rec-intro">
                Proven on real runs: the Draft cut tokens per Session by <strong>−{proof.token_drop_pct?.toFixed(1)}%</strong>
                {proof.spend_drop && <> (<Money value={proof.spend_drop} size="sm" /> less Spend)</>}, task success held.{" "}
                <a href="#before-after">See before / after</a>
              </p>
            )
          )}

          <ApplyFixes scope={initiativeId} base={spend} baseLabel="Initiative Spend" sessions={initiative.data?.session_count}
            recs={doneHere} proofHref={() => "#before-after"} />

          {team && (
            <div className="team-recs">
              <h3>For Team {team}</h3>
              <p className="small muted">
                {teamHere
                  ? <>{team} ran {teamHere.session_count.toLocaleString()} of this Initiative&apos;s Sessions (<Money value={teamHere.spend} size="sm" />
                    {spend ? `, ${shareOf(teamHere.spend, spend).toFixed(0)}% of its Spend` : ""}). The Initiative Recommendations below apply to every Team on it, including {team}.</>
                  : <>{team} has no Sessions in this Initiative.</>}
              </p>
              {all.loading && <p className="muted small">Loading…</p>}
              {!all.loading && teamRecs.length === 0 && <p className="small muted">No Team-wide Recommendations for {team}.</p>}
              {teamRecs.map((r) => (
                <RecommendationCard key={r.recommendation_id} r={r} initiativeId={initiativeId}
                  scope={r.target_type === "policy" ? `Policy for ${team}` : `Team-wide: ${team}`} />
              ))}
            </div>
          )}

          {items.map((r, i) => (
            <RecommendationCard key={r.recommendation_id} r={r} rank={i} initiativeId={initiativeId}
              live={r.recommendation_id === liveRec} />
          ))}

          {doneHere.length > 0 && !ranHere && (
            <div className="fixes-sticky" role="status">
              <span><strong>{doneHere.length} {doneHere.length === 1 ? "fix" : "fixes"} applied</strong> <span className="badge badge-sim">Simulation</span></span>
              <a className="button button-cta" href={`#applied-fixes-${initiativeId}`}>Apply fixes ↑</a>
            </div>
          )}
        </>
      )}
    </section>
  );
}
