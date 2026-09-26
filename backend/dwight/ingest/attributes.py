"""Attribute names Dwight reads from OTLP. Emitters (harness 03, synthetic
generator 07) should set exactly these.

Checked against the OTel GenAI semantic conventions on 2026-09-26: semconv
registry v1.41.0 (gen_ai.* now maintained in
github.com/open-telemetry/semantic-conventions-genai, status: Development).

Semconv notes
  * gen_ai.usage.input_tokens INCLUDES cached tokens (both cache read and write).
  * Cache read:  gen_ai.usage.cache_read.input_tokens     (in semconv)
  * Cache write: gen_ai.usage.cache_creation.input_tokens (v1.41.0 registry);
                 the semconv-genai repo main renames it
                 gen_ai.usage.cache_write.input_tokens. We accept both.
  * Content: gen_ai.system_instructions, gen_ai.input.messages,
             gen_ai.output.messages (opt-in in semconv; JSON strings).
  * Tools: execute_tool spans with gen_ai.tool.name, gen_ai.tool.call.id,
           gen_ai.tool.call.arguments, gen_ai.tool.call.result.

Dwight convention: each chat span's gen_ai.input.messages carries only the
messages NEW since the previous Call (semconv lets instrumentations filter);
the classifier concatenates staged content in seq order. Full history is also
accepted but bloats staging.

Not in semconv, so Dwight defines dwight.* attributes (code note, build-spec §3):
  * Business Function / Team / Member (resource attributes, ADR 0003)
  * tool result tokens, args/result hashes (hashes are computed from content
    if absent; result tokens are estimated as chars/4 if absent)
  * prompt prefix hash + tokens (Cache Miss detector)
  * call sequence number (else ordered by span start time)
  * experiment tag, task id, task success; dataset (real | synthetic | fixture)
"""

# --- semconv -------------------------------------------------------------------
OPERATION = "gen_ai.operation.name"            # chat | execute_tool | invoke_agent
CONVERSATION_ID = "gen_ai.conversation.id"     # = Dwight session_id
AGENT_NAME = "gen_ai.agent.name"
REQUEST_MODEL = "gen_ai.request.model"
RESPONSE_MODEL = "gen_ai.response.model"
INPUT_TOKENS = "gen_ai.usage.input_tokens"
OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
CACHE_READ_TOKENS = "gen_ai.usage.cache_read.input_tokens"
CACHE_WRITE_TOKENS = ("gen_ai.usage.cache_creation.input_tokens",
                      "gen_ai.usage.cache_write.input_tokens")
SYSTEM_INSTRUCTIONS = "gen_ai.system_instructions"
INPUT_MESSAGES = "gen_ai.input.messages"
OUTPUT_MESSAGES = "gen_ai.output.messages"
TOOL_NAME = "gen_ai.tool.name"
TOOL_CALL_ID = "gen_ai.tool.call.id"
TOOL_ARGUMENTS = "gen_ai.tool.call.arguments"
TOOL_RESULT = "gen_ai.tool.call.result"
SERVICE_NAME = "service.name"

# --- dwight.* (no semconv equivalent) ------------------------------------------
# Resource attributes (ADR 0003)
BUSINESS_FUNCTION = "dwight.business_function"
TEAM = "dwight.team"
MEMBER_ID = "dwight.member.id"
DATASET = "dwight.dataset"                      # real | synthetic | fixture
# Session-level (resource or invoke_agent span)
EXPERIMENT = "dwight.experiment"                # before | after
EXPERIMENT_TASK_ID = "dwight.experiment.task_id"
EXPERIMENT_TASK_SUCCESS = "dwight.experiment.task_success"  # bool
# Call-level (chat span)
CALL_SEQ = "dwight.call.seq"
PROMPT_PREFIX_HASH = "dwight.prompt.prefix_hash"
PROMPT_PREFIX_TOKENS = "dwight.prompt.prefix_tokens"
# Tool-level (execute_tool span)
TOOL_ARGS_HASH = "dwight.tool.args_hash"
TOOL_RESULT_HASH = "dwight.tool.result_hash"
TOOL_RESULT_TOKENS = "dwight.tool.result_tokens"

CHAT_OPERATIONS = {"chat", "text_completion", "generate_content"}
