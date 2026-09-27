"use client";
// Panel: Sessions in this Initiative, most Spend first. Owner: 06. GET /api/initiatives/{id}/sessions
// With a Team (?team=, from the Overview chart) it shows that Team's Sessions only.
import { useState } from "react";
import { Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import { WASTE_PATTERN_LABEL, type SessionList } from "@/lib/contract";

const PAGE = 5;
const COMPLEXITY_LABEL = { low: "Low", med: "Medium", high: "High" } as const;

export default function SessionsList({ initiativeId, team }: { initiativeId: string; team?: string | null }) {
  const { data, error, loading } = useApi<SessionList>(`/api/initiatives/${initiativeId}/sessions`);
  const [showAll, setShowAll] = useState(false);
  const items = (data?.items ?? []).filter((s) => !team || s.team === team);
  const shown = showAll ? items : items.slice(0, PAGE);
  const anyWaste = items.some((s) => s.waste_patterns.length > 0);
  const toggle =
    items.length > PAGE ? (
      <button className="button" onClick={() => setShowAll((v) => !v)}>
        {showAll ? `Show top ${PAGE}` : `Show all ${items.length.toLocaleString()}`}
      </button>
    ) : null;
  return (
    <Panel title={team ? `Sessions · Team ${team}` : "Sessions"} source={data?.source} loading={loading} error={error} actions={toggle}>
      {data && items.length === 0 ? (
        <p className="muted">No Sessions classified into this Initiative yet.</p>
      ) : (
        <table className="table compact">
          <thead>
            <tr>
              <th>Started</th><th>Member</th><th>Team</th><th>Summary</th><th>Complexity</th>
              <th>Calls</th><th>Tokens</th><th>Spend</th>{anyWaste && <th>Waste</th>}
            </tr>
          </thead>
          <tbody>
            {shown.map((s) => (
              <tr key={s.session_id}>
                <td title={s.session_id}>{s.started_at.slice(0, 16).replace("T", " ")}</td>
                <td>{s.member_id}</td>
                <td>{s.team}</td>
                <td>
                  {s.summary ?? "—"}
                  {s.experiment && <span className="chip">{s.experiment}</span>}
                  {s.task_success != null && (
                    <span className="chip">{s.task_success ? "task passed" : "task failed"}</span>
                  )}
                </td>
                <td>{s.complexity ? COMPLEXITY_LABEL[s.complexity] : "—"}</td>
                <td>{s.call_count}</td>
                <td>{s.total_tokens.toLocaleString()}</td>
                <td><Money value={s.spend} size="sm" /></td>
                {anyWaste && <td>{s.waste_patterns.map((p) => WASTE_PATTERN_LABEL[p]).join(", ") || "—"}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data && items.length > PAGE && !showAll && (
        <p className="muted small">Top {PAGE} by Spend of {items.length.toLocaleString()}.</p>
      )}
    </Panel>
  );
}
