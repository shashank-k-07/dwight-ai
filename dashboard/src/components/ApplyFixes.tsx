"use client";
// "Apply fixes": runs the simulation over the fixes applied with "Implement" (lib/simulation.ts),
// one row at a time, and shows Spend before -> after and the money saved. Used on Initiative
// detail (scope = the Initiative, one row per fix) and Overview (scope = "all", one row per
// Initiative). Every number is the same arithmetic as project(): Spend minus each fix's own
// saving, one Waste counted once, no Initiative saving more than its own Spend, labelled
// Simulated · Estimated. The step-by-step reveal only animates towards those computed values.
import { useEffect, useRef, useState } from "react";
import { Info, Money } from "@/components/Money";
import type { Money as MoneyT, Recommendation } from "@/lib/contract";
import { bySaving, project, shareOf, useSimulation } from "@/lib/simulation";

const STEP_MS = 650;
const RUN_MS = 5000; // a run with many rows still finishes in about this long
const reduceMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Animate a number towards `target` (ms), or jump when motion is reduced. */
function useTween(target: number, ms = 450): number {
  const [v, setV] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    if (reduceMotion()) {
      setV(target);
      from.current = target;
      return;
    }
    const start = performance.now();
    const a = from.current;
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / ms);
      const e = 1 - Math.pow(1 - k, 3);
      const x = a + (target - a) * e;
      setV(x);
      from.current = x;
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

const sim$ = (usd: number): MoneyT => ({ usd, kind: "estimated", note: "simulated" });

interface Row { key: string; label: string; sub?: string; recs: Recommendation[] }

export default function ApplyFixes({ scope, base, baseLabel, sessions, recs: appliedRecs, labelFor, proofHref, groupBy, caps }: {
  scope: string;
  base: MoneyT | null;
  baseLabel: string;
  sessions?: number;
  recs: Recommendation[];
  /** Where a single fix applies (e.g. the Initiative's name), shown before its title. */
  labelFor?: (r: Recommendation) => string;
  /** Link for "proven on real runs" (Draft fixes with a Measured before/after). */
  proofHref?: (r: Recommendation) => string;
  /** One row per group (e.g. per Initiative on Overview) instead of one row per fix. */
  groupBy?: (r: Recommendation) => { key: string; label: string };
  /** Most a target ("initiative:<id>") can save: its own Spend (see project()). */
  caps?: Record<string, number>;
}) {
  const sim = useSimulation();
  const recs = bySaving(appliedRecs); // largest first, so an overlapping smaller fix adds nothing
  const run = sim.runFor(scope, recs);
  const [step, setStep] = useState<number | null>(null); // null = show the whole run at once

  // Rows the run steps through: single fixes, or groups ordered by what they save.
  let rows: Row[];
  if (groupBy && base) {
    const m = new Map<string, Row>();
    recs.forEach((r) => {
      const g = groupBy(r);
      const row = m.get(g.key) ?? { key: g.key, label: g.label, recs: [] };
      row.recs.push(r);
      m.set(g.key, row);
    });
    rows = [...m.values()]
      .map((row) => ({ ...row, sub: `${row.recs.length} ${row.recs.length === 1 ? "fix" : "fixes"}` }))
      .sort((x, y) => project(base, y.recs, caps).saving.usd - project(base, x.recs, caps).saving.usd);
  } else {
    rows = recs.map((r) => ({ key: r.recommendation_id, label: r.title, recs: [r] }));
  }
  const stepMs = Math.min(STEP_MS, RUN_MS / Math.max(rows.length, 1));
  const shown = run ? (step ?? rows.length) : 0;
  const upTo = (n: number) => rows.slice(0, n).flatMap((row) => row.recs);

  useEffect(() => {
    if (step === null || step >= rows.length) return;
    const id = setTimeout(() => setStep((s) => (s === null ? null : s + 1)), reduceMotion() ? 0 : stepMs);
    return () => clearTimeout(id);
  }, [step, rows.length, stepMs]);

  const partial = base ? project(base, upTo(shown), caps) : null;
  const after = useTween(partial ? partial.after.usd : base?.usd ?? 0);
  const saved = useTween(partial ? partial.saving.usd : 0);
  if (!recs.length || !base) return null;
  const final = project(base, recs, caps);
  const running = run && step !== null && step < rows.length;

  const start = () => {
    sim.run(scope, recs);
    setStep(0);
  };

  // What each row adds, in order (a fix repeating a larger one's Waste adds nothing).
  const added = rows.map((_, i) => project(base, upTo(i + 1), caps).saving.usd - project(base, upTo(i), caps).saving.usd);
  // Why a row adds nothing: it repeats a larger fix's Waste, or its Initiative's Spend is already used up.
  const overlapped = rows.map((_, i) => project(base, upTo(i + 1), caps).overlapping > project(base, upTo(i), caps).overlapping);
  const grouped = !!groupBy;

  return (
    <div className={`fixes${run ? " fixes-run" : ""}`} id={`applied-fixes-${scope}`}>
      <div className="fixes-head">
        <strong>{recs.length} {recs.length === 1 ? "fix" : "fixes"} applied</strong>
        {grouped && <span className="small muted">across {rows.length} {rows.length === 1 ? "Initiative" : "Initiatives"}</span>}
        <span className="badge badge-sim">Simulation</span>
        <Info>Applied in this browser only: Dwight changed nothing in your systems. Apply fixes runs the simulation over the Sessions and shows the Spend they would have cost with these fixes in place.</Info>
        <span className="fixes-actions">
          {!run || running ? (
            <button type="button" className="button button-cta" onClick={start} disabled={!!running}>
              {running ? "Running simulation…" : "Apply fixes"}
            </button>
          ) : (
            <button type="button" className="button button-quiet" onClick={start}>Run again</button>
          )}
          <button type="button" className="linklike small" onClick={sim.reset}>Reset simulation</button>
        </span>
      </div>

      <ol className="fixes-list">
        {rows.map((row, i) => {
          const done = run && i < shown;
          const one = grouped ? null : row.recs[0];
          const proven = row.recs.find((r) => r.measured_drop?.counts);
          return (
            <li key={row.key} className={done ? "done" : running && i === shown ? "now" : ""}>
              <span className="fixes-check" aria-hidden>{done ? "✓" : "○"}</span>
              <span className="fixes-title">
                {one && labelFor && <span className="muted">{labelFor(one)} · </span>}
                {row.label}
                {row.sub && <span className="small muted"> · {row.sub}</span>}
                {proven?.measured_drop && (
                  <span className="small muted"> · proven on real runs: −{proven.measured_drop.token_drop_pct.toFixed(1)}% tokens
                    {proofHref && <> (<a href={proofHref(proven)}>before/after</a>)</>}</span>
                )}
              </span>
              <span className="fixes-amount">
                {done ? (added[i] > 0.0000005
                  ? <>−<Money value={sim$(added[i])} size="sm" /></>
                  : <span className="small muted">{overlapped[i] ? "same Waste as a larger fix above, not added" : "nothing left to save: its Initiative's Spend is already counted"}</span>)
                  : one ? <Money value={one.saving} size="sm" /> : null}
              </span>
              {!run && (
                <button type="button" className="linklike small" onClick={() => sim.undoAll(row.recs.map((r) => r.recommendation_id))}
                  title={one ? "Un-apply this fix" : "Un-apply these fixes"}>Undo</button>
              )}
            </li>
          );
        })}
      </ol>

      {!run ? (
        <p className="small muted">
          Press <strong>Apply fixes</strong> to run the simulation over {sessions ? `${sessions.toLocaleString("en-US")} Sessions` : "the Sessions"} and
          see the money saved.
        </p>
      ) : (
        <div className="fixes-result">
          <div className="sim-flow">
            <div>
              <div className="stat-label">{baseLabel}, before</div>
              <Money value={base} size="lg" />
            </div>
            <div className="sim-arrow" aria-hidden>→</div>
            <div>
              <div className="stat-label">After the fixes</div>
              <Money value={sim$(after)} size="lg" />
            </div>
            <div className="fixes-saved">
              <div className="stat-label">Money saved</div>
              <Money value={sim$(saved)} size="lg" />
              <div className="small muted">{shareOf(sim$(saved), base).toFixed(1)}% of Spend</div>
            </div>
          </div>
          <div className="fixes-bars" aria-hidden>
            <div className="fixes-bar"><span className="fixes-bar-label">Before</span><span className="fixes-bar-track"><span className="fixes-bar-before" style={{ width: "100%" }} /></span></div>
            <div className="fixes-bar">
              <span className="fixes-bar-label">After</span>
              <span className="fixes-bar-track">
                <span className="fixes-bar-after" style={{ width: `${base.usd > 0 ? (after / base.usd) * 100 : 0}%` }} />
                <span className="fixes-bar-saved" style={{ width: `${base.usd > 0 ? (saved / base.usd) * 100 : 0}%` }} />
              </span>
            </div>
          </div>
          <p className="small muted">
            Simulated · Estimated: Spend minus each fix&apos;s own saving, for the same Sessions.{" "}
            {final.overlapping
              ? `${final.overlapping} ${final.overlapping === 1 ? "fix removes" : "fixes remove"} the same Waste as a larger one and ${final.overlapping === 1 ? "is" : "are"} not added; `
              : "Fixes for the same Waste count once (the largest); "}
            {final.capped ? "no Initiative saves more than its own Spend; " : ""}
            fixes for different Waste can still touch the same Calls, so treat it as an upper bound.
          </p>
        </div>
      )}
    </div>
  );
}
