"""Ticket 14: Policy options, LiteLLM render, Apply (file + policies row), prefill."""
import json

import pytest
import yaml
from fastapi.testclient import TestClient

from dwight import config, db, policy_export
from dwight.api.main import app
from dwight.pipeline.stages import seed_fixtures

client = TestClient(app)


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    d = tmp_path / "policies"
    monkeypatch.setattr(config, "POLICY_OUT_DIR", d)
    return d


def test_options_come_from_org_and_infra_profile():
    r = client.get("/api/policy/options").json()
    assert r["source"] == "store"
    teams = {t["team"]: t["business_function"] for t in r["teams"]}
    assert len(teams) == 12
    assert teams["Data Infrastructure"] == "Engineering"
    assert teams["Growth Marketing"] == "Marketing"
    assert r["models"] == [{"model": "glm-5.1", "tier": "flagship"},
                           {"model": "glm-4.7", "tier": "standard"},
                           {"model": "glm-4.5-air", "tier": "economy"}]


def test_render_is_litellm_team_allowlist_yaml():
    r = client.post("/api/policy/render",
                    json={"team": "data-infra", "allowed_models": ["glm-4.5-air", "glm-4.7", "glm-4.7"]}).json()
    assert r["source"] == "store" and r["format"] == "litellm"
    assert r["team"] == "Data Infrastructure"
    assert r["allowed_models"] == ["glm-4.7", "glm-4.5-air"]   # deduped, tier order
    cfg = yaml.safe_load(r["rendered_config"])
    [team] = cfg["teams"]
    assert team["team_alias"] == "data-infra"
    # model names plus their gateway aliases, so either way of calling a model is covered
    assert team["models"] == ["glm-4.7", "kestrel-standard", "glm-4.5-air", "kestrel-economy"]
    assert "glm-5.1" not in team["models"] and "kestrel-flagship" not in team["models"]
    assert team["metadata"]["managed_by"] == "dwight"
    assert "ADR 0002" in r["rendered_config"]


def test_render_quotes_awkward_team_names():
    r = client.post("/api/policy/render", json={"team": "Accounting & FP&A", "allowed_models": ["glm-4.7"]}).json()
    assert yaml.safe_load(r["rendered_config"])["teams"][0]["metadata"]["team"] == "Accounting & FP&A"


def test_render_with_no_models_exports_nothing():
    r = client.post("/api/policy/render", json={"team": "Routing", "allowed_models": []}).json()
    assert r["allowed_models"] == []
    assert yaml.safe_load(r["rendered_config"]) is None   # comments only, never `models: []`


@pytest.mark.parametrize("body", [{"team": "Nope", "allowed_models": ["glm-4.7"]},
                                  {"team": "Routing", "allowed_models": ["gpt-4o"]}])
def test_render_rejects_unknown_team_or_model(body):
    r = client.post("/api/policy/render", json=body)
    assert r.status_code == 400
    assert "org.yaml" in r.json()["detail"] or "Infra Profile" in r.json()["detail"]


def test_apply_writes_file_and_stores_policy(out_dir):
    conn = db.connect()
    conn.execute("DELETE FROM policies")
    conn.commit()
    body = {"team": "Routing", "allowed_models": ["glm-4.7", "glm-4.5-air"]}
    p = client.post("/api/policy/apply", json=body).json()
    assert p["source"] == "store"
    path = out_dir / "routing.yaml"
    assert path.read_text() == p["rendered_config"]
    assert p["output_path"] == str(path)          # outside the repo -> absolute
    assert yaml.safe_load(path.read_text())["teams"][0]["team_alias"] == "routing"

    row = conn.execute("SELECT team, allowed_models_json, output_path FROM policies WHERE policy_id=?",
                       (p["policy_id"],)).fetchone()
    assert row["team"] == "Routing" and json.loads(row["allowed_models_json"]) == ["glm-4.7", "glm-4.5-air"]

    # Re-applying replaces the Team's file and adds a new record; the list is newest first.
    p2 = client.post("/api/policy/apply", json={"team": "Routing", "allowed_models": ["glm-4.5-air"]}).json()
    assert yaml.safe_load(path.read_text())["teams"][0]["models"] == ["glm-4.5-air", "kestrel-economy"]
    items = client.get("/api/policies").json()["items"]
    assert [i["policy_id"] for i in items][:2] == [p2["policy_id"], p["policy_id"]]
    conn.close()


def test_apply_refuses_empty_allowlist(out_dir):
    r = client.post("/api/policy/apply", json={"team": "Routing", "allowed_models": []})
    assert r.status_code == 400
    assert not out_dir.exists()


def test_seeded_policy_is_listed(conn):
    seed_fixtures.run(conn, [])
    items = policy_export.list_policies(conn)["items"]
    assert items[0]["policy_id"] == "pol-001" and items[0]["allowed_models"] == ["glm-4.7", "glm-4.5-air"]


def test_prefill_from_policy_recommendation_row(conn):
    seed_fixtures.run(conn, [])
    rec = db.rows(conn, "SELECT target_id, suggested_models_json FROM recommendations WHERE target_type='policy'")[0]
    pre = policy_export.prefill(rec["target_id"], rec["suggested_models"])
    assert pre == {"team": "Routing", "allowed_models": ["glm-4.7", "glm-4.5-air"]}
    # and the prefill renders as-is
    assert policy_export.render(pre["team"], pre["allowed_models"])["allowed_models"] == pre["allowed_models"]
    assert policy_export.prefill("routing", ["glm-9"]) is None
    assert policy_export.prefill("Nope", ["glm-4.7"]) is None
    assert policy_export.prefill("Routing", None) is None
