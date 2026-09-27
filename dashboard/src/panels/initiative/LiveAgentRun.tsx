"use client";
// Live agent run inside a Draft Recommendation's card (demo feedback: show a real agent applying the fix).
// GET/POST /api/recommendations/{id}/live-run, GET /api/live-runs/{run_id} (backend/dwight/live_run.py).
// Real, not simulated: Dwight loads the Initiative's Drafts into kestrel-devagent's context, the harness
// re-runs the same tasks on the pinned model, and the result is Measured against the recorded before runs.
// If the run fails or times out, the recorded after runs are shown instead, labelled as recorded.
import { useEffect, useState } from "react";
import { Money } from "@/components/Money";
import { apiGet, useApi } from "@/lib/api";
import type { BeforeAfter, LiveRun, LiveRunStatus, LiveTask } from "@/lib/contract";

const tokens = (n: number) => Math.round(n).toLocaleString("en-US");
const shortModel = (m?: string | null) => (m ? m.split("/").pop() : "the pinned model");
const TYPE_LABEL = { initiative_doc: "initiative doc", memory: "memory file" } as const;
// Measured is the dashboard default (no pill, ADR 0006 UI note); the live result says it came from this run.
const LiveTag = ({ live }: { live?: boolean }) => (live ? <span className="badge badge-live">live run</span> : null);

async function post<T>(path: string): Promise<T> {
  const r = await fetch(path, { method: "POST" });
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {
      // not JSON
    }
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

function TaskTile({ t }: { t: LiveTask }) {
  const share = t.before_tokens ? Math.min(t.tokens / t.before_tokens, 1) : 0;
  const icon = t.status === "done" ? (t.task_success ? "✓" : "✗") : t.status === "failed" ? "!" : t.status === "running" ? "●" : "○";
  return (
    <div className={`live-task live-task-${t.status}${t.status === "done" ? (t.task_success ? " live-pass" : " live-fail") : ""}`}
      title={t.error ?? (t.check_notes?.length ? t.check_notes.join("; ") : t.session_id)}>
      <div className="live-task-head">
        <strong>{t.task_id.split("-")[0]}</strong>
        <span className="live-icon" aria-label={t.status}>{icon}</span>
      </div>
      <div className="small">
        {t.status === "queued" ? "waiting" : t.status === "failed" ? "API error" : `${t.calls} calls · ${tokens(t.tokens)} tok`}
      </div>
      <div className="live-bar" aria-hidden><span style={{ width: `${Math.max(share * 100, t.tokens ? 2 : 0)}%` }} /></div>
      <div className="small muted">
        {t.status === "running" && t.last_tools.length ? `→ ${t.last_tools.join(", ")}` :
          t.before_tokens ? `before: ${tokens(t.before_tokens)} tok` : ""}
      </div>
    </div>
  );
}

function Result({ r, live }: { r: BeforeAfter; live: boolean }) {
  const b = r.before, a = r.after;
  if (!b || !a) return null;
  const held = r.success_held === true;
  return (
    <div className={`live-result${held ? "" : " live-result-bad"}`}>
      <div className="sim-flow">
        <div><div className="stat-label">Tokens / Session</div>{tokens(b.avg_tokens)} → <strong>{tokens(a.avg_tokens)}</strong></div>
        <div>
          <div className="stat-label">Token drop</div>
          <strong className="live-big">{r.token_drop_pct != null ? `${r.token_drop_pct >= 0 ? "−" : "+"}${Math.abs(r.token_drop_pct).toFixed(1)}%` : "–"}</strong>{" "}
          <LiveTag live={live} />
        </div>
        <div><div className="stat-label">Spend on these runs</div><Money value={b.spend} size="sm" /> → <Money value={a.spend} size="sm" /></div>
        <div><div className="stat-label">Tasks passed</div>{b.tasks_passed}/{b.tasks_total} → <strong>{a.tasks_passed}/{a.tasks_total}</strong></div>
      </div>
      {held ? (
        <p className="small">Task success held, so this counts: {r.spend_drop && <><Money value={r.spend_drop} size="sm" /> less Spend on these {a.session_count} runs.</>}</p>
      ) : (
        <p className="small panel-error">Task success dropped ({b.tasks_passed}/{b.tasks_total} → {a.tasks_passed}/{a.tasks_total}), so this run doesn&apos;t count as a saving.</p>
      )}
    </div>
  );
}

export default function LiveAgentRun({ recommendationId }: { recommendationId: string }) {
  const status = useApi<LiveRunStatus>(`/api/recommendations/${recommendationId}/live-run`);
  const [run, setRun] = useState<LiveRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [showRecorded, setShowRecorded] = useState(false);
  const s = status.data;
  const current = run ?? s?.run ?? null;
  const active = current && (current.status === "applying" || current.status === "running");

  // Poll while the run is in progress.
  useEffect(() => {
    if (!active || !current) return;
    let live = true;
    const id = setInterval(() => {
      apiGet<LiveRun>(`/api/live-runs/${current.run_id}`).then((r) => live && setRun(r)).catch(() => undefined);
    }, 1000);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, [active, current?.run_id]);

  if (!s || !s.eligible) return null;
  const start = () => {
    setStarting(true);
    setError(null);
    setShowRecorded(false);
    post<LiveRun>(`/api/recommendations/${recommendationId}/live-run`)
      .then(setRun)
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setStarting(false));
  };
  const failed = current && (current.status === "failed" || current.status === "timed_out");
  const done = current?.status === "done";
  const passed = current?.tasks.filter((t) => t.status === "done" && t.task_success).length ?? 0;
  const finished = current?.tasks.filter((t) => t.status === "done" || t.status === "failed").length ?? 0;

  return (
    <div className="live-run">
      <p className="sim-result-head">
        <strong>Run this fix with a real agent</strong> <span className="badge badge-live">Real · not simulated</span>
      </p>
      {!current && (
        <p className="small">
          Dwight loads this Initiative&apos;s Drafts ({s.applied_drafts.map((d) => `${TYPE_LABEL[d.type]}, ${tokens(d.tokens)} tokens`).join("; ")})
          into kestrel-devagent&apos;s context, then the agent re-runs the same {s.task_count} storage tasks live on{" "}
          <code>{shortModel(s.model)}</code>, with the settings the before runs used. The result is Measured against those before runs.
        </p>
      )}

      {current && (
        <ol className="live-steps small">
          <li className="done">
            <strong>Fix applied by Dwight:</strong> {current.applied_files.map((f) => <code key={f.draft_id}>{f.filename}</code>)} loaded into
            the agent&apos;s starting context.
          </li>
          <li className={done || failed ? "done" : "now"}>
            <strong>kestrel-devagent re-runs {current.tasks.length} tasks</strong> on <code>{shortModel(current.model)}</code>{" "}
            · {finished}/{current.tasks.length} finished · {passed} passed · {current.elapsed_s.toFixed(0)} s
          </li>
          <li className={done ? "done" : ""}><strong>Measured</strong> against the recorded before runs of the same tasks</li>
        </ol>
      )}
      {current && (
        <div className="live-grid">{current.tasks.map((t) => <TaskTile key={t.task_id} t={t} />)}</div>
      )}
      {current && <p className="small muted">Each bar is the tokens used so far, against the full width of that task&apos;s before run.</p>}
      {current?.tasks.filter((t) => t.status === "done" && t.task_success === false).map((t) => (
        <p key={t.task_id} className="small panel-error">
          {t.task_id} failed its check{t.check_notes?.length ? `: ${t.check_notes.join("; ")}` : ""} (it {t.before_success ? "passed" : "failed"} in the before run).
        </p>
      ))}

      {done && current.result && <Result r={current.result} live />}
      {done && current.message && <p className="small muted">{current.message}</p>}
      {(failed || error) && (
        <p className="small panel-error">
          {error ? `Couldn't start the live run: ${error}` : current?.message ?? "The live run failed."} Showing the recorded run instead.
        </p>
      )}
      {(failed || error || showRecorded) && s.recorded && (
        <>
          <p className="sim-result-head small"><strong>Recorded run</strong> <span className="badge">recorded, ticket 16</span> the same tasks, run with the Drafts earlier</p>
          <Result r={s.recorded} live={false} />
        </>
      )}

      <div className="live-actions">
        {s.enabled ? (
          <button type="button" className="button button-cta" onClick={start} disabled={starting || !!active}>
            {active ? "Running…" : starting ? "Starting…" : current ? "Run it again, live" : `Apply the fix and run ${s.task_count} tasks live`}
          </button>
        ) : (
          <span className="small muted">{s.reason}</span>
        )}
        {s.recorded && !failed && !error && (
          <button type="button" className="linklike small" onClick={() => setShowRecorded((v) => !v)}>
            {showRecorded ? "Hide the recorded run" : "Show the recorded run"}
          </button>
        )}
      </div>
    </div>
  );
}
