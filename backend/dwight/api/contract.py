"""The frozen API contract (ticket 01). Response shapes for every endpoint.

Human-readable endpoint list: docs/api-contract.md. TypeScript mirror:
dashboard/src/lib/contract.ts. Changing a shape needs a flag to the team; every
fixture in backend/fixtures/api/ is validated against these models by
tests/test_contract.py.

Rules baked into the types:
  * Every dollar figure is a Money object carrying kind = measured | estimated
    (ADR 0006). There are no bare *_usd floats in any response.
  * Spend is metered tokens x list price, so it is always kind="measured".
  * Every response has `source`: "store" (computed from the store) or
    "fixture" (committed fixture JSON; the real stage hasn't landed yet).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Kind = Literal["measured", "estimated"]
WastePattern = Literal["redundant_read", "cache_miss", "runaway_loop", "model_overkill"]
RecurringForm = Literal["common_path", "repeated_discovery"]
Complexity = Literal["low", "med", "high"]
Source = Literal["store", "fixture"]


class Money(BaseModel):
    usd: float
    kind: Kind
    note: Optional[str] = None  # e.g. "conservative upper bound"


class Envelope(BaseModel):
    source: Source = "store"


# --- Overview ------------------------------------------------------------------
class TeamSpend(BaseModel):
    team: str
    spend: Money
    session_count: int


class BusinessFunctionSpend(BaseModel):
    business_function: str
    spend: Money
    session_count: int
    teams: list[TeamSpend]


class Period(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None


class Overview(Envelope):
    period: Period
    session_count: int
    spend: Money                     # measured
    measured_waste: Money            # measured
    estimated_saving: Money          # estimated
    spend_by_business_function: list[BusinessFunctionSpend]


# --- Initiatives -----------------------------------------------------------------
class InitiativeRow(BaseModel):
    initiative_id: str
    name: str
    business_function: Optional[str] = None
    session_count: int
    spend: Money                     # measured
    measured_waste: Money
    estimated_saving: Money
    top_waste_pattern: Optional[WastePattern] = None
    # Added after the freeze (additive, optional): the Initiative's Spend split by Team,
    # ranked by Spend. Feeds the Overview's Initiative x Team chart. Empty in old fixtures.
    teams: list[TeamSpend] = Field(default_factory=list)


class InitiativeList(Envelope):
    items: list[InitiativeRow]       # ranked by spend desc


class Initiative(Envelope):
    initiative_id: str
    name: str
    description: Optional[str] = None
    business_function: Optional[str] = None
    session_count: int
    spend: Money
    teams: list[TeamSpend] = Field(default_factory=list)   # additive: Spend by Team, ranked by Spend


# --- Initiative detail panels ------------------------------------------------------
class PatternBreakdown(BaseModel):
    pattern: WastePattern
    amount: Money                    # redundant_read/cache_miss/runaway_loop measured; model_overkill estimated
    finding_count: int
    session_count: int


class WasteBreakdown(Envelope):
    initiative_id: str
    measured_total: Money
    estimated_total: Money
    patterns: list[PatternBreakdown]


class ResourceRef(BaseModel):
    resource_id: str
    tokens: Optional[int] = None     # mean tokens per read


class RecurringDiscoveryItem(BaseModel):
    recurring_discovery_id: str
    form: RecurringForm
    resources: list[ResourceRef] = Field(default_factory=list)   # common_path
    statement: Optional[str] = None                             # repeated_discovery
    tokens: Optional[int] = None     # common_path: mean tokens/Session reading these resources
    session_count: int               # Sessions that show it
    session_share: float             # 0..1
    cost: Money                      # measured; repeated_discovery has note "conservative upper bound"
    evidence: list[str]              # session IDs


class RecurringDiscoveries(Envelope):
    initiative_id: str
    initiative_session_count: int
    items: list[RecurringDiscoveryItem]


class PracticeRef(BaseModel):
    practice_id: str
    title: str


class MeasuredDrop(BaseModel):
    """From before/after runs (ticket 13). Shown next to the Estimated Saving."""
    token_drop_pct: float            # 0..100
    spend_drop: Money                # measured
    counts: bool                     # False if task success dropped: don't present as a saving


class PolicyPrefill(BaseModel):
    team: str
    allowed_models: list[str]


class Recommendation(BaseModel):
    recommendation_id: str
    target_type: Literal["initiative", "team", "policy"]
    target_id: str
    practice: PracticeRef
    title: str
    body: str                        # markdown
    infra_refs: list[str]
    saving: Money                    # usd + kind attached by code (never the LLM)
    draft_id: Optional[str] = None
    recurring_discovery_id: Optional[str] = None
    measured_drop: Optional[MeasuredDrop] = None
    policy_prefill: Optional[PolicyPrefill] = None   # target_type=policy/team -> opens Policy screen prefilled
    # Added after the freeze (additive): Recommendations sharing a group remove the same Waste, so
    # their savings don't add up (the "Implement" simulation counts the largest in a group).
    overlap_group: Optional[str] = None


class RecommendationList(Envelope):
    items: list[Recommendation]


class Draft(Envelope):
    draft_id: str
    recommendation_id: Optional[str] = None
    initiative_id: Optional[str] = None
    type: Literal["initiative_doc", "memory"]
    title: str
    filename: str
    content: str                     # markdown
    source_resource_ids: list[str]
    tokens: int
    source_tokens: Optional[int] = None


class DraftList(Envelope):
    items: list[Draft]


class ExperimentTotals(BaseModel):
    session_count: int
    tasks_passed: int
    tasks_total: int
    success_rate: float              # 0..1
    total_tokens: int
    avg_tokens: float
    spend: Money                     # measured


class BeforeAfter(Envelope):
    initiative_id: str
    has_runs: bool                   # False -> panel hidden
    before: Optional[ExperimentTotals] = None
    after: Optional[ExperimentTotals] = None
    token_drop_pct: Optional[float] = None
    spend_drop: Optional[Money] = None   # measured
    success_held: Optional[bool] = None  # False -> "result doesn't count", no saving shown


class SessionRow(BaseModel):
    session_id: str
    member_id: str
    team: str
    business_function: str
    agent: str
    started_at: str
    ended_at: str
    summary: Optional[str] = None
    complexity: Optional[Complexity] = None
    call_count: int
    total_tokens: int
    spend: Money                     # measured
    waste_patterns: list[WastePattern]
    experiment: Optional[Literal["before", "after"]] = None
    task_success: Optional[bool] = None


class SessionList(Envelope):
    items: list[SessionRow]


# --- Policy --------------------------------------------------------------------------
class TeamOption(BaseModel):
    team: str
    business_function: str


class ModelOption(BaseModel):
    model: str
    tier: str


class PolicyOptions(Envelope):
    teams: list[TeamOption]
    models: list[ModelOption]


class PolicyRequest(BaseModel):
    team: str
    allowed_models: list[str]


class PolicyRender(Envelope):
    team: str
    allowed_models: list[str]
    format: Literal["litellm"] = "litellm"
    rendered_config: str             # YAML


class Policy(Envelope):
    policy_id: str
    team: str
    allowed_models: list[str]
    rendered_config: str
    output_path: Optional[str] = None
    applied_at: str


class PolicyList(Envelope):
    items: list[Policy]


# --- Closing numbers strip ---------------------------------------------------------
class ClosingNumbers(Envelope):
    spend_analysed: Money                  # measured
    measured_waste: Money                  # measured, full dataset
    measured_waste_real_layer: Money       # measured, dataset='real' only
    estimated_saving: Money                # estimated
    draft_token_drop_pct: Optional[float]  # from before/after runs (16), measured
    classifier_accuracy: Optional[float]   # 0..1, from eval (08)
    classifier_eval_sessions: Optional[int] = None


# --- Health ----------------------------------------------------------------------------
class Health(BaseModel):
    ok: bool
    db_path: str
    sessions: int
    endpoint_sources: dict[str, Source]
    price_multiplier: float = 1.0    # DWIGHT_PRICE_MULTIPLIER: every served $ is x this (1 = list prices)


# --- Live agent run (added after the freeze, additive; dwight/live_run.py) ----------
class AppliedFile(BaseModel):
    """A Draft file Dwight loaded into the Agent's starting context."""
    draft_id: str
    filename: str
    type: Literal["initiative_doc", "memory"]
    tokens: int


class LiveTask(BaseModel):
    task_id: str
    session_id: str
    status: Literal["queued", "running", "done", "failed"]
    calls: int = 0
    tokens: int = 0                          # input + output so far (final once done)
    last_tools: list[str] = Field(default_factory=list)
    task_success: Optional[bool] = None
    spend: Optional[Money] = None            # measured, once done
    before_tokens: Optional[int] = None      # this task's recorded before run
    before_spend: Optional[Money] = None     # measured
    before_success: Optional[bool] = None
    error: Optional[str] = None
    check_notes: list[str] = Field(default_factory=list)   # why the task's check passed or failed


class LiveRun(Envelope):
    run_id: str
    recommendation_id: str
    initiative_id: str
    status: Literal["applying", "running", "done", "failed", "timed_out"]
    model: str
    started_at: str
    finished_at: Optional[str] = None
    elapsed_s: float
    applied_files: list[AppliedFile]
    tasks: list[LiveTask]
    result: Optional[BeforeAfter] = None     # status=done: recorded before runs vs this batch (Measured)
    message: Optional[str] = None


class LiveRunStatus(Envelope):
    enabled: bool                            # DWIGHT_LIVE_RUNS=1 and a model key configured
    eligible: bool                           # this Recommendation can be run by the Agent
    reason: Optional[str] = None             # why not (disabled or ineligible)
    task_count: int = 0
    model: Optional[str] = None              # the pinned model the before runs used
    applied_drafts: list[AppliedFile] = Field(default_factory=list)
    run: Optional[LiveRun] = None            # the latest run for this Recommendation (this API process)
    recorded: Optional[BeforeAfter] = None   # the recorded after runs (the fallback)
