"""Ticket 09: Recommendation engine + Waste / Recommendations endpoints. GLM is mocked."""
import re

import pytest
from fastapi.testclient import TestClient

from dwight import db
from dwight.api.contract import RecommendationList, WasteBreakdown
from dwight.api.main import app
from dwight.api.serving import get_conn
from dwight.pipeline.stages import recommend, seed_fixtures
from dwight.recommend import engine
from dwight.recommend import library as lib

SCR = "storage-cost-reduction"


class FakeGLM:
    """Stands in for glm.chat_json. Reads the Groups and candidates out of the prompt and
    answers with one valid Recommendation per Group (the REQUIRED practice when given),
    plus one alternative for the first Group. `first_bad` = what to break on the first call."""

    def __init__(self, first_bad=None):
        self.calls = []
        self.first_bad = first_bad

    def __call__(self, messages, schema=None, tier=None):
        self.calls.append(messages)
        prompt = messages[1]["content"]
        recs = []
        for section in prompt.split("\n## key: ")[1:]:
            key = section.split()[0]
            req = re.search(r"REQUIRED practice for this Group: (\S+)", section)
            cands = re.findall(r"\n  - ([a-z0-9-]+): .*?Cites: ([^\n]*)", section)
            cites = dict(cands)
            picks = [req.group(1)] if req else [cands[0][0]]
            if not recs and len(cands) > 1:
                picks.append(next(c for c, _ in cands if c not in picks))
            for pid in picks:
                if any(r["practice_id"] == pid for r in recs):
                    continue
                refs = [x.strip() for x in cites[pid].split(",") if x.strip() != "none"][:1] or ["tier:standard"]
                recs.append({"addresses": key, "practice_id": pid, "title": f"Apply {pid}",
                             "body": "Sessions re-sent 2400 tokens; change the config.", "infra_refs": refs})
        cap = int(re.search(r"write between \d+ and (\d+)", prompt).group(1))
        recs = recs[:cap]
        if len(self.calls) == 1 and self.first_bad == "money":
            recs[0]["body"] = "This wastes $12.50 a month."
        if self.first_bad == "always_invalid":
            recs = [{"addresses": "nope", "practice_id": "made-up-practice", "title": "x", "body": "y",
                     "infra_refs": ["mcp:not-real"]}]
        return schema.model_validate({"recommendations": recs})


@pytest.fixture(autouse=True)
def _restore_glm():
    orig = recommend._glm_chat_json
    yield
    recommend._glm_chat_json = orig


@pytest.fixture
def seeded(conn):
    seed_fixtures.run(conn, [])
    return conn


def _run(conn, fake, args=()):
    recommend._glm_chat_json = lambda: fake
    return recommend.run(conn, list(args))


def _recs(conn, where="1=1", params=()):
    return db.rows(conn, f"SELECT * FROM recommendations WHERE {where} ORDER BY target_id, rank", params)


# --- Practice Library matching --------------------------------------------------------
def test_matching_rule_filters_by_fixes_and_infra_requirements():
    assert "semantic-response-cache" not in {p.id for p in lib.eligible_practices("redundant_read")}
    assert "vector-search-docs-index" not in {p.id for p in lib.eligible_practices("common_path")}
    assert "consolidated-initiative-doc" in {p.id for p in lib.eligible_practices("common_path")}
    assert "initiative-memory-file" in {p.id for p in lib.eligible_practices("repeated_discovery")}
    for fix in ["redundant_read", "cache_miss", "runaway_loop", "model_overkill", "common_path", "repeated_discovery"]:
        assert all(fix in p.fixes and lib.meets_requirements(p) for p in lib.eligible_practices(fix))
    assert lib.cited_refs(lib.practice("tier-routing-by-complexity"))[0] == "gateway:kestrel-llm-gateway"
    assert "tier:economy" in lib.cited_refs(lib.practice("tier-routing-by-complexity"))
    assert lib.policy_models() == ["glm-4.7", "glm-4.5-air"]


# --- Stage --------------------------------------------------------------------------------
def test_top3_initiatives_get_two_valid_recommendations(seeded):
    msg = _run(seeded, FakeGLM())
    assert "0 fallback" in msg
    top3 = [r["initiative_id"] for r in db.rows(seeded, "SELECT initiative_id FROM initiatives "
                                                        "ORDER BY spend_usd DESC LIMIT 3")]
    for iid in top3:
        recs = _recs(seeded, "target_type='initiative' AND target_id=?", (iid,))
        assert len(recs) >= 2, iid
    for r in _recs(seeded):
        assert lib.practice(r["practice_id"]) is not None
        assert r["infra_refs"] and all(lib.is_infra_ref(x) for x in r["infra_refs"])
        assert not engine.MONEY_RE.search(r["title"] + r["body"])


def test_usd_and_kind_come_from_findings_not_glm(seeded):
    _run(seeded, FakeGLM())
    by_practice = {(r["target_id"], r["practice_id"]): r for r in _recs(seeded)}
    cache = by_practice[("k8s-upgrade", "cache-friendly-prompt-layout")]
    assert (cache["usd"], cache["kind"]) == (pytest.approx(0.00588), "measured")
    rds = {r["form"]: r for r in db.rows(seeded, "SELECT * FROM recurring_discoveries WHERE initiative_id=?", (SCR,))}
    doc = by_practice[(SCR, "consolidated-initiative-doc")]
    mem = by_practice[(SCR, "initiative-memory-file")]
    assert doc["recurring_discovery_id"] == rds["common_path"]["recurring_discovery_id"]
    assert mem["recurring_discovery_id"] == rds["repeated_discovery"]["recurring_discovery_id"]
    assert doc["usd"] == pytest.approx(rds["common_path"]["spend_usd"]) and doc["kind"] == "estimated"
    overkill = by_practice[("incident-postmortems", "tier-routing-by-complexity")]
    assert overkill["kind"] == "estimated"


def test_glm_never_sees_dollar_figures(seeded):
    fake = FakeGLM()
    _run(seeded, fake)
    usd_values = [f"{r['usd']:.5f}" for r in db.rows(seeded, "SELECT usd FROM waste_findings")]
    usd_values += [f"{r['spend_usd']:.5f}" for r in db.rows(seeded, "SELECT spend_usd FROM recurring_discoveries")]
    for messages in fake.calls:
        text = "\n".join(m["content"] for m in messages[1:])  # [0] is the rules ("never write dollar figures")
        assert not engine.MONEY_RE.search(text)
        assert not any(v in text for v in usd_values)


def test_output_with_dollar_figure_is_rejected_and_retried(seeded):
    fake = FakeGLM(first_bad="money")
    msg = _run(seeded, fake, ["--initiative", "k8s-upgrade"])
    assert "1 GLM outputs rejected" in msg and len(fake.calls) == 2
    assert "dollar figure" in fake.calls[1][-1]["content"]
    assert all("$" not in r["body"] for r in _recs(seeded, "target_id='k8s-upgrade'"))


def test_invalid_practice_or_refs_rejected_then_fallback(seeded):
    fake = FakeGLM(first_bad="always_invalid")
    msg = _run(seeded, fake, ["--initiative", "auth-migration"])
    assert len(fake.calls) == engine.MAX_ATTEMPTS
    assert "not a candidate" in fake.calls[1][-1]["content"] or "not a Group key" in fake.calls[1][-1]["content"]
    assert "not refs in the Infra Profile" in fake.calls[1][-1]["content"]
    recs = _recs(seeded, "target_id='auth-migration'")
    assert len(recs) >= 2 and "fallback" in msg
    for r in recs:
        assert r["practice_id"] in {p.id for p in lib.eligible_practices("redundant_read")}
        assert r["infra_refs"] and all(lib.is_infra_ref(x) for x in r["infra_refs"])


def test_team_policy_candidate(seeded):
    _run(seeded, FakeGLM())
    pol = _recs(seeded, "target_type='policy'")
    assert [(r["target_id"], r["practice_id"]) for r in pol] == [("Routing", "team-model-allowlist-policy")]
    assert pol[0]["suggested_models"] == ["glm-4.7", "glm-4.5-air"] and pol[0]["kind"] == "estimated"


def test_idempotent_and_keeps_attached_draft(seeded):
    _run(seeded, FakeGLM())
    first = {r["recommendation_id"] for r in _recs(seeded)}
    rid = f"r-{SCR}-consolidated-initiative-doc"
    seeded.execute("UPDATE recommendations SET draft_id='d-x', usd=1.5 WHERE recommendation_id=?", (rid,))
    _run(seeded, FakeGLM())
    assert {r["recommendation_id"] for r in _recs(seeded)} == first
    kept = _recs(seeded, "recommendation_id=?", (rid,))[0]
    assert (kept["draft_id"], kept["usd"], kept["kind"]) == ("d-x", 1.5, "estimated")
    # stale targets are removed on a full run
    seeded.execute("DELETE FROM waste_findings WHERE session_id='fx-rr-01'")
    _run(seeded, FakeGLM())
    assert not _recs(seeded, "target_id='auth-migration'")


# --- Endpoints -----------------------------------------------------------------------------
@pytest.fixture
def client(seeded):
    app.dependency_overrides[get_conn] = lambda: seeded
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_waste_endpoint_from_store(client):
    r = client.get("/api/initiatives/k8s-upgrade/waste").json()
    WasteBreakdown.model_validate(r)
    assert r["source"] == "store"
    assert {p["pattern"]: p["amount"]["kind"] for p in r["patterns"]} == {"cache_miss": "measured",
                                                                        "runaway_loop": "measured"}
    assert r["measured_total"]["usd"] == pytest.approx(0.00588 + 0.00534192, abs=1e-6)
    assert r["estimated_total"] == {"usd": 0.0, "kind": "estimated", "note": None}
    mo = client.get("/api/initiatives/incident-postmortems/waste").json()
    assert mo["patterns"][0]["pattern"] == "model_overkill" and mo["patterns"][0]["amount"]["kind"] == "estimated"
    assert client.get("/api/initiatives/unknown/waste").json()["patterns"] == []


def test_recommendation_endpoints_from_store(client, seeded):
    _run(seeded, FakeGLM())
    r = client.get(f"/api/initiatives/{SCR}/recommendations").json()
    RecommendationList.model_validate(r)
    assert r["source"] == "store" and len(r["items"]) >= 2
    for item in r["items"]:
        assert item["practice"]["title"] == lib.practice_title(item["practice"]["practice_id"])
        assert item["saving"]["kind"] in ("measured", "estimated")
    mem = next(i for i in r["items"] if i["practice"]["practice_id"] == "initiative-memory-file")
    assert mem["saving"]["note"] == "conservative upper bound"
    pol = client.get("/api/recommendations?target_type=policy").json()["items"]
    assert [p["target_type"] for p in pol] == ["policy"]
    assert pol[0]["policy_prefill"]["allowed_models"] == ["glm-4.7", "glm-4.5-air"]
    assert len(client.get("/api/recommendations").json()["items"]) == len(_recs(seeded))


def test_overlap_groups_pool_fixes_for_the_same_waste(conn):
    """Fixes for one Initiative's repeated Discoveries share a group (the memory file covers them all);
    Waste-pattern fixes keep the engine's same-Waste grouping."""
    from dwight.api.routes.recommendations import overlap_group
    base = {"target_type": "initiative", "target_id": "x", "kind": "estimated", "usd": 1.0}
    assert overlap_group(base, "repeated_discovery") == overlap_group({**base, "usd": 9.0}, "repeated_discovery")
    assert overlap_group(base, "repeated_discovery") != overlap_group(base, "common_path")
    assert overlap_group(base, None) == overlap_group(dict(base), None)
    assert overlap_group(base, None) != overlap_group({**base, "usd": 2.0}, None)
    assert overlap_group(base, None) != overlap_group({**base, "target_id": "y"}, None)
