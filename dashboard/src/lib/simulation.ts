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

// Recommendations fixing the same Waste carry the same figure (the API notes "not additive");
// this is the backend's grouping key (routes/recommendations.py), so one Waste counts once.
const wasteKey = (r: Recommendation) =>
  [r.target_type, r.target_id, r.recurring_discovery_id ?? "", r.saving.kind, r.saving.usd.toFixed(6)].join("|");

export interface Projection {
  before: Money; // the served Spend, as is (Measured)
  saving: Money; // simulated: sum of distinct savings, capped at Spend
  after: Money; // simulated projection
  /** What the saving is built from, each at its own kind (ADR 0006: never merged silently). */
  from: { measured: Money | null; estimated: Money | null };
  counted: number;
  overlapping: number; // implemented, but the same Waste as another one: not added again
  capped: boolean;
}

/** Spend before -> projected after, if these Recommendations had been in place for the same Sessions. */
export function project(spend: Money, recs: Recommendation[]): Projection {
  const seen = new Set<string>();
  let usd = 0;
  const part = { measured: 0, estimated: 0 };
  let overlapping = 0;
  for (const r of recs) {
    const k = wasteKey(r);
    if (seen.has(k)) {
      overlapping++;
      continue;
    }
    seen.add(k);
    usd += r.saving.usd;
    part[r.saving.kind] += r.saving.usd;
  }
  const capped = usd > spend.usd;
  const saving = Math.min(usd, spend.usd);
  const sim = (x: number): Money => ({ usd: x, kind: "estimated", note: "simulated" });
  const src = (kind: "measured" | "estimated"): Money | null => (part[kind] > 0 ? { usd: part[kind], kind } : null);
  return {
    before: spend, saving: sim(saving), after: sim(spend.usd - saving),
    from: { measured: src("measured"), estimated: src("estimated") },
    counted: seen.size, overlapping, capped,
  };
}

/** The drop as a share of Spend, for copy like "−12% Spend (simulated)". Not a $ figure. */
export const shareOf = (part: Money, whole: Money) => (whole.usd > 0 ? (part.usd / whole.usd) * 100 : 0);
