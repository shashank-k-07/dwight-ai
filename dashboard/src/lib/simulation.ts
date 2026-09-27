"use client";
// "Implement" + "Apply fixes" simulation (demo feedback). Per viewer, in this browser only
// (localStorage): nothing is written to the store and nothing here ever happened.
//   1. Implement on a Recommendation applies its fix (it's added to `applied`); no numbers yet.
//   2. Apply fixes runs the simulation over the applied fixes in a scope (one Initiative, or
//      "all" on Overview) and records the run; the panel then shows Spend before -> after.
// Every projected figure is arithmetic in code on the served Money objects (Spend minus each
// fix's own saving, one Waste counted once), kind "estimated" with note "simulated", never
// Measured and never from the LLM. The only Measured results are real runs, read from the API.
import { useSyncExternalStore } from "react";
import type { Money, Recommendation } from "@/lib/contract";

const KEY = "dwight.simulation.v2";
const OLD_KEY = "dwight.simulation.v1"; // v1 held only implemented Recommendations

export interface Implemented {
  recommendation_id: string;
  /** The Initiative page it was applied from. */
  initiative_id: string;
  at: string;
}
export interface SimRun {
  ids: string[]; // the applied fixes the run covered, sorted
  at: string;
}
export interface SimulationState {
  applied: Record<string, Implemented>;
  runs: Record<string, SimRun>; // scope ("all" | initiative_id) -> last run
}

const EMPTY: SimulationState = { applied: {}, runs: {} };
let cache: SimulationState | null = null;
const listeners = new Set<() => void>();

function load(): SimulationState {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) {
      const p = JSON.parse(raw);
      if (p && typeof p === "object") return { applied: p.applied ?? {}, runs: p.runs ?? {} };
    }
    const old = window.localStorage.getItem(OLD_KEY);
    if (old) return { applied: JSON.parse(old) ?? {}, runs: {} };
  } catch {
    // unreadable or blocked: start empty
  }
  return EMPTY;
}

function save(next: SimulationState) {
  cache = next;
  try {
    window.localStorage.removeItem(OLD_KEY);
    if (Object.keys(next.applied).length || Object.keys(next.runs).length) window.localStorage.setItem(KEY, JSON.stringify(next));
    else window.localStorage.removeItem(KEY);
  } catch {
    // storage blocked (private window): the simulation still works until reload
  }
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) {
      cache = null;
      l();
    }
  };
  window.addEventListener("storage", onStorage); // other tabs
  return () => {
    listeners.delete(l);
    window.removeEventListener("storage", onStorage);
  };
}

function snapshot(): SimulationState {
  if (cache === null) cache = load();
  return cache;
}

const sortedIds = (recs: Recommendation[]) => recs.map((r) => r.recommendation_id).sort();

export function useSimulation() {
  const state = useSyncExternalStore(subscribe, snapshot, () => EMPTY);
  return {
    state,
    count: Object.keys(state.applied).length,
    isApplied: (id: string) => id in state.applied,
    apply: (r: Recommendation, initiativeId: string) => {
      const cur = snapshot();
      save({ ...cur, applied: { ...cur.applied, [r.recommendation_id]: { recommendation_id: r.recommendation_id, initiative_id: initiativeId, at: new Date().toISOString() } } });
    },
    /** Implement all: apply several fixes in one go. */
    applyAll: (recs: Recommendation[], initiativeId: string | ((r: Recommendation) => string)) => {
      const cur = snapshot();
      const at = new Date().toISOString();
      const applied = { ...cur.applied };
      const from = typeof initiativeId === "function" ? initiativeId : () => initiativeId;
      recs.forEach((r) => (applied[r.recommendation_id] = { recommendation_id: r.recommendation_id, initiative_id: from(r), at }));
      save({ ...cur, applied });
    },
    undoAll: (ids: string[]) => {
      const cur = snapshot();
      const applied = { ...cur.applied };
      ids.forEach((id) => delete applied[id]);
      save({ ...cur, applied });
    },
    undo: (id: string) => {
      const cur = snapshot();
      const applied = { ...cur.applied };
      delete applied[id];
      save({ ...cur, applied });
    },
    /** Apply fixes: record a run of the simulation over these applied fixes, in a scope. */
    run: (scope: string, recs: Recommendation[]) => {
      const cur = snapshot();
      save({ ...cur, runs: { ...cur.runs, [scope]: { ids: sortedIds(recs), at: new Date().toISOString() } } });
    },
    /** The scope's last run, if it covered exactly these fixes (otherwise the result is stale). */
    runFor: (scope: string, recs: Recommendation[]): SimRun | null => {
      const r = state.runs[scope];
      return r && r.ids.join(",") === sortedIds(recs).join(",") ? r : null;
    },
    reset: () => save(EMPTY),
  };
}

/** Policy Recommendations aren't simulated: "Apply as Policy" really writes the gateway config. */
export const isSimulatable = (r: Recommendation) => r.target_type !== "policy";

// Recommendations that remove the same Waste don't add up: the backend gives them one
// `overlap_group` (routes/recommendations.py overlap_group(); e.g. every fix for an Initiative's
// repeated Discoveries, since the memory file covers them all), and only the largest saving in a
// group counts. Older responses without the field fall back to the engine's same-Waste key.
const wasteKey = (r: Recommendation) =>
  r.overlap_group ?? [r.target_type, r.target_id, r.recurring_discovery_id ?? "", r.saving.kind, r.saving.usd.toFixed(6)].join("|");

/** Largest saving first: the order a run applies fixes in, so an overlapping smaller fix adds nothing. */
export const bySaving = (recs: Recommendation[]) => [...recs].sort((a, b) => b.saving.usd - a.saving.usd);

export interface Projection {
  before: Money; // the served Spend, as is (Measured)
  saving: Money; // simulated: per overlap group the largest saving, summed, capped at Spend
  after: Money; // simulated projection
  /** What the saving is built from, each at its own kind (ADR 0006: never merged silently). */
  from: { measured: Money | null; estimated: Money | null };
  counted: number;
  overlapping: number; // applied, but the same Waste as a larger fix: not added
  capped: boolean;
}

/** Spend before -> projected after, if these Recommendations had been in place for the same Sessions. */
export function project(spend: Money, recs: Recommendation[], caps?: Record<string, number>): Projection {
  const best = new Map<string, Recommendation>();
  for (const r of recs) {
    const k = wasteKey(r);
    const cur = best.get(k);
    if (!cur || r.saving.usd > cur.saving.usd) best.set(k, r);
  }
  // Per target: no Initiative (or Team) saves more than its own Spend, when `caps` gives it.
  const perTarget = new Map<string, { usd: number; measured: number; estimated: number }>();
  for (const r of best.values()) {
    const k = `${r.target_type}:${r.target_id}`;
    const t = perTarget.get(k) ?? { usd: 0, measured: 0, estimated: 0 };
    t.usd += r.saving.usd;
    t[r.saving.kind] += r.saving.usd;
    perTarget.set(k, t);
  }
  let usd = 0;
  let capped = false;
  const part = { measured: 0, estimated: 0 };
  for (const [k, t] of perTarget) {
    const cap = caps?.[k];
    const f = cap != null && t.usd > cap ? cap / t.usd : 1; // scale both kinds down to the cap
    if (f < 1) capped = true;
    usd += t.usd * f;
    part.measured += t.measured * f;
    part.estimated += t.estimated * f;
  }
  capped = capped || usd > spend.usd;
  const saving = Math.min(usd, spend.usd);
  const sim = (x: number): Money => ({ usd: x, kind: "estimated", note: "simulated" });
  const src = (kind: "measured" | "estimated"): Money | null => (part[kind] > 0 ? { usd: part[kind], kind } : null);
  return {
    before: spend, saving: sim(saving), after: sim(spend.usd - saving),
    from: { measured: src("measured"), estimated: src("estimated") },
    counted: best.size, overlapping: recs.length - best.size, capped,
  };
}

/** The drop as a share of Spend, for copy like "−12% Spend (simulated)". Not a $ figure. */
export const shareOf = (part: Money, whole: Money) => (whole.usd > 0 ? (part.usd / whole.usd) * 100 : 0);
