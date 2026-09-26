"use client";
// Panel: Sessions in this Initiative. Owner: 06. GET /api/initiatives/{id}/sessions
import { Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import { WASTE_PATTERN_LABEL, type SessionList } from "@/lib/contract";

export default function SessionsList({ initiativeId }: { initiativeId: string }) {
  const { data, error, loading } = useApi<SessionList>(`/api/initiatives/${initiativeId}/sessions`);
  return (
    <Panel title="Sessions" source={data?.source} loading={loading} error={error}>
      <table className="table compact">
        <thead><tr><th>Started</th><th>Member</th><th>Team</th><th>Summary</th><th>Tokens</th><th>Spend</th><th>Waste</th></tr></thead>
        <tbody>
          {data?.items.map((s) => (
            <tr key={s.session_id}>
              <td>{s.started_at.slice(0, 16).replace("T", " ")}</td><td>{s.member_id}</td><td>{s.team}</td>
              <td>{s.summary ?? "—"}{s.experiment && <span className="chip">{s.experiment}</span>}</td>
              <td>{s.total_tokens.toLocaleString()}</td><td><Money value={s.spend} size="sm" /></td>
              <td>{s.waste_patterns.map((p) => WASTE_PATTERN_LABEL[p]).join(", ") || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
