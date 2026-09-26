"""Classifier accuracy eval (ticket 08). No live model calls: dwight.glm.chat_json is mocked."""
import json

import pytest
from fastapi.testclient import TestClient

from dwight import config, glm
from dwight import eval as ev
from dwight.api.main import app
from dwight.api.serving import get_conn
from dwight.classifier import model as cmodel
from dwight.pipeline import discover


class AlwaysStorage:
    """Stands in for glm.chat_json: every Session goes to storage-cost-reduction."""

    def __init__(self):
        self.calls = []

    def __call__(self, messages, *, schema=None, **kw):
        self.calls.append(messages)
        return schema.model_validate({"summary": "Did work.", "initiative_id": "storage-cost-reduction",
                                      "complexity": "med", "discoveries": []})


@pytest.fixture
def fake(monkeypatch):
    f = AlwaysStorage()
    monkeypatch.setattr(glm, "chat_json", f)
    return f


@pytest.fixture
def mini(tmp_path, monkeypatch):
    """A tiny 'synthetic' layer: the fixture OTLP payloads as JSON lines, and a ground
    truth that puts every even Session in storage-cost-reduction, every odd one in
    auth-migration, with every third Session ambiguous."""
    payloads = json.loads((config.OTLP_FIXTURES_DIR / "fixture_sessions.json").read_text())
    otlp = tmp_path / "otlp"
    otlp.mkdir()
    (otlp / "day-1.jsonl").write_text("\n".join(json.dumps(p) for p in payloads) + "\n")
    from dwight.ingest.otlp import _collect
    sids = sorted({sid for p in payloads for sid in _collect(p)})
    truth = tmp_path / "truth.jsonl"
    truth.write_text("\n".join(json.dumps({
        "session_id": sid, "initiative_id": "storage-cost-reduction" if i % 2 == 0 else "auth-migration",
        "complexity": "med" if i % 4 else "low", "ambiguous": i % 3 == 0}) for i, sid in enumerate(sids)) + "\n")
    monkeypatch.setattr(ev, "GROUND_TRUTH_PATH", truth)
    monkeypatch.setattr(ev, "SYNTHETIC_OTLP_DIR", otlp)
    return sids


def stage(conn, *args):
    return discover()["eval_classifier"].run(conn, list(args))


def test_sample_is_stratified_and_deterministic():
    truth = {f"s{i:03d}": ev.Truth(f"s{i:03d}", f"init-{i % 3}", "med", i % 5 == 0) for i in range(90)}
    a = ev.stratified_sample(truth, per_initiative=10, ambiguous_per_initiative=3, seed=1)
    assert a == ev.stratified_sample(truth, per_initiative=10, ambiguous_per_initiative=3, seed=1)
    assert a != ev.stratified_sample(truth, per_initiative=10, ambiguous_per_initiative=3, seed=2)
    assert len(a) == 30
    for k in range(3):
        mine = [s for s in a if truth[s].initiative_id == f"init-{k}"]
        assert len(mine) == 10 and sum(truth[s].ambiguous for s in mine) == 3


def test_score_reports_accuracy_and_confusion():
    truth = {"a": ev.Truth("a", "x", "low", False), "b": ev.Truth("b", "x", "med", True),
             "c": ev.Truth("c", "y", "med", False), "d": ev.Truth("d", "y", "high", True)}
    r = ev.score({"a": "x", "b": "y", "c": "y", "d": "y", "zz": "x"}, truth,
                 {"a": "low", "b": "low", "c": "med", "d": "med"})
    assert r["n_sessions"] == 4 and r["correct"] == 3 and r["accuracy"] == 0.75
    assert r["accuracy_clear"] == 1.0 and r["accuracy_ambiguous"] == 0.5
    assert r["accuracy_population_weighted"] == 0.75           # half the population is ambiguous
    assert r["per_initiative"]["x"] == {"n": 2, "correct": 1, "recall": 0.5, "precision": 1.0,
                                        "confused_with": {"y": 1}}
    assert r["per_initiative"]["y"]["precision"] == pytest.approx(0.6667)
    assert r["top_confusions"] == {"x -> y": 1}
    assert r["complexity_accuracy"] == 0.5
    assert "x" in ev.report(r, "t")


def test_sample_reingests_classifies_scores_and_records(conn, fake, mini):
    msg = stage(conn, "sample", "--per-initiative", "4", "--ambiguous", "1", "--workers", "2")
    assert "accuracy 0.500 over 8/8" in msg
    assert len(fake.calls) == 8
    row = conn.execute("SELECT label, accuracy, n_sessions, details_json FROM eval_runs").fetchone()
    assert row["accuracy"] == 0.5 and row["n_sessions"] == 8
    assert row["label"].startswith(cmodel.PROMPT_VERSION)
    details = json.loads(row["details_json"])
    assert details["mode"] == "sample" and details["reingested"] == 8 and details["thinking"] == "off"
    assert details["per_initiative"]["auth-migration"]["confused_with"] == {"storage-cost-reduction": 4}
    # Only the sample was ingested, and classifying discarded its staged content.
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 8
    assert conn.execute("SELECT COUNT(*) FROM staging_content").fetchone()[0] == 0

    # Running it again (after a prompt change) re-ingests the same sample and classifies it again.
    stage(conn, "sample", "--per-initiative", "4", "--ambiguous", "1", "--workers", "2")
    assert len(fake.calls) == 16
    assert conn.execute("SELECT COUNT(*) FROM eval_runs").fetchone()[0] == 2

    # --no-classify re-scores without model calls.
    stage(conn, "sample", "--per-initiative", "4", "--ambiguous", "1", "--no-classify")
    assert len(fake.calls) == 16


def test_score_mode_uses_the_classified_store_without_model_calls(conn, fake, mini):
    discover()["ingest"].run(conn, [str(ev.SYNTHETIC_OTLP_DIR)])
    discover()["classify"].run(conn, ["--workers", "2"])
    n_calls = len(fake.calls)
    msg = stage(conn, "score", "--label", "final store")
    assert len(fake.calls) == n_calls
    n = len(mini)
    expected = round(sum(1 for i in range(n) if i % 2 == 0) / n, 4)
    row = conn.execute("SELECT label, accuracy, n_sessions FROM eval_runs").fetchone()
    assert row["label"] == "final store" and row["n_sessions"] == n and row["accuracy"] == expected
    assert f"over {n} Sessions" in msg


def test_score_mode_with_nothing_classified_records_nothing(conn, mini):
    assert "nothing recorded" in stage(conn, "score")
    assert conn.execute("SELECT COUNT(*) FROM eval_runs").fetchone()[0] == 0


def test_score_row_is_what_closing_numbers_serves(conn, fake, mini):
    """score -> eval_runs row -> /api/closing-numbers (the route reads the latest row by created_at)."""
    discover()["ingest"].run(conn, [str(ev.SYNTHETIC_OTLP_DIR)])
    discover()["classify"].run(conn, ["--workers", "2"])
    ev.record(conn, {"accuracy": 0.1, "n_sessions": 3}, label="older")
    conn.execute("UPDATE eval_runs SET created_at = '2000-01-01T00:00:00Z'")
    conn.commit()
    stage(conn, "score")
    row = conn.execute("SELECT eval_id, created_at, label, accuracy, n_sessions, details_json FROM eval_runs "
                       "ORDER BY created_at DESC, eval_id DESC LIMIT 1").fetchone()
    n = len(mini)
    assert row["label"] == f"{cmodel.PROMPT_VERSION} store" and row["n_sessions"] == n
    assert row["created_at"].endswith("Z") and 0 < row["accuracy"] < 1
    assert json.loads(row["details_json"])["prompt_version"] == cmodel.PROMPT_VERSION
    app.dependency_overrides[get_conn] = lambda: conn
    try:
        body = TestClient(app).get("/api/closing-numbers").json()
    finally:
        app.dependency_overrides.clear()
    assert body["classifier_accuracy"] == row["accuracy"] and body["classifier_eval_sessions"] == n


def test_prompt_shows_each_initiatives_business_function_not_ground_truth():
    prompt = cmodel._user_prompt("t", cmodel.candidates(), {"team": "Platform"})
    assert "storage-cost-reduction: Storage cost reduction [Engineering] —" in prompt
    assert "primary_teams" not in prompt and "data-infra" not in prompt
