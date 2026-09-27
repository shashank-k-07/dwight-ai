"""Ticket 13: before/after totals are computed from stored experiment Sessions."""
import pytest
from fastapi.testclient import TestClient

from dwight import db
from dwight.api.contract import BeforeAfter, MeasuredDrop
from dwight.api.main import app
from dwight.api.routes import before_after as ba
from dwight.api.serving import get_conn
from dwight.pipeline.stages import seed_fixtures

SCR = "storage-cost-reduction"


@pytest.fixture
def seeded(conn):
    seed_fixtures.run(conn, [])
    return conn


def _session(conn, sid, experiment, task, success, tokens, spend, initiative="test-init", dataset="real"):
    conn.execute(
        "INSERT INTO sessions (session_id, member_id, team, business_function, agent, started_at, ended_at, "
        "dataset, experiment, experiment_task_id, task_success, spend_usd, total_input_tokens, "
        "total_output_tokens, call_count, initiative_id, ingested_at) "
        "VALUES (?, 'm1', 'Platform', 'Engineering', 'glm-harness', '2026-09-27T10:00:00Z', "
        "'2026-09-27T10:05:00Z', ?, ?, ?, ?, ?, ?, 0, 1, ?, '2026-09-27T10:06:00Z')",
        (sid, dataset, experiment, task, None if success is None else int(success), spend, tokens, initiative))


def _expected(conn, prefix):
    rows = conn.execute(
        "SELECT total_input_tokens + total_output_tokens, spend_usd, task_success FROM sessions "
        "WHERE session_id LIKE ?", (prefix + "%",)).fetchall()
    return sum(r[0] for r in rows), sum(r[1] for r in rows), sum(r[2] for r in rows), len(rows)


def test_fixture_pair_computed_from_store(seeded):
    body = ba.compute(seeded, SCR)
    BeforeAfter.model_validate({**body, "source": "store"})
    assert body["has_runs"] is True
    b_tokens, b_spend, b_pass, b_n = _expected(seeded, "fx-scr-b")
    a_tokens, a_spend, a_pass, a_n = _expected(seeded, "fx-scr-a")
    b, a = body["before"], body["after"]
    # untagged fx-scr-07/08 are in the Initiative but not in the experiment
    assert (b["session_count"], b["tasks_passed"], b["tasks_total"]) == (b_n, b_pass, b_n) == (6, 5, 6)
    assert (a["session_count"], a["tasks_passed"], a["tasks_total"]) == (a_n, a_pass, a_n) == (6, 6, 6)
    assert b["total_tokens"] == b_tokens and a["total_tokens"] == a_tokens
    assert b["spend"] == {"usd": round(b_spend, 6), "kind": "measured"}
    assert a["spend"]["kind"] == "measured"
    assert body["token_drop_pct"] == round((b_tokens / 6 - a_tokens / 6) / (b_tokens / 6) * 100, 1)
    assert body["token_drop_pct"] > 0
    assert body["spend_drop"]["kind"] == "measured"
    assert body["spend_drop"]["usd"] == pytest.approx(b_spend - a_spend, abs=1e-5)
    assert body["success_held"] is True


def test_no_experiment_runs_hides_panel(seeded):
    assert ba.compute(seeded, "k8s-upgrade") == {"initiative_id": "k8s-upgrade", "has_runs": False}
    assert ba.compute(seeded, "no-such-initiative")["has_runs"] is False
    assert ba.measured_drop(seeded, "k8s-upgrade") is None


def test_success_drop_means_result_does_not_count(conn):
    for t in ("t1", "t2"):
        _session(conn, f"b-{t}", "before", t, True, 1000, 0.10)
    _session(conn, "a-t1", "after", "t1", True, 400, 0.04)
    _session(conn, "a-t2", "after", "t2", False, 400, 0.04)
    body = ba.compute(conn, "test-init")
    assert body["token_drop_pct"] == 60.0
    assert body["success_held"] is False
    drop = ba.measured_drop(conn, "test-init")
    MeasuredDrop.model_validate(drop)
    assert drop["counts"] is False


def test_unrecorded_success_does_not_count(conn):
    _session(conn, "b-t1", "before", "t1", None, 1000, 0.10)
    _session(conn, "a-t1", "after", "t1", None, 400, 0.04)
    body = ba.compute(conn, "test-init")
    assert body["before"]["tasks_total"] == 0
    assert body["success_held"] is False


def test_only_tasks_run_on_both_sides_are_compared(conn):
    _session(conn, "b-t1", "before", "t1", True, 1000, 0.10)
    _session(conn, "b-t2", "before", "t2", True, 1000, 0.10)
    _session(conn, "b-t9", "before", "t9", False, 90000, 9.0)   # never re-run after
    _session(conn, "a-t1", "after", "t1", True, 500, 0.05)
    _session(conn, "a-t2", "after", "t2", True, 500, 0.05)
    body = ba.compute(conn, "test-init")
    assert body["before"]["session_count"] == 2
    assert body["before"]["tasks_passed"] == 2
    assert body["token_drop_pct"] == 50.0
    assert body["spend_drop"]["usd"] == pytest.approx(0.10)
    assert body["success_held"] is True


def test_unequal_run_counts_compare_per_session(conn):
    _session(conn, "b-t1", "before", "t1", True, 1000, 0.10)
    _session(conn, "a-t1a", "after", "t1", True, 500, 0.05)
    _session(conn, "a-t1b", "after", "t1", True, 500, 0.05)
    body = ba.compute(conn, "test-init")
    assert body["token_drop_pct"] == 50.0
    assert body["spend_drop"]["usd"] == pytest.approx(0.10)   # vs 2 before-sized runs


def test_real_runs_win_over_fixture_runs(seeded):
    # real before runs land (ticket 04) while the fixture pair is still in the store
    _session(seeded, "real-b-t01", "before", "t01", True, 50000, 0.5, initiative=SCR)
    body = ba.compute(seeded, SCR)
    assert body["before"]["session_count"] == 1
    assert body["after"] is None                  # real after runs (16) not in yet
    assert body.get("token_drop_pct") is None and body.get("success_held") is None
    BeforeAfter.model_validate({**body, "source": "store"})
    _session(seeded, "real-a-t01", "after", "t01", True, 20000, 0.2, initiative=SCR)
    body = ba.compute(seeded, SCR)
    assert body["token_drop_pct"] == 60.0 and body["success_held"] is True


def test_measured_drop_attached_to_draft_recommendations(seeded):
    recs = db.rows(seeded, "SELECT recommendation_id, target_type, target_id, draft_id FROM recommendations")
    ba.attach_measured_drops(seeded, recs)
    with_drop = {r["recommendation_id"] for r in recs if r.get("measured_drop")}
    assert with_drop == {"r-scr-doc", "r-scr-mem"}
    drop = next(r for r in recs if r["recommendation_id"] == "r-scr-doc")["measured_drop"]
    MeasuredDrop.model_validate(drop)
    assert drop["token_drop_pct"] == ba.compute(seeded, SCR)["token_drop_pct"]
    assert drop["counts"] is True


def test_endpoint_serves_store(seeded):
    app.dependency_overrides[get_conn] = lambda: seeded
    try:
        client = TestClient(app)
        r = client.get(f"/api/initiatives/{SCR}/before-after").json()
        assert r["source"] == "store" and r["has_runs"] is True and r["success_held"] is True
        assert client.get("/api/initiatives/k8s-upgrade/before-after").json()["has_runs"] is False
        assert client.get("/api/health").json()["endpoint_sources"]["initiative_before_after"] == "store"
    finally:
        app.dependency_overrides.pop(get_conn, None)
