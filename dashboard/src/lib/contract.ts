// TypeScript mirror of the frozen API contract: backend/dwight/api/contract.py
// (source of truth; endpoint list in docs/api-contract.md). Keep in sync; don't
// change shapes without flagging it to the team.

export type Kind = "measured" | "estimated";
export type WastePattern = "redundant_read" | "cache_miss" | "runaway_loop" | "model_overkill";
export type RecurringForm = "common_path" | "repeated_discovery";
export type Complexity = "low" | "med" | "high";
export type Source = "store" | "fixture";

/** Every dollar figure in every response. Render only with <Money/> or formatMoney(). */
export interface Money {
  usd: number;
  kind: Kind;
  note?: string | null;
}

interface Envelope {
  source: Source;
}

// --- Overview -----------------------------------------------------------------
export interface TeamSpend { team: string; spend: Money; session_count: number }
export interface BusinessFunctionSpend {
  business_function: string;
  spend: Money;
  session_count: number;
  teams: TeamSpend[];
}
export interface Overview extends Envelope {
  period: { start?: string | null; end?: string | null };
  session_count: number;
  spend: Money;
  measured_waste: Money;
  estimated_saving: Money;
  spend_by_business_function: BusinessFunctionSpend[];
}

// --- Initiatives ----------------------------------------------------------------
export interface InitiativeRow {
  initiative_id: string;
  name: string;
  business_function?: string | null;
  session_count: number;
  spend: Money;
  measured_waste: Money;
  estimated_saving: Money;
  top_waste_pattern?: WastePattern | null;
  /** Added after the freeze (additive): Spend by Team, ranked by Spend. May be absent in fixtures. */
  teams?: TeamSpend[];
}
export interface InitiativeList extends Envelope { items: InitiativeRow[] }
export interface Initiative extends Envelope {
  initiative_id: string;
  name: string;
  description?: string | null;
  business_function?: string | null;
  session_count: number;
  spend: Money;
  teams?: TeamSpend[]; // additive: Spend by Team, ranked by Spend
}

// --- Initiative detail panels ------------------------------------------------------
export interface PatternBreakdown {
  pattern: WastePattern;
  amount: Money;
  finding_count: number;
  session_count: number;
}
export interface WasteBreakdown extends Envelope {
  initiative_id: string;
  measured_total: Money;
  estimated_total: Money;
  patterns: PatternBreakdown[];
}
export interface ResourceRef { resource_id: string; tokens?: number | null }
export interface RecurringDiscoveryItem {
  recurring_discovery_id: string;
  form: RecurringForm;
  resources: ResourceRef[];
  statement?: string | null;
  tokens?: number | null;
  session_count: number;
  session_share: number;
  cost: Money;
  evidence: string[];
}
export interface RecurringDiscoveries extends Envelope {
  initiative_id: string;
  initiative_session_count: number;
  items: RecurringDiscoveryItem[];
}
export interface MeasuredDrop { token_drop_pct: number; spend_drop: Money; counts: boolean }
export interface PolicyPrefill { team: string; allowed_models: string[] }
export interface Recommendation {
  recommendation_id: string;
  target_type: "initiative" | "team" | "policy";
  target_id: string;
  practice: { practice_id: string; title: string };
  title: string;
  body: string;
  infra_refs: string[];
  saving: Money;
  draft_id?: string | null;
  recurring_discovery_id?: string | null;
  measured_drop?: MeasuredDrop | null;
  policy_prefill?: PolicyPrefill | null;
  /** Additive: Recommendations in one group remove the same Waste; only the largest saving counts. */
  overlap_group?: string | null;
}
export interface RecommendationList extends Envelope { items: Recommendation[] }
export interface Draft extends Envelope {
  draft_id: string;
  recommendation_id?: string | null;
  initiative_id?: string | null;
  type: "initiative_doc" | "memory";
  title: string;
  filename: string;
  content: string;
  source_resource_ids: string[];
  tokens: number;
  source_tokens?: number | null;
}
export interface DraftList extends Envelope { items: Draft[] }
export interface ExperimentTotals {
  session_count: number;
  tasks_passed: number;
  tasks_total: number;
  success_rate: number;
  total_tokens: number;
  avg_tokens: number;
  spend: Money;
}
export interface BeforeAfter extends Envelope {
  initiative_id: string;
  has_runs: boolean;
  before?: ExperimentTotals | null;
  after?: ExperimentTotals | null;
  token_drop_pct?: number | null;
  spend_drop?: Money | null;
  success_held?: boolean | null;
}
export interface SessionRow {
  session_id: string;
  member_id: string;
  team: string;
  business_function: string;
  agent: string;
  started_at: string;
  ended_at: string;
  summary?: string | null;
  complexity?: Complexity | null;
  call_count: number;
  total_tokens: number;
  spend: Money;
  waste_patterns: WastePattern[];
  experiment?: "before" | "after" | null;
  task_success?: boolean | null;
}
export interface SessionList extends Envelope { items: SessionRow[] }

// --- Policy ----------------------------------------------------------------------------
export interface PolicyOptions extends Envelope {
  teams: { team: string; business_function: string }[];
  models: { model: string; tier: string }[];
}
export interface PolicyRequest { team: string; allowed_models: string[] }
export interface PolicyRender extends Envelope {
  team: string;
  allowed_models: string[];
  format: "litellm";
  rendered_config: string;
}
export interface Policy extends Envelope {
  policy_id: string;
  team: string;
  allowed_models: string[];
  rendered_config: string;
  output_path?: string | null;
  applied_at: string;
}
export interface PolicyList extends Envelope { items: Policy[] }

// --- Closing numbers -------------------------------------------------------------------
export interface ClosingNumbers extends Envelope {
  spend_analysed: Money;
  measured_waste: Money;
  measured_waste_real_layer: Money;
  estimated_saving: Money;
  draft_token_drop_pct?: number | null;
  classifier_accuracy?: number | null;
  classifier_eval_sessions?: number | null;
}

// --- Live agent run (additive; backend/dwight/live_run.py) ----------------------------------
export interface AppliedFile { draft_id: string; filename: string; type: "initiative_doc" | "memory"; tokens: number }
export interface LiveTask {
  task_id: string;
  session_id: string;
  status: "queued" | "running" | "done" | "failed";
  calls: number;
  tokens: number;
  last_tools: string[];
  task_success?: boolean | null;
  spend?: Money | null;
  before_tokens?: number | null;
  before_spend?: Money | null;
  before_success?: boolean | null;
  error?: string | null;
  check_notes?: string[];
}
export interface LiveRun extends Envelope {
  run_id: string;
  recommendation_id: string;
  initiative_id: string;
  status: "applying" | "running" | "done" | "failed" | "timed_out";
  model: string;
  started_at: string;
  finished_at?: string | null;
  elapsed_s: number;
  applied_files: AppliedFile[];
  tasks: LiveTask[];
  result?: BeforeAfter | null;
  message?: string | null;
}
export interface LiveRunStatus extends Envelope {
  enabled: boolean;
  eligible: boolean;
  reason?: string | null;
  task_count: number;
  model?: string | null;
  applied_drafts: AppliedFile[];
  run?: LiveRun | null;
  recorded?: BeforeAfter | null;
}

// --- Health ------------------------------------------------------------------------------
export interface Health {
  ok: boolean;
  db_path: string;
  sessions: number;
  endpoint_sources: Record<string, Source>;
  /** DWIGHT_PRICE_MULTIPLIER: every served $ is list price × this (1 = list prices). Additive. */
  price_multiplier?: number;
}

// --- Display names (glossary terms, CONTEXT.md) ------------------------------------------
export const WASTE_PATTERN_LABEL: Record<WastePattern, string> = {
  redundant_read: "Redundant Read",
  cache_miss: "Cache Miss",
  runaway_loop: "Runaway Loop",
  model_overkill: "Model Overkill",
};
