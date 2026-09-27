"use client";
// Panel: Recommendations, the visual focus of Initiative detail. Owner: 09 (12: Draft link,
// 13: measured drop, 14: policy link; demo feedback: prominence, Team highlight, "Implement").
// GET /api/initiatives/{id}/recommendations, /api/initiatives/{id}, /api/initiatives/{id}/before-after,
// and with ?team=: /api/recommendations + /api/overview (the Team's own Recommendations and Spend).
// "Implement" is a per-viewer simulation (lib/simulation.ts): nothing is written anywhere.
//   * A Draft Recommendation whose before/after runs held task success shows those real runs,
//     labelled Measured (13/16), plus the simulated projection for the whole Initiative.
//   * Every other one shows Spend before -> projected after, labelled Simulated · Estimated.
//   * Policy Recommendations aren't simulated: "Apply as Policy" writes the real gateway config.
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { Info, Money } from "@/components/Money";
import { useApi } from "@/lib/api";
import type { BeforeAfter, Initiative, Money as MoneyT, Overview, Recommendation, RecommendationList } from "@/lib/contract";
import { isSimulatable, project, shareOf, useSimulation, type Projection } from "@/lib/simulation";
import { SavingSources } from "@/panels/overview/SimulationImpact";

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

const tokens = (n: number) => Math.round(n).toLocaleString("en-US");
const SimBadge = () => <span className="badge badge-sim">Simulated · Estimated</span>;

/** The real before/after runs, when this Recommendation's Draft was what the after runs loaded. */
const measuredProof = (r: Recommendation, ba: BeforeAfter | null) =>
  r.measured_drop?.counts && ba?.has_runs && ba.success_held && ba.before && ba.after ? ba : null;

function ProjectionView({ p, baseLabel }: { p: Projection; baseLabel: string }) {
  return (
    <div className="sim-flow sim-flow-sm">
      <div>
        <div className="stat-label">{baseLabel}</div>
        <Money value={p.before} />
      </div>
      <div className="sim-arrow" aria-hidden>→</div>
      <div>
        <div className="stat-label">Projected (simulated)</div>
        <Money value={p.after} />
      </div>
      <div>
        <div className="stat-label">Saving</div>
        <Money value={p.saving} /> <span className="muted small">−{shareOf(p.saving, p.before).toFixed(1)}%</span>
      </div>
    </div>
  );
}

function ImplementResult({ r, base, baseLabel, ba, onUndo }: {
  r: Recommendation; base: MoneyT | null; baseLabel: string; ba: BeforeAfter | null; onUndo: () => void;
}) {
  const proof = measuredProof(r, ba);
  const p = base ? project(base, [r]) : null;
  return (
    <div className="sim-result">
      {proof && proof.before && proof.after && (
        <div className="measured-result">
          <p className="sim-result-head"><strong>What actually happened</strong> <span className="muted small">the same {proof.after.tasks_total} tasks, without then with the Draft</span></p>
          <div className="sim-flow sim-flow-sm">
            <div><div className="stat-label">Tokens / Session</div>{tokens(proof.before.avg_tokens)} → <strong>{tokens(proof.after.avg_tokens)}</strong></div>
            <div><div className="stat-label">Token drop</div><strong>−{proof.token_drop_pct?.toFixed(1)}%</strong></div>
            <div><div className="stat-label">Spend on those runs</div><Money value={proof.before.spend} size="sm" /> → <Money value={proof.after.spend} size="sm" /></div>
            <div><div className="stat-label">Tasks passed</div>{proof.before.tasks_passed}/{proof.before.tasks_total} → {proof.after.tasks_passed}/{proof.after.tasks_total}</div>
          </div>
        </div>
      )}
      <p className="sim-result-head">
        <strong>{proof ? "Projected for the whole Initiative" : "If this had been in place"}</strong> <SimBadge />
      </p>
      {p ? <ProjectionView p={p} baseLabel={baseLabel} /> : <p className="muted small">Loading…</p>}
      {p && <SavingSources p={p} />}
      <p className="small muted">
        Simulation only, in this browser: Dwight changed nothing
        <Info>{`The Spend above minus this Recommendation's own ${r.saving.kind === "measured" ? "Measured Waste" : "Estimated Saving"}, for the same Sessions.`}</Info>
        {" "}· <button type="button" className="linklike" onClick={onUndo}>Undo</button>
      </p>
    </div>
  );
}

function RecommendationCard({ r, rank, initiativeId, base, baseLabel, ba, scope }: {
  r: Recommendation; rank?: number; initiativeId: string; base: MoneyT | null; baseLabel: string;
  ba: BeforeAfter | null; scope?: string;
}) {
  const sim = useSimulation();
  const [open, setOpen] = useState(false);
  const href = policyHref(r);
  const done = sim.isImplemented(r.recommendation_id);
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
        {done && <ImplementResult r={r} base={base} baseLabel={baseLabel} ba={ba} onUndo={() => sim.undo(r.recommendation_id)} />}
      </div>
      <aside className="rec-side">
        <div className="stat-label">{r.saving.kind === "measured" ? "Measured Waste it removes" : "Estimated Saving"}</div>
        <Money value={r.saving} size="lg" />
        <div className="rec-actions">
          {isSimulatable(r) && (done ? (
            <button type="button" className="button button-done" onClick={() => sim.undo(r.recommendation_id)} title="Undo this simulated implementation">
              ✓ Implemented (simulated)
            </button>
          ) : (
            <button type="button" className="button button-cta" onClick={() => sim.implement(r, initiativeId)}>
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
  const overview = useApi<Overview>(team ? "/api/overview" : null);
  const sim = useSimulation();

  const items = data?.items ?? [];
  const spend = initiative.data?.spend ?? null;
  const teamRecs = team
    ? (all.data?.items ?? []).filter((r) => (r.target_type === "team" || r.target_type === "policy") && r.target_id === team)
    : [];
  const teamSpend = team
    ? overview.data?.spend_by_business_function.flatMap((bf) => bf.teams).find((t) => t.team === team)?.spend ?? null
    : null;
  const teamHere = initiative.data?.teams?.find((t) => t.team === team);
  const doneHere = items.filter((r) => sim.isImplemented(r.recommendation_id));
  const combined = spend && doneHere.length > 1 ? project(spend, doneHere) : null;
  const proof = items.map((r) => measuredProof(r, ba.data)).find(Boolean) ?? null;

  return (
    <section className="panel rec-panel" id="recommendations">
      <header className="panel-head">
        <h2>
          Recommendations {items.length > 0 && <span className="muted">({items.length})</span>}
          <Info>In Dwight&apos;s recommended order. Each applies a Practice from Dwight&apos;s Practice Library to this Initiative and the Infra Profile. Dollar figures come from the Waste findings in code, never from the model. Press Implement to simulate the result.</Info>
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
                <RecommendationCard key={r.recommendation_id} r={r} initiativeId={initiativeId} base={teamSpend}
                  baseLabel={`${team} Spend, all Initiatives`} ba={null}
                  scope={r.target_type === "policy" ? `Policy for ${team}` : `Team-wide: ${team}`} />
              ))}
            </div>
          )}

          {combined && (
            <div className="sim-result sim-combined">
              <p className="sim-result-head"><strong>{doneHere.length} implemented on this Initiative</strong> <SimBadge /></p>
              <ProjectionView p={combined} baseLabel="Initiative Spend" />
              <SavingSources p={combined} />
              <p className="small muted">
                Recommendations that fix the same Waste count once{combined.overlapping ? ` (${combined.overlapping} not added again)` : ""};
                different ones can still overlap, so this is an upper bound.
              </p>
            </div>
          )}

          {items.map((r, i) => (
            <RecommendationCard key={r.recommendation_id} r={r} rank={i} initiativeId={initiativeId} base={spend}
              baseLabel="Initiative Spend" ba={ba.data} />
          ))}
        </>
      )}
    </section>
  );
}
