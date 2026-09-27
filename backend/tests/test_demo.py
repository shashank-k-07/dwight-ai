"""Ticket 17: demo snapshot / reset / numbers export. Offline: fixture store, no model calls."""
import json
import sqlite3

import pytest

from dwight import config, db, demo
from dwight.api.routes import closing_numbers as cn
from dwight.pipeline import discover


@pytest.fixture
def demo_env(tmp_path, monkeypatch):
    store = tmp_path / "demo.sqlite"
    conn = db.connect(store)
    discover()["seed_fixtures"].run(conn, [])
    conn.close()
    monkeypatch.setattr(demo, "SNAPSHOTS_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(demo, "COMMITTED_MANIFEST", tmp_path / "demo-snapshot.json")
    monkeypatch.setattr(config, "DB_PATH", store)
    monkeypatch.setattr(config, "DRAFT_OUT_DIR", tmp_path / "out" / "drafts")
    monkeypatch.setattr(config, "POLICY_OUT_DIR", tmp_path / "out" / "policies")
    return tmp_path, store


def test_usd_matches_money_tsx():
    assert demo.usd(31234.4) == "$31,234"
    assert demo.usd(12.345) == "$12.35" and demo.usd(0) == "$0.00"
    assert demo.usd(0.158) == "$0.16" and demo.usd(0.1) == "$0.10"
    assert demo.money_text({"usd": 0.807, "kind": "measured"}) == "$0.81 [Measured]"
    assert demo.pct(75.4) == "75.4%"


def test_snapshot_then_reset_restores_store_drafts_and_policies(demo_env):
    tmp, store = demo_env
    m = demo.snapshot("demo")
    snap = tmp / "snapshots" / "demo"
    assert (snap / "store.sqlite").exists() and json.loads((tmp / "demo-snapshot.json").read_text()) == m
    assert m["row_counts"]["sessions"] > 0 and m["drafts"]
    assert m["closing_numbers"]["source"] == "store"
    assert m["before_after"]["token_drop_pct"] == 71.5 and m["before_after"]["success_held"]

    # a rehearsal: apply a Policy (row + file), wipe a table
    conn = sqlite3.connect(store)
    conn.execute("DELETE FROM waste_findings")
    conn.commit()
    conn.close()
    config.POLICY_OUT_DIR.mkdir(parents=True)
    (config.POLICY_OUT_DIR / "rehearsal-team.yaml").write_text("x: 1\n")

    r = demo.reset("demo")
    assert r["warnings"] == [] and r["policy_files_removed"] == ["rehearsal-team.yaml"]
    conn = db.connect(store)
    assert demo.numbers(conn)["closing_numbers"] == m["closing_numbers"]
    assert demo.row_counts(conn) == m["row_counts"]
    conn.close()
    for d in m["drafts"]:
        assert demo.sha256(config.DRAFT_OUT_DIR / d["filename"]) == d["sha256"]


def test_reset_refuses_a_damaged_snapshot(demo_env):
    tmp, _ = demo_env
    demo.snapshot("demo")
    with open(tmp / "snapshots" / "demo" / "store.sqlite", "ab") as f:
        f.write(b"x")
    with pytest.raises(RuntimeError, match="damaged"):
        demo.reset("demo")


def test_export_matches_the_endpoint(demo_env):
    tmp, store = demo_env
    conn = db.connect(store)
    md, js = demo.export(conn, tmp / "demo-numbers")
    body = cn.closing_numbers_body(conn)
    conn.close()
    data = json.loads(js.read_text())
    assert data["closing_numbers"] == body
    text = md.read_text()
    assert demo.money_text(body["spend_analysed"]) + " of Spend analysed" in text
    assert f"Drafts cut tokens by {demo.pct(body['draft_token_drop_pct'])} [Measured]" in text
    assert "Sciforium reports no cached-token counts" in text and "second Draft attempt" in text


def test_headline_says_so_when_success_dropped():
    body = {"spend_analysed": {"usd": 1, "kind": "measured"}, "measured_waste": {"usd": 1, "kind": "measured"},
            "measured_waste_real_layer": {"usd": 0.5, "kind": "measured"},
            "estimated_saving": {"usd": 2, "kind": "estimated"}, "draft_token_drop_pct": None,
            "classifier_accuracy": None}
    lines = demo.headline(body)
    assert any("no token drop to show" in s for s in lines) and any("no eval" in s for s in lines)
