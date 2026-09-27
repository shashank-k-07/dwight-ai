from fastapi.testclient import TestClient

from dwight import config, db
from dwight.api.main import app
from dwight.ingest.otlp import ingest_file

client = TestClient(app)


def test_overview_shows_tracer_spend_from_store():
    conn = db.connect()
    conn.execute("DELETE FROM sessions")
    ingest_file(conn, config.OTLP_FIXTURES_DIR / "tracer_session.json")
    conn.close()
    r = client.get("/api/overview").json()
    assert r["source"] == "store"
    assert r["session_count"] == 1
    assert r["spend"] == {"usd": 0.003342, "kind": "measured", "note": None}
    assert r["spend_by_business_function"][0]["business_function"] == "Engineering"


def test_fixture_endpoints_serve():
    for path in ["/api/initiatives", "/api/initiatives/storage-cost-reduction",
                 "/api/initiatives/storage-cost-reduction/waste",
                 "/api/initiatives/storage-cost-reduction/recurring-discoveries",
                 "/api/initiatives/storage-cost-reduction/recommendations",
                 "/api/initiatives/storage-cost-reduction/drafts", "/api/drafts/d-scr-doc",
                 "/api/initiatives/storage-cost-reduction/before-after",
                 "/api/initiatives/storage-cost-reduction/sessions", "/api/policy/options",
                 "/api/policies", "/api/closing-numbers", "/api/recommendations?target_type=policy",
                 "/api/health"]:
        r = client.get(path)
        assert r.status_code == 200, path
    assert client.get("/api/drafts/d-scr-doc/download").headers["content-disposition"].startswith("attachment")
    assert client.post("/api/policy/render", json={"team": "Platform", "allowed_models": ["glm-4.7"]}).status_code == 200


def test_otlp_http_receiver():
    body = (config.OTLP_FIXTURES_DIR / "tracer_session.json").read_text()
    r = client.post("/v1/traces", content=body, headers={"content-type": "application/json"})
    assert r.json()["dwight_sessions"] == ["tracer-0001"]
