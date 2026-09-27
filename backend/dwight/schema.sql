-- Dwight store schema. FROZEN (ticket 01): changing it needs a flag to the team,
-- not a quiet edit. Source of truth for the data model is docs/build-spec.md §3.
--
-- Conventions
--   * money columns are *_usd REAL, always computed in code as tokens x price
--     (dwight/pricing.py). The kind (measured|estimated) travels with it where
--     it can be either.
--   * list/object columns are TEXT holding JSON (suffix _json).
--   * timestamps are ISO-8601 UTC strings.

-- One continuous run of an Agent by one Member toward one goal.
CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    member_id         TEXT NOT NULL,
    team              TEXT NOT NULL,
    business_function TEXT NOT NULL,
    agent             TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    ended_at          TEXT NOT NULL,
    dataset           TEXT NOT NULL DEFAULT 'real',     -- real | synthetic | fixture  (resource attr dwight.dataset)
    -- Experiment runs (before/after proof, tickets 04/13/16)
    experiment        TEXT,                             -- NULL | before | after       (dwight.experiment)
    experiment_task_id TEXT,                            -- same task id in before and after (dwight.experiment.task_id)
    task_success      INTEGER,                          -- NULL | 0 | 1                (dwight.experiment.task_success)
    -- Priced at ingest (sum of calls.spend_usd). Measured.
    spend_usd         REAL NOT NULL DEFAULT 0,
    total_input_tokens  INTEGER NOT NULL DEFAULT 0,
    total_output_tokens INTEGER NOT NULL DEFAULT 0,
    call_count        INTEGER NOT NULL DEFAULT 0,
    -- Derived by the classify stage (ticket 06)
    initiative_id     TEXT REFERENCES initiatives(initiative_id),
    summary           TEXT,                             -- redacted, one line
    complexity        TEXT CHECK (complexity IN ('low', 'med', 'high')),
    classified_at     TEXT,
    ingested_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_initiative ON sessions(initiative_id);

-- One model request inside a Session.
-- Token semantics follow OTel GenAI: input_tokens INCLUDES cache_read_tokens
-- and cache_write_tokens. Uncached input = input - cache_read - cache_write.
CREATE TABLE IF NOT EXISTS calls (
    call_id            TEXT PRIMARY KEY,
    session_id         TEXT NOT NULL REFERENCES sessions(session_id),
    seq                INTEGER NOT NULL,                -- 0-based order in the Session
    model              TEXT NOT NULL,                   -- normalised to a prices.yaml key
    input_tokens       INTEGER NOT NULL DEFAULT 0,
    output_tokens      INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    prompt_prefix_hash TEXT,                            -- hash of the stable prompt prefix (dwight.prompt.prefix_hash)
    prompt_prefix_tokens INTEGER,                       -- tokens in that prefix (dwight.prompt.prefix_tokens); Cache Miss needs it
    started_at         TEXT,
    spend_usd          REAL NOT NULL DEFAULT 0,         -- Measured, from prices.yaml
    UNIQUE (session_id, seq)
);

-- Tool calls the model REQUESTED in a Call (execute_tool spans whose parent is
-- that Call's chat span). Their results enter the context of Call seq+1.
-- No raw arguments or results here: those are content and live in staging.
CREATE TABLE IF NOT EXISTS tool_calls (
    call_id        TEXT NOT NULL REFERENCES calls(call_id),
    idx            INTEGER NOT NULL,                    -- order within the Call
    tool_call_id   TEXT,                                -- gen_ai.tool.call.id
    name           TEXT NOT NULL,                       -- gen_ai.tool.name
    args_hash      TEXT,
    result_hash    TEXT,
    result_tokens  INTEGER NOT NULL DEFAULT 0,          -- dwight.tool.result_tokens
    PRIMARY KEY (call_id, idx)
);

-- TRANSIENT STAGING for raw prompt content (ADRs 0005, 0008).
-- Ingest writes message content and tool arguments/results here. The classify
-- stage reads it, writes the derived fields (summary, Initiative, complexity,
-- Trail, Discoveries) and then DELETES the Session's rows. Nothing else may
-- read this table, and nothing derived may be computed from it later.
CREATE TABLE IF NOT EXISTS staging_content (
    session_id  TEXT NOT NULL,
    call_id     TEXT,
    seq         INTEGER,                                -- call seq
    kind        TEXT NOT NULL,                          -- system_instructions | input_messages | output_messages | tool_arguments | tool_result
    tool_idx    INTEGER,                                -- for tool_* kinds: tool_calls.idx
    tool_name   TEXT,
    content     TEXT NOT NULL                           -- raw JSON/text as received
);
CREATE INDEX IF NOT EXISTS idx_staging_session ON staging_content(session_id);

-- Trail: ordered resources a Session's Agent read (built by code in classify).
CREATE TABLE IF NOT EXISTS trail_entries (
    session_id  TEXT NOT NULL REFERENCES sessions(session_id),
    position    INTEGER NOT NULL,
    resource_id TEXT NOT NULL,                          -- normalised path / URL / doc ID, e.g. company-docs/storage-tiers.md
    tokens      INTEGER NOT NULL,                       -- result tokens of that read
    call_seq    INTEGER NOT NULL,                       -- seq of the Call that requested the read
    PRIMARY KEY (session_id, position)
);
CREATE INDEX IF NOT EXISTS idx_trail_resource ON trail_entries(resource_id);

-- Discoveries: short redacted statements (classify stage).
CREATE TABLE IF NOT EXISTS discoveries (
    session_id  TEXT NOT NULL REFERENCES sessions(session_id),
    idx         INTEGER NOT NULL,
    statement   TEXT NOT NULL,
    call_seq    INTEGER NOT NULL,                       -- Call where it was established
    PRIMARY KEY (session_id, idx)
);

CREATE TABLE IF NOT EXISTS initiatives (
    initiative_id     TEXT PRIMARY KEY,                 -- slug, e.g. storage-cost-reduction
    name              TEXT NOT NULL,
    description       TEXT,
    business_function TEXT,
    session_count     INTEGER NOT NULL DEFAULT 0,
    spend_usd         REAL NOT NULL DEFAULT 0          -- Measured
);

CREATE TABLE IF NOT EXISTS waste_findings (
    finding_id  TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(session_id),
    pattern     TEXT NOT NULL CHECK (pattern IN ('redundant_read', 'cache_miss', 'runaway_loop', 'model_overkill')),
    kind        TEXT NOT NULL CHECK (kind IN ('measured', 'estimated')),
    usd         REAL NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',           -- call IDs involved
    detail      TEXT                                    -- optional human-readable note
);
CREATE INDEX IF NOT EXISTS idx_findings_session ON waste_findings(session_id);

CREATE TABLE IF NOT EXISTS recurring_discoveries (
    recurring_discovery_id TEXT PRIMARY KEY,
    initiative_id     TEXT NOT NULL REFERENCES initiatives(initiative_id),
    form              TEXT NOT NULL CHECK (form IN ('common_path', 'repeated_discovery')),
    resource_ids_json TEXT,                             -- common_path: JSON list of resource IDs
    statement         TEXT,                             -- repeated_discovery: one actionable statement
    tokens            INTEGER,                          -- common_path: mean tokens per Session spent reading these resources
    session_count     INTEGER NOT NULL,
    session_share     REAL NOT NULL,                    -- 0..1 of the Initiative's Sessions
    spend_usd         REAL NOT NULL,                    -- Measured: what the repetition cost
    evidence_json     TEXT NOT NULL DEFAULT '[]'        -- session IDs
);

CREATE TABLE IF NOT EXISTS recommendations (
    recommendation_id TEXT PRIMARY KEY,
    target_type  TEXT NOT NULL CHECK (target_type IN ('initiative', 'team', 'policy')),
    target_id    TEXT NOT NULL,
    practice_id  TEXT NOT NULL,                         -- must exist in data/company/practices.yaml
    title        TEXT NOT NULL,
    body         TEXT NOT NULL,
    infra_refs_json TEXT NOT NULL DEFAULT '[]',         -- names from the Infra Profile
    usd          REAL NOT NULL,                         -- attached by code, never by the LLM
    kind         TEXT NOT NULL CHECK (kind IN ('measured', 'estimated')),
    draft_id     TEXT,
    recurring_discovery_id TEXT,                        -- set when it addresses a RecurringDiscovery
    suggested_models_json TEXT,                         -- policy Recommendations: allowed models to prefill (ticket 14)
    rank         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS drafts (
    draft_id          TEXT PRIMARY KEY,
    recommendation_id TEXT,
    initiative_id     TEXT,
    type              TEXT NOT NULL CHECK (type IN ('initiative_doc', 'memory')),
    title             TEXT NOT NULL,
    filename          TEXT NOT NULL,                    -- download name, e.g. storage-cost-reduction.md
    content           TEXT NOT NULL,                    -- markdown
    source_resource_ids_json TEXT NOT NULL DEFAULT '[]',
    tokens            INTEGER NOT NULL,
    source_tokens     INTEGER                           -- tokens of the sources it replaces
);

CREATE TABLE IF NOT EXISTS policies (
    policy_id       TEXT PRIMARY KEY,
    team            TEXT NOT NULL,
    allowed_models_json TEXT NOT NULL,
    rendered_config TEXT NOT NULL,                      -- LiteLLM team allowlist YAML
    output_path     TEXT,
    applied_at      TEXT NOT NULL
);

-- Classifier accuracy runs (ticket 08).
CREATE TABLE IF NOT EXISTS eval_runs (
    eval_id      TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL,
    label        TEXT,                                  -- e.g. "prompt v1"
    accuracy     REAL NOT NULL,                         -- 0..1
    n_sessions   INTEGER NOT NULL,
    details_json TEXT
);

-- Record of pipeline stage runs (for debugging / health).
CREATE TABLE IF NOT EXISTS stage_runs (
    stage       TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,
    message     TEXT
);
