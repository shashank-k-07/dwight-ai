"""Live agent run (dwight/live_run.py). No live model calls: the model client is a scripted fake.

The store is the fixture store plus the 10 real recorded before runs (data/otlp/real/real-scr-b-*),
so the comparison runs against real before runs, as on stage.
"""
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from dwight import config, db, live_run
from dwight.api.main import app
from dwight.harness import workspace
from dwight.ingest.otlp import ingest_file
from dwight.pipeline import discover

api = TestClient(app)
REC = "r-scr-doc"


def _response(text="Done: no changes needed.", prompt_tokens=2000, completion_tokens=100):
    msg = SimpleNamespace(content=text, tool_calls=None, reasoning_content=None, model_extra={})
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                            prompt_tokens_details=None, model_extra={})
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=usage)


class FakeClient:
    """Every Call answers at once (so every task's check fails: nothing was done)."""

    def __init__(self, fn=None):
        self.requests = []
        self.fn = fn
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        if self.fn:
            return self.fn(kw)
        return _response()


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "store.sqlite"
    conn = db.connect(path)
    discover()["seed_fixtures"].run(conn, [])
    for f in sorted((config.DATA_DIR / "otlp" / "real").glob("real-scr-b-*.json")):
        ingest_file(conn, f)
    conn.execute("UPDATE sessions SET initiative_id='storage-cost-reduction' WHERE session_id LIKE 'real-scr-b-%'")
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "LIVE_RUNS_DIR", tmp_path / "live-runs")
    monkeypatch.setattr(config, "PRICE_MULTIPLIER", 1.0)
    monkeypatch.setattr(workspace, "WORKSPACES_DIR", tmp_path / "ws")
    monkeypatch.setattr(workspace, "PRIVATE_DIR", tmp_path / "private")
    monkeypatch.setattr(live_run, "_runs", {})
    monkeypatch.setattr(live_run, "_latest", {})
    monkeypatch.setattr(live_run, "_loaded", True)
    return path


def _counts(path):
    conn = db.connect(path)
    n = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    conn.close()
    return n


def test_disabled_by_default_and_says_why(store, monkeypatch):
    monkeypatch.setattr(config, "LIVE_RUNS", False)
    s = api.get(f"/api/recommendations/{REC}/live-run").json()
    assert s["enabled"] is False and s["eligible"] is True and "DWIGHT_LIVE_RUNS" in s["reason"]
    assert s["task_count"] == 10 and s["recorded"]["has_runs"]
    assert {d["type"] for d in s["applied_drafts"]} == {"initiative_doc", "memory"}
    r = api.post(f"/api/recommendations/{REC}/live-run")
    assert r.status_code == 403


def test_only_draft_recommendations_are_eligible(store):
    conn = db.connect(store)
    other = conn.execute("SELECT recommendation_id FROM recommendations WHERE draft_id IS NULL LIMIT 1").fetchone()[0]
    ok, why = live_run.eligibility(conn, other)
    conn.close()
    assert not ok and "Draft" in why


def test_run_applies_drafts_runs_every_task_and_measures_against_real_before_runs(store, monkeypatch):
    before_sessions = _counts(store)
    client = FakeClient()
    conn = db.connect(store)
    run = live_run.start(conn, REC, client=client, background=False)
    conn.close()
    body = live_run.to_contract(run)

    assert body["status"] == "done" and body["message"] is None
    assert len(body["tasks"]) == 10 and all(t["status"] == "done" for t in body["tasks"])
    # 1. the fix was applied: both Drafts, as stored, in every Session's system prompt
    assert [a["type"] for a in body["applied_files"]] == ["initiative_doc", "memory"]
    for a in body["applied_files"]:
        assert (run.dir / "context" / a["filename"]).exists()
    sys0 = client.requests[0]["messages"][0]["content"]
    assert "# Context files" in sys0 and all(a["filename"] in sys0 for a in body["applied_files"])
    # 2. same pinned model as the before runs
    assert {r["model"] for r in client.requests} == {body["model"]}
    # 3. measured against the real before runs, with the Before/After rules
    res = body["result"]
    assert res["before"]["session_count"] == 10 and res["after"]["session_count"] == 10
    assert res["after"]["avg_tokens"] == 2100 and res["token_drop_pct"] > 90
    assert res["success_held"] is False            # the fake did nothing, so every check failed
    t = body["tasks"][0]
    assert t["before_tokens"] and t["spend"]["kind"] == "measured" and t["before_success"] is True
    assert t["check_notes"]                          # why the check failed, for the dashboard
    # nothing reached the store
    assert _counts(store) == before_sessions
    assert (run.dir / "run.sqlite").exists() and (run.dir / "run.json").exists()


def test_status_serves_the_latest_run_and_scales_dollars(store, monkeypatch):
    conn = db.connect(store)
    live_run.start(conn, REC, client=FakeClient(), background=False)
    conn.close()
    monkeypatch.setattr(config, "LIVE_RUNS", True)
    monkeypatch.setattr(config, "GLM_API_KEY", "test")
    a = api.get(f"/api/recommendations/{REC}/live-run").json()
    assert a["enabled"] and a["run"]["status"] == "done"
    monkeypatch.setattr(config, "PRICE_MULTIPLIER", 100.0)
    b = api.get(f"/api/live-runs/{a['run']['run_id']}").json()
    assert b["tasks"][0]["spend"]["usd"] == pytest.approx(a["run"]["tasks"][0]["spend"]["usd"] * 100, abs=1e-4)
    assert b["result"]["token_drop_pct"] == a["run"]["result"]["token_drop_pct"]


def test_model_errors_fail_the_run_with_a_reason(store):
    def boom(kw):
        raise RuntimeError("provider down")

    conn = db.connect(store)
    run = live_run.start(conn, REC, client=FakeClient(boom), background=False)
    conn.close()
    body = live_run.to_contract(run)
    assert body["status"] == "failed" and "provider down" in body["message"] and body["result"] is None
    assert all(t["status"] == "failed" for t in body["tasks"])


def test_a_slow_run_times_out_and_only_one_runs_at_a_time(store, monkeypatch):
    monkeypatch.setattr(live_run, "TIMEOUT_S", 0.5)

    def slow(kw):
        time.sleep(2)
        return _response()

    conn = db.connect(store)
    run = live_run.start(conn, REC, client=FakeClient(slow), background=True)
    with pytest.raises(live_run.LiveRunError) as e:
        live_run.start(conn, REC, client=FakeClient())
    assert e.value.status == 409
    conn.close()
    for _ in range(50):
        if run.status != "running" and run.status != "applying":
            break
        time.sleep(0.1)
    assert run.status == "timed_out" and live_run.to_contract(run)["result"] is None


def test_finished_runs_survive_an_api_restart(store, monkeypatch):
    conn = db.connect(store)
    run = live_run.start(conn, REC, client=FakeClient(), background=False)
    before = live_run.to_contract(run)
    monkeypatch.setattr(live_run, "_runs", {})       # a fresh API process
    monkeypatch.setattr(live_run, "_latest", {})
    assert live_run.load_saved(conn) == 1
    again = live_run.to_contract(live_run.latest(REC))
    conn.close()
    assert again["result"] == before["result"] and again["tasks"] == before["tasks"]
