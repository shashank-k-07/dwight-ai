"use client";
// "Apply fixes": runs the simulation over the fixes applied with "Implement" (lib/simulation.ts),
// one fix at a time, and shows Spend before -> after and the money saved. Used on Initiative
// detail (scope = the Initiative) and Overview (scope = "all"). Every number is the same
// arithmetic as project(): Spend minus each fix's own saving, one Waste counted once, labelled
// Simulated · Estimated. The step-by-step reveal only animates towards those computed values.
import { useEffect, useRef, useState } from "react";
import { Info, Money } from "@/components/Money";
import type { Money as MoneyT, Recommendation } from "@/lib/contract";
import { project, shareOf, useSimulation } from "@/lib/simulation";

const STEP_MS = 650;
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

export default function ApplyFixes({ scope, base, baseLabel, sessions, recs, labelFor, proofHref }: {
  scope: string;
  base: MoneyT | null;
  baseLabel: string;
  sessions?: number;
  recs: Recommendation[];
  /** Where each fix applies, for the Overview list (e.g. the Initiative's name). */
  labelFor?: (r: Recommendation) => string;
  /** Link for "proven on real runs" (Draft fixes with a Measured before/after). */
  proofHref?: (r: Recommendation) => string;
}) {
  const sim = useSimulation();
  const run = sim.runFor(scope, recs);
  const [step, setStep] = useState<number | null>(null); // null = show the whole run at once
  const shown = run ? (step ?? recs.length) : 0;

  useEffect(() => {
    if (step === null || step >= recs.length) return;
    const id = setTimeout(() => setStep((s) => (s === null ? null : s + 1)), reduceMotion() ? 0 : STEP_MS);
    return () => clearTimeout(id);
  }, [step, recs.length]);

  const partial = base ? project(base, recs.slice(0, shown)) : null;
  const after = useTween(partial ? partial.after.usd : base?.usd ?? 0);
  const saved = useTween(partial ? partial.saving.usd : 0);
  if (!recs.length || !base) return null;
  const final = project(base, recs);
  const running = run && step !== null && step < recs.length;

  const start = () => {
    sim.run(scope, recs);
    setStep(0);
  };

  // What each fix adds, in order (a fix repeating an earlier one's Waste adds nothing).
  const added = recs.map((_, i) => project(base, recs.slice(0, i + 1)).saving.usd - project(base, recs.slice(0, i)).saving.usd);

  return (
    <div className={`fixes${run ? " fixes-run" : ""}`} id={`applied-fixes-${scope}`}>
      <div className="fixes-head">
        <strong>{recs.length} {recs.length === 1 ? "fix" : "fixes"} applied</strong>
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
        {recs.map((r, i) => {
          const done = run && i < shown;
          return (
            <li key={r.recommendation_id} className={done ? "done" : running && i === shown ? "now" : ""}>
              <span className="fixes-check" aria-hidden>{done ? "✓" : "○"}</span>
              <span className="fixes-title">
                {labelFor && <span className="muted">{labelFor(r)} · </span>}
                {r.title}
                {r.measured_drop?.counts && (
                  <span className="small muted"> · proven on real runs: −{r.measured_drop.token_drop_pct.toFixed(1)}% tokens
                    {proofHref && <> (<a href={proofHref(r)}>before/after</a>)</>}</span>
                )}
              </span>
              <span className="fixes-amount">
                {done ? (added[i] > 0.0000005
                  ? <>−<Money value={sim$(added[i])} size="sm" /></>
                  : <span className="small muted">same Waste as an earlier fix, not added again</span>)
                  : <Money value={r.saving} size="sm" />}
              </span>
              {!run && (
                <button type="button" className="linklike small" onClick={() => sim.undo(r.recommendation_id)} title="Un-apply this fix">Undo</button>
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
            {final.overlapping ? `${final.overlapping} fix${final.overlapping === 1 ? "" : "es"} repeat an earlier one's Waste and count once; ` : "A Waste counts once; "}
            different fixes can still overlap, so treat it as an upper bound{final.capped ? " (capped at Spend)" : ""}.
          </p>
        </div>
      )}
    </div>
  );
}
