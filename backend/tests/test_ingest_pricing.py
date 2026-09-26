import pytest

from dwight import config, db, pricing
from dwight.ingest.builder import SessionBuilder
from dwight.ingest.otlp import ingest_file, ingest_payload

TRACER = config.OTLP_FIXTURES_DIR / "tracer_session.json"


def test_call_spend_is_tokens_times_price():
    # glm-4.7: input 0.60, cache_read 0.11, output 2.20 per 1M. input_tokens includes cached ones.
    assert pricing.call_spend("glm-4.7", 2820, 240, cache_read_tokens=1792) == pytest.approx(
        (1028 * 0.60 + 1792 * 0.11 + 240 * 2.20) / 1e6)


def test_provider_deployment_path_resolves_to_pool_model():
    # The harness records the model string it sent to Sciforium.
    assert pricing.normalise_model("/deployments/506a9a37/deepseek-ai/DeepSeek-V4.1-Flash") == "deepseek-v4.1-flash"
    assert pricing.normalise_model("/deployments/abc/zai-org/GLM-5.3-Flash") == "glm-5.3-flash"
    # Pool models are light tier: never re-priced for Model Overkill (synthetic layer only).
    assert pricing.cheaper_model("/deployments/506a9a37/deepseek-ai/DeepSeek-V4.1-Flash") is None
    assert pricing.cheaper_model("glm-5.3-flash") is None


def test_unknown_model_fails_loudly():
    with pytest.raises(pricing.UnknownModel):
        pricing.price("gpt-imaginary")


def test_tracer_session_ingested_and_priced(conn):
    assert ingest_file(conn, TRACER) == ["tracer-0001"]
    s = db.rows(conn, "SELECT * FROM sessions")[0]
    assert (s["member_id"], s["team"], s["business_function"], s["agent"]) == (
        "m-001", "Platform", "Engineering", "dwight-harness")
    assert s["call_count"] == 3
    calls = db.rows(conn, "SELECT * FROM calls ORDER BY seq")
    assert [c["cache_read_tokens"] for c in calls] == [0, 1792, 2816]
    expected = sum(pricing.call_spend(c["model"], c["input_tokens"], c["output_tokens"],
                                      c["cache_read_tokens"], c["cache_write_tokens"]) for c in calls)
    assert s["spend_usd"] == pytest.approx(expected)
    assert s["spend_usd"] == pytest.approx(0.00334208)
    tools = db.rows(conn, "SELECT * FROM tool_calls ORDER BY call_id")
    assert [(t["call_id"], t["name"], t["result_tokens"]) for t in tools] == [
        ("tracer-0001:0", "read_file", 900), ("tracer-0001:1", "write_file", 12)]


def test_raw_content_only_in_staging(conn):
    ingest_file(conn, TRACER)
    kinds = {r["kind"] for r in db.rows(conn, "SELECT kind FROM staging_content")}
    assert {"input_messages", "output_messages", "tool_arguments", "tool_result"} <= kinds


def test_reingest_is_idempotent_and_keeps_derived_fields(conn):
    ingest_file(conn, TRACER)
    conn.execute("UPDATE sessions SET initiative_id='x', summary='s' WHERE session_id='tracer-0001'")
    ingest_file(conn, TRACER)
    s = db.rows(conn, "SELECT * FROM sessions")[0]
    assert s["initiative_id"] == "x"
    assert conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 3


def test_builder_roundtrip_with_experiment_tags(conn):
    b = SessionBuilder("s-1", member_id="m-9", team="Growth", business_function="Marketing",
                       experiment="after", task_id="t01", task_success=True)
    c = b.call(model="glm-4.5-air", input_tokens=1000, output_tokens=100)
    b.tool(c, "read_doc", {"doc_id": "x"}, "text", result_tokens=50)
    ingest_payload(conn, b.otlp())
    s = db.rows(conn, "SELECT * FROM sessions")[0]
    assert (s["experiment"], s["experiment_task_id"], s["task_success"]) == ("after", "t01", 1)
    assert s["spend_usd"] == pytest.approx((1000 * 0.20 + 100 * 1.10) / 1e6)
