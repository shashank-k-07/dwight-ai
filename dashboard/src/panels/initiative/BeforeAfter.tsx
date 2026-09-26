"use client";
// Panel: before/after proof. Owner: 13. Hidden when the Initiative has no experiment runs.
// GET /api/initiatives/{id}/before-after (computed from stored dwight.experiment Sessions).
import { Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import type { BeforeAfter as BA, ExperimentTotals } from "@/lib/contract";

const tokens = (n: number) => Math.round(n).toLocaleString("en-US");
const pct = (x: number) => `${Math.round(x * 100)}%`;
const success = (t: ExperimentTotals) =>
  t.tasks_total > 0 ? `${t.tasks_passed}/${t.tasks_total} passed (${pct(t.success_rate)})` : "not recorded";

// Token counts and task success are Measured too, not only the dollars.
function MeasuredTag() {
  return <span className="money-kind money-kind-measured">Measured</span>;
}

function change(before: number, after: number): string {
  if (before <= 0) return "";
  const d = ((after - before) / before) * 100;
  return `${d > 0 ? "+" : d < 0 ? "−" : ""}${Math.abs(d).toFixed(1)}%`;
}

function Totals({ data }: { data: BA }) {
  const b = data.before;
  const a = data.after;
  const counts = data.success_held === true;
  return (
    <table className="table compact">
      <thead>
        <tr><th></th><th>Before the Draft</th><th>After the Draft</th><th>Change</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>Sessions</td><td>{b?.session_count ?? "–"}</td><td>{a?.session_count ?? "–"}</td><td></td>
        </tr>
        <tr>
          <td>Tokens / Session</td>
          <td>{b ? tokens(b.avg_tokens) : "–"}</td>
          <td>{a ? tokens(a.avg_tokens) : "–"}</td>
          <td>{b && a ? change(b.avg_tokens, a.avg_tokens) : ""}</td>
        </tr>
        <tr>
          <td>Tokens (total)</td><td>{b ? tokens(b.total_tokens) : "–"}</td><td>{a ? tokens(a.total_tokens) : "–"}</td><td></td>
        </tr>
        <tr>
          <td>Spend</td>
          <td>{b ? <Money value={b.spend} size="sm" /> : "–"}</td>
          <td>{a ? <Money value={a.spend} size="sm" /> : "–"}</td>
          {/* The Spend drop is only shown when task success held: otherwise it isn't a saving. */}
          <td>{counts && data.spend_drop ? <Money value={data.spend_drop} size="sm" /> : ""}</td>
        </tr>
        <tr>
          <td>Task success</td><td>{b ? success(b) : "–"}</td><td>{a ? success(a) : "–"}</td><td></td>
        </tr>
      </tbody>
    </table>
  );
}

function Verdict({ data }: { data: BA }) {
  const { before: b, after: a } = data;
  if (!a) return <p className="muted">After runs with the Draft loaded aren&apos;t in yet. Only the before runs are shown.</p>;
  if (!b) return <p className="muted">No before runs for these tasks yet, so there is nothing to compare.</p>;
  if (!data.success_held) {
    const why = b.tasks_total === 0 || a.tasks_total === 0 ? "Task success wasn't recorded" : "Task success dropped";
    return <p className="panel-error">{why}, so this result doesn&apos;t count and the drop isn&apos;t shown as a saving.</p>;
  }
  const drop = data.token_drop_pct;
  if (drop == null) return null;
  const spend = data.spend_drop;
  return (
    <p>
      <strong>{drop >= 0 ? `${drop.toFixed(0)}% fewer tokens per Session` : `${Math.abs(drop).toFixed(0)}% more tokens per Session`}</strong>{" "}
      <MeasuredTag />
      {spend && (
        <> · <Money value={{ ...spend, usd: Math.abs(spend.usd) }} /> {spend.usd >= 0 ? "less" : "more"} Spend</>
      )}
      {" "}· task success held ({b.tasks_passed}/{b.tasks_total} → {a.tasks_passed}/{a.tasks_total})
    </p>
  );
}

export default function BeforeAfter({ initiativeId }: { initiativeId: string }) {
  const { data, error, loading } = useApi<BA>(`/api/initiatives/${initiativeId}/before-after`);
  if (data && !data.has_runs) return null;
  return (
    <Panel title="Before / after the Draft" source={data?.source} loading={loading} error={error}>
      {data && (
        <>
          <Verdict data={data} />
          <Totals data={data} />
          <p className="small muted">
            Same tasks run without and then with the Draft loaded; only tasks run on both sides are compared.
          </p>
        </>
      )}
    </Panel>
  );
}
