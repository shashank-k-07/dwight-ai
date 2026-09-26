"use client";
// Panel: Policy editor + rendered gateway config. Owner: 14.
// GET /api/policy/options, POST /api/policy/render, POST /api/policy/apply, GET /api/policies,
// GET /api/recommendations?target_type=policy (policy Recommendations to prefill from).
// Prefill: /policy?team=<Team>&models=a,b (from a policy Recommendation's policy_prefill),
// optionally &recommendation=<id> to show which Recommendation it came from.
// Dwight renders and writes the config; the Customer's gateway enforces it (ADR 0002).
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { apiPost, useApi } from "@/lib/api";
import type { Policy, PolicyList, PolicyOptions, PolicyRender, Recommendation, RecommendationList } from "@/lib/contract";

function splitModels(s: string | null): string[] {
  return (s ?? "").split(",").map((x) => x.trim()).filter(Boolean);
}

export default function PolicyEditor() {
  const params = useSearchParams();
  const { data, error, loading } = useApi<PolicyOptions>("/api/policy/options");
  const recs = useApi<RecommendationList>("/api/recommendations?target_type=policy");
  const history = useApi<PolicyList>("/api/policies");

  const [team, setTeam] = useState(params.get("team") ?? "");
  const [models, setModels] = useState<string[]>(splitModels(params.get("models")));
  const [fromRec, setFromRec] = useState<string | null>(params.get("recommendation"));
  const [render, setRender] = useState<PolicyRender | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [applied, setApplied] = useState<Policy | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  // Policy Recommendations that carry a prefill (the fixture ignores the target_type filter).
  const policyRecs = useMemo(
    () => (recs.data?.items ?? []).filter((r): r is Recommendation & { policy_prefill: NonNullable<Recommendation["policy_prefill"]> } => !!r.policy_prefill),
    [recs.data],
  );
  const knownModels = useMemo(() => new Set(data?.models.map((m) => m.model) ?? []), [data]);
  const unknownModels = models.filter((m) => data && !knownModels.has(m));
  const chosen = models.filter((m) => knownModels.has(m));

  // Once options load: match the prefilled Team by name or id, or default to the first Team.
  useEffect(() => {
    if (!data?.teams.length) return;
    const match = data.teams.find((t) => t.team.toLowerCase() === team.toLowerCase())
      ?? data.teams.find((t) => t.team.toLowerCase().replace(/[^a-z0-9]+/g, "-") === team.toLowerCase());
    if (!match) setTeam(data.teams[0].team);
    else if (match.team !== team) setTeam(match.team);
  }, [data, team]);

  useEffect(() => {
    if (!team || !data) return;
    let live = true;
    apiPost<PolicyRender>("/api/policy/render", { team, allowed_models: chosen })
      .then((r) => live && (setRender(r), setRenderError(null)))
      .catch((e) => live && (setRender(null), setRenderError(String(e.message || e))));
    setApplied(null);
    setApplyError(null);
    return () => {
      live = false;
    };
  }, [team, chosen.join(","), data]);

  const toggle = (m: string) => {
    setFromRec(null);
    setModels((cur) => (cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m]));
  };
  const prefill = (r: Recommendation) => {
    if (!r.policy_prefill) return;
    setTeam(r.policy_prefill.team);
    setModels(r.policy_prefill.allowed_models);
    setFromRec(r.recommendation_id);
  };
  const apply = () => {
    setApplying(true);
    apiPost<Policy>("/api/policy/apply", { team, allowed_models: chosen })
      .then((p) => (setApplied(p), setApplyError(null), history.reload()))
      .catch((e) => setApplyError(String(e.message || e)))
      .finally(() => setApplying(false));
  };
  const canApply = !applying && chosen.length > 0 && !renderError;
  const sourceRec = policyRecs.find((r) => r.recommendation_id === fromRec);

  // Arrived via a Recommendation's "Apply as Policy" link (team + models, no id): say which one.
  useEffect(() => {
    if (fromRec || !params.get("team")) return;
    const want = [...splitModels(params.get("models"))].sort().join(",");
    const hit = policyRecs.find((r) => r.policy_prefill.team.toLowerCase() === (params.get("team") ?? "").toLowerCase()
      && [...r.policy_prefill.allowed_models].sort().join(",") === want);
    if (hit) setFromRec(hit.recommendation_id);
    // Only on first load of the Recommendations.
  }, [policyRecs]);

  return (
    <>
      <Panel title="Policy" source={data?.source} loading={loading} error={error}>
        {data && (
          <div className="policy">
            <p className="small muted">
              A Policy limits which models a Team&apos;s Agents may use. Dwight writes it as a LiteLLM team model
              allowlist; your gateway enforces it. Dwight doesn&apos;t sit in the request path.
            </p>
            {sourceRec && (
              <p className="small">
                Prefilled from Recommendation <strong>{sourceRec.title}</strong> <Money value={sourceRec.saving} size="sm" />
              </p>
            )}
            <label>Team{" "}
              <select value={team} onChange={(e) => (setTeam(e.target.value), setFromRec(null))}>
                {data.teams.map((t) => <option key={t.team} value={t.team}>{t.team} ({t.business_function})</option>)}
              </select>
            </label>
            <fieldset>
              <legend>Allowed models (Infra Profile tiers)</legend>
              {data.models.map((m) => (
                <label key={m.model} className="check">
                  <input type="checkbox" checked={models.includes(m.model)} onChange={() => toggle(m.model)} /> {m.model}{" "}
                  <span className="muted small">{m.tier}</span>
                </label>
              ))}
              {unknownModels.length > 0 && (
                <p className="small muted">Not in the Infra Profile, left out: {unknownModels.join(", ")}</p>
              )}
            </fieldset>
            <h3>Gateway config (LiteLLM) {render?.source === "fixture" && <span className="badge badge-fixture">fixture data</span>}</h3>
            {renderError ? <p className="panel-error">Couldn&apos;t render: {renderError}</p> : <pre className="markdown">{render?.rendered_config ?? "…"}</pre>}
            <button className="button" onClick={apply} disabled={!canApply} style={canApply ? undefined : { opacity: 0.5, cursor: "not-allowed" }}>
              {applying ? "Applying…" : "Apply"}
            </button>
            {chosen.length === 0 && <span className="small muted"> Choose at least one model (an empty LiteLLM allowlist allows every model).</span>}
            {applyError && <p className="panel-error">Couldn&apos;t apply: {applyError}</p>}
            {applied && (
              <p className="small">
                Policy <code>{applied.policy_id}</code> for {applied.team} written to <code>{applied.output_path}</code>.
                Commit it to your gateway config; your gateway enforces it.
              </p>
            )}
          </div>
        )}
      </Panel>

      <Panel title="Recommended Policies" source={recs.data?.source} loading={recs.loading} error={recs.error}>
        {policyRecs.length === 0 ? <p className="muted">No policy Recommendations yet.</p> : policyRecs.map((r) => (
          <article key={r.recommendation_id} className="rec">
            <div className="rec-head">
              <h3>{r.title}</h3>
              <Money value={r.saving} />
            </div>
            <p className="small muted">Practice: {r.practice.title} <code>{r.practice.practice_id}</code></p>
            <p>{r.body}</p>
            <p className="small">
              {r.policy_prefill.team}: {r.policy_prefill.allowed_models.join(", ")}{" "}
              <button className="button" onClick={() => prefill(r)} disabled={fromRec === r.recommendation_id}>
                {fromRec === r.recommendation_id ? "Prefilled" : "Prefill"}
              </button>
            </p>
          </article>
        ))}
      </Panel>

      <Panel title="Applied Policies" source={history.data?.source} loading={history.loading} error={history.error}>
        {history.data?.items.length ? (
          <table className="table">
            <thead><tr><th>Team</th><th>Allowed models</th><th>File</th><th>Applied</th></tr></thead>
            <tbody>
              {history.data.items.map((p) => (
                <tr key={p.policy_id}>
                  <td>{p.team}</td>
                  <td>{p.allowed_models.join(", ")}</td>
                  <td><code>{p.output_path ?? "not written"}</code></td>
                  <td className="small">{p.applied_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted">No Policy applied yet.</p>}
      </Panel>
    </>
  );
}
