"""Demo pricing (DWIGHT_PRICE_MULTIPLIER) and the Initiative x Team split. Offline: fixture store.

Every dollar figure the API serves is scaled once, in serving.money(); percentages, token and
Session counts are not. Checked by serving every GET endpoint at x1 and x100 and comparing.
"""
import json

import pytest
from fastapi.testclient import TestClient

from dwight import config, db, demo
from dwight.api.main import app
from dwight.api.routes import closing_numbers as cn
from dwight.pipeline import discover

client = TestClient(app)
IID = "storage-cost-reduction"
PATHS = ["/api/overview", "/api/closing-numbers", "/api/initiatives", f"/api/initiatives/{IID}",
         f"/api/initiatives/{IID}/sessions", f"/api/initiatives/{IID}/waste",
         f"/api/initiatives/{IID}/recurring-discoveries", f"/api/initiatives/{IID}/recommendations",
         "/api/recommendations", "/api/recommendations?target_type=policy", f"/api/initiatives/{IID}/drafts",
         f"/api/initiatives/{IID}/before-after", "/api/policy/options", "/api/policies"]


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "store.sqlite"
    conn = db.connect(path)
    discover()["seed_fixtures"].run(conn, [])
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "PRICE_MULTIPLIER", 1.0)
    return path


def _get_all(monkeypatch, mult: float) -> dict:
    monkeypatch.setattr(config, "PRICE_MULTIPLIER", mult)
    out = {}
    for p in PATHS:
        r = client.get(p)
        assert r.status_code == 200, p
        out[p] = r.json()
    return out


def _compare(a, b, mult, path, seen):
    """b must equal a, except every Money usd is x mult."""
    if isinstance(a, dict):
        assert a.keys() == b.keys(), path
        if "usd" in a and "kind" in a:
            assert b["usd"] == pytest.approx(a["usd"] * mult, rel=1e-6, abs=1e-4), path
            seen.append(path)
            assert {k: v for k, v in a.items() if k != "usd"} == {k: v for k, v in b.items() if k != "usd"}, path
            return
        for k in a:
            _compare(a[k], b[k], mult, f"{path}.{k}", seen)
    elif isinstance(a, list):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _compare(x, y, mult, f"{path}[{i}]", seen)
    else:
        assert a == b, path   # percentages, counts, tokens, ids: never scaled


def test_every_served_dollar_is_scaled_once_and_nothing_else_is(store, monkeypatch):
    x1 = _get_all(monkeypatch, 1.0)
    x100 = _get_all(monkeypatch, 100.0)
    seen: list[str] = []
    for p in PATHS:
        _compare(x1[p], x100[p], 100.0, p, seen)
    # the paths that matter all carried Money, including the before/after Spend drop (derived)
    for must in ("/api/overview", "/api/closing-numbers", "/api/initiatives", "before-after", "recommendations",
                 "/waste", "recurring-discoveries"):
        assert any(must in s for s in seen), must
    ba1, ba100 = x1[f"/api/initiatives/{IID}/before-after"], x100[f"/api/initiatives/{IID}/before-after"]
    assert ba100["spend_drop"]["usd"] == pytest.approx(ba1["spend_drop"]["usd"] * 100, abs=1e-4)
    assert ba100["token_drop_pct"] == ba1["token_drop_pct"]


def test_fixture_bodies_are_scaled_too(monkeypatch):
    monkeypatch.setattr(config, "FORCE_FIXTURES", True)
    monkeypatch.setattr(config, "PRICE_MULTIPLIER", 1.0)
    a = client.get("/api/overview").json()
    monkeypatch.setattr(config, "PRICE_MULTIPLIER", 100.0)
    b = client.get("/api/overview").json()
    assert a["source"] == b["source"] == "fixture"
    _compare(a, b, 100.0, "overview", [])


def test_health_reports_the_multiplier(store, monkeypatch):
    assert client.get("/api/health").json()["price_multiplier"] == 1.0
    monkeypatch.setattr(config, "PRICE_MULTIPLIER", 100.0)
    assert client.get("/api/health").json()["price_multiplier"] == 100.0


def test_export_at_x100_matches_the_app_and_says_so(store, tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "COMMITTED_MANIFEST", tmp_path / "demo-snapshot.json")
    monkeypatch.setattr(config, "PRICE_MULTIPLIER", 100.0)
    conn = db.connect(store)
    md, js = demo.export(conn, tmp_path / "demo-numbers")
    body = client.get("/api/closing-numbers").json()
    conn.close()
    data = json.loads(js.read_text())
    assert data["closing_numbers"] == body and data["price_multiplier"] == 100.0
    text = md.read_text()
    assert "Demo pricing ×100" in text
    assert demo.money_text(body["spend_analysed"]) + " of Spend analysed" in text
    monkeypatch.setattr(config, "PRICE_MULTIPLIER", 1.0)
    at_list = client.get("/api/closing-numbers").json()
    assert body["spend_analysed"]["usd"] == pytest.approx(at_list["spend_analysed"]["usd"] * 100, abs=1e-4)
    assert body["draft_token_drop_pct"] == at_list["draft_token_drop_pct"]
    assert f"> - {demo.money_text(at_list['spend_analysed'])} of Spend analysed" in text


def test_export_at_x1_has_no_demo_pricing_note(store, tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "COMMITTED_MANIFEST", tmp_path / "demo-snapshot.json")
    conn = db.connect(store)
    md, _ = demo.export(conn, tmp_path / "demo-numbers")
    conn.close()
    assert "Demo pricing" not in md.read_text()


def test_snapshot_manifest_is_at_list_prices_whatever_the_setting(store, tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "SNAPSHOTS_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(demo, "COMMITTED_MANIFEST", tmp_path / "demo-snapshot.json")
    monkeypatch.setattr(config, "DRAFT_OUT_DIR", tmp_path / "out" / "drafts")
    monkeypatch.setattr(config, "POLICY_OUT_DIR", tmp_path / "out" / "policies")
    conn = db.connect(store)
    at_list = cn.closing_numbers_body(conn)
    conn.close()
    monkeypatch.setattr(config, "PRICE_MULTIPLIER", 100.0)
    m = demo.snapshot("demo")
    assert m["closing_numbers"] == at_list and m["price_multiplier"] == 1.0
    assert config.PRICE_MULTIPLIER == 100.0          # restored after the block
    assert demo.reset("demo")["warnings"] == []      # reset compares at list prices too


def test_initiatives_split_spend_by_team(store):
    items = client.get("/api/initiatives").json()["items"]
    assert items and all(r["teams"] for r in items)
    for r in items:
        assert sum(t["session_count"] for t in r["teams"]) == r["session_count"]
        assert sum(t["spend"]["usd"] for t in r["teams"]) == pytest.approx(r["spend"]["usd"], abs=1e-5)
        assert all(t["spend"]["kind"] == "measured" for t in r["teams"])
        usd = [t["spend"]["usd"] for t in r["teams"]]
        assert usd == sorted(usd, reverse=True)
    one = client.get(f"/api/initiatives/{IID}").json()
    assert one["teams"] == next(r for r in items if r["initiative_id"] == IID)["teams"]
