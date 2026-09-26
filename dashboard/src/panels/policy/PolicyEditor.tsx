"use client";
// Panel: Policy editor + rendered gateway config. Owner: 14.
// GET /api/policy/options, POST /api/policy/render, POST /api/policy/apply, GET /api/policies
// Prefill: /policy?team=<Team>&models=a,b (from a policy Recommendation).
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Panel } from "@/components/Panel";
import { apiPost, useApi } from "@/lib/api";
import type { Policy, PolicyOptions, PolicyRender } from "@/lib/contract";

export default function PolicyEditor() {
  const params = useSearchParams();
  const { data, error, loading } = useApi<PolicyOptions>("/api/policy/options");
  const [team, setTeam] = useState(params.get("team") ?? "");
  const [models, setModels] = useState<string[]>(params.get("models")?.split(",").filter(Boolean) ?? []);
  const [render, setRender] = useState<PolicyRender | null>(null);
  const [applied, setApplied] = useState<Policy | null>(null);

  useEffect(() => {
    if (!team && data?.teams.length) setTeam(data.teams[0].team);
  }, [data, team]);
  useEffect(() => {
    if (!team) return;
    apiPost<PolicyRender>("/api/policy/render", { team, allowed_models: models }).then(setRender).catch(() => setRender(null));
    setApplied(null);
  }, [team, models]);

  const toggle = (m: string) => setModels((cur) => (cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m]));
  return (
    <Panel title="Policy" source={data?.source} loading={loading} error={error}>
      {data && (
        <div className="policy">
          <label>Team{" "}
            <select value={team} onChange={(e) => setTeam(e.target.value)}>
              {data.teams.map((t) => <option key={t.team} value={t.team}>{t.team} ({t.business_function})</option>)}
            </select>
          </label>
          <fieldset>
            <legend>Allowed models</legend>
            {data.models.map((m) => (
              <label key={m.model} className="check">
                <input type="checkbox" checked={models.includes(m.model)} onChange={() => toggle(m.model)} /> {m.model} <span className="muted small">{m.tier}</span>
              </label>
            ))}
          </fieldset>
          <h3>Gateway config (LiteLLM) {render?.source === "fixture" && <span className="badge badge-fixture">fixture data</span>}</h3>
          <pre className="markdown">{render?.rendered_config ?? "…"}</pre>
          <button className="button" onClick={() => apiPost<Policy>("/api/policy/apply", { team, allowed_models: models }).then(setApplied)}>Apply</button>
          {applied && <p className="small">Written to <code>{applied.output_path}</code>. Your gateway enforces it; Dwight doesn&apos;t sit in the request path.</p>}
        </div>
      )}
    </Panel>
  );
}
