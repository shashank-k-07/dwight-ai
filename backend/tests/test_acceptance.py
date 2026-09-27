"""Ticket 15: the one-command rebuild and the acceptance checks. No model calls."""
from types import SimpleNamespace

import pytest

from dwight import config
from dwight.api.routes import closing_numbers
from dwight.ingest.otlp import ingest_file
from dwight.pipeline import __main__ as cli
from dwight.pipeline import discover
from dwight.pipeline.stages import acceptance

REAL = config.DATA_DIR / "otlp" / "real"


def test_rebuild_runs_every_stage_in_order_then_the_checks(monkeypatch, tmp_path):
    ran = []
    stages = {n: SimpleNamespace(name=n, in_default_run=d) for n, d in
              [("ingest", True), ("classify", True), ("draft", True), ("draft_check", False),
               ("seed_fixtures", False), ("acceptance", False), ("eval_classifier", False)]}
    monkeypatch.setattr(cli, "_run", lambda s, args: ran.append((s.name, args)) or True)
    monkeypatch.setattr(cli, "_reset", lambda: ran.append(("reset", [])))
    monkeypatch.setattr(cli, "SYNTHETIC_OTLP_DIR", REAL)   # non-empty: no generation
    assert cli.rebuild(stages) == 0
    assert [n for n, _ in ran] == ["reset", "ingest", "classify", "draft", "eval_classifier", "draft_check",
                                   "acceptance"]
    assert dict(ran)["eval_classifier"][0] == "score"   # no model calls
    assert dict(ran)["draft"] == ["--pinned", str(config.DATA_DIR / "drafts")]

    ran.clear()
    monkeypatch.setattr(cli, "_run", lambda s, args: ran.append((s.name, args)) or s.name != "classify")
    assert cli.rebuild(stages, keep=True) == 1
    assert [n for n, _ in ran] == ["ingest", "classify"]   # stops at the first failure, --keep skips reset


def test_rebuild_is_the_only_extra_command_and_real_stages_exist():
    stages = discover()
    assert "acceptance" in stages and not stages["acceptance"].in_default_run
    assert set(cli.rebuild_args()) <= set(stages)


@pytest.fixture
def real_store(conn):
    for sid in ("real-001", "real-015", "real-024", "real-033"):   # clean, RR, Cache Miss, Runaway Loop
        ingest_file(conn, REAL / f"{sid}.json")
    discover()["detect"].run(conn, [])
    return conn


def test_detectors_scored_against_the_real_labels(real_store):
    r = acceptance.check_detectors(real_store, loop_min=3)
    per = r["per_pattern"]
    assert per["redundant_read"]["flagged"] == per["redundant_read"]["planted"] == 1
    assert per["runaway_loop"]["flagged"] == 1
    # Sciforium reports no cache reads, so the planted Cache Miss can't be observed
    assert per["cache_miss"] == {"planted": 1, "flagged": 0, "not_observable": 1, "missed": []}
    assert r["clean"]["sessions"] == 1 and not r["clean"]["unexplained"]
    assert r["real_model_overkill_findings"] == 0 and r["ok"]


def test_clean_run_with_an_unexplained_measured_finding_fails(real_store):
    real_store.execute("INSERT INTO waste_findings (finding_id, session_id, pattern, kind, usd) "
                       "VALUES ('x', 'real-001', 'runaway_loop', 'measured', 0.01)")
    r = acceptance.check_detectors(real_store, loop_min=3)
    assert r["clean"]["unexplained"] == ["real-001"] and not r["ok"]


def test_waste_totals_split_real_from_full(real_store):
    w = acceptance.waste_totals(real_store)
    assert w["real"]["measured_waste"] > 0
    assert w["real"]["measured_waste"] == pytest.approx(w["full"]["measured_waste"])
    assert w["synthetic"]["sessions"] == 0 and w["real"]["sessions"] == 4


def test_closing_numbers_from_store(real_store):
    body = closing_numbers._from_store(real_store)
    assert body["measured_waste_real_layer"]["kind"] == "measured"
    assert body["measured_waste_real_layer"]["usd"] == pytest.approx(
        acceptance.waste_totals(real_store)["real"]["measured_waste"], abs=1e-6)
    assert body["estimated_saving"]["kind"] == "estimated"
    assert body["classifier_accuracy"] is None and body["draft_token_drop_pct"] is None
    real_store.execute("INSERT INTO eval_runs (eval_id, created_at, accuracy, n_sessions) "
                       "VALUES ('e1', '2026-09-26T00:00:00Z', 0.9, 100)")
    assert closing_numbers._from_store(real_store)["classifier_accuracy"] == 0.9
