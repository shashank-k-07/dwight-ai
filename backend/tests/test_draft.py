"""Ticket 12: Drafter stage, Draft endpoints and the draft_check acceptance check. GLM is mocked."""
import re
import threading

import pytest
import yaml
from fastapi.testclient import TestClient

from dwight import config, db, glm, pricing
from dwight.api.contract import Draft, DraftList
from dwight.api.main import app
from dwight.api.serving import get_conn
from dwight.pipeline.stages import _drafter as d
from dwight.pipeline.stages import draft, draft_check, seed_fixtures

SCR = "storage-cost-reduction"
DOC_ID, MEM_ID = f"d-{SCR}-doc", f"d-{SCR}-memory"
SECRET = "RAW-PROMPT-SENTINEL-8472"


class FakeChat:
    """Stands in for glm.chat: one short section per call, naming the doc it was given."""

    def __init__(self, replies=None):
        self.calls, self.replies, self.lock = [], list(replies or []), threading.Lock()

    def __call__(self, messages, tier=None, temperature=0.2, max_tokens=None, **kw):
        with self.lock:
            self.calls.append(messages)
            if self.replies:
                r = self.replies.pop(0)
                if isinstance(r, Exception):
                    raise r
                return r
        user = messages[1]["content"]
        rid = user.split("Source doc `", 1)[1].split("`", 1)[0]
        return f"### Needed values (§1)\n- Exact values from {rid}: `STANDARD_IA`, 128 KB."


class FakeChatJSON:
    def __init__(self, line_for=None, fail=False):
        self.calls, self.line_for, self.fail = [], line_for, fail

    def __call__(self, messages, schema=None, tier=None, **kw):
        self.calls.append(messages)
        if self.fail:
            raise glm.GLMBadOutput("nope")
        facts = [l.split(". ", 1) for l in messages[1]["content"].split("\n") if l[:1].isdigit()]
        return schema.model_validate({"lines": [
            {"id": int(i), "line": self.line_for(s) if self.line_for else f"Always remember: {s}"} for i, s in facts]})


@pytest.fixture
def seeded(conn, tmp_path, monkeypatch):
    seed_fixtures.run(conn, [])
    # raw content for a storage Session: the Drafter must never read it
    conn.execute("INSERT INTO staging_content (session_id, seq, kind, content) VALUES ('fx-scr-b01', 0, "
                 "'input_messages', ?)", (SECRET,))
    conn.commit()
    monkeypatch.setattr(glm, "chat", FakeChat())
    monkeypatch.setattr(glm, "chat_json", FakeChatJSON())
    return conn


def _run(conn, tmp_path, *extra):
    return draft.run(conn, ["--out-dir", str(tmp_path / "drafts"), *extra])


def _drafts(conn):
    return {r["draft_id"]: r for r in db.rows(conn, "SELECT * FROM drafts")}


def _rec(conn, rid):
    return db.rows(conn, "SELECT * FROM recommendations WHERE recommendation_id=?", (rid,))[0]


# ---------------------------------------------------------------- pure parts

def test_token_counter_is_chars_over_four():
    assert d.count_tokens("") == 0
    assert d.count_tokens("abcdefgh") == 2
    assert d.count_tokens("abcdefghi") == 2


def test_fetches_company_docs_fresh_and_skips_everything_else():
    docs, skipped = d.fetch_source_docs(["company-docs/storage-tiering-policy.md", "auth/session.py",
                                         "perch:ENG/x", "company-docs/../backend/dwight/glm.py",
                                         "company-docs/missing.md"])
    assert [x.resource_id for x in docs] == ["company-docs/storage-tiering-policy.md"]
    assert docs[0].title == "Storage Tiering & Retention Policy"
    assert docs[0].text == (config.COMPANY_DOCS_DIR / "storage-tiering-policy.md").read_text()
    assert len(skipped) == 4


def test_section_budgets_split_by_size_under_target():
    docs = [d.SourceDoc("a", "A", "x" * 4000), d.SourceDoc("b", "B", "x" * 12000)]
    budgets = d.section_budgets(docs, target_tokens=1000, fixed_tokens=100)
    assert sum(budgets) <= 1000 * d.AIM - 100
    assert budgets[1] == pytest.approx(3 * budgets[0], abs=1)


def test_clean_section_and_truncation():
    assert d.clean_section("```markdown\n## Title\nSource: x\n\n### A (§1)\n- b\n```") == "### A (§1)\n- b"
    assert d.looks_truncated("| a | b |\n| 1 | 2")
    assert d.looks_truncated("```\nblobctl plan")
    assert not d.looks_truncated("| a | b |\n| 1 | 2 |")
    assert d.drop_dangling("| a | b |\n| 1 | 2") == "| a | b |"


def test_memory_lines_keep_literals_or_fall_back(monkeypatch):
    stmts = ["blobctl plan needs STORAGE_ENV=staging.", "Pass --approver on apply."]
    monkeypatch.setattr(glm, "chat_json", FakeChatJSON(
        line_for=lambda s: "Set STORAGE_ENV=staging before blobctl." if "STORAGE" in s else "Remember approvals."))
    lines = d.memory_lines(stmts)
    assert lines == ["Set STORAGE_ENV=staging before blobctl.", "Pass --approver on apply."]  # 2nd dropped --approver
    monkeypatch.setattr(glm, "chat_json", FakeChatJSON(fail=True))
    log = []
    assert d.memory_lines(stmts, log=log) == stmts and log
    assert d.memory_lines(["  - multi\nline  "], use_glm=False) == ["multi line"]


def test_pricing_formulas():
    assert draft.doc_saving_usd(19700, 4000, 7, 1e-6) == pytest.approx(15700 * 7 * 1e-6)
    assert draft.doc_saving_usd(1000, 4000, 7, 1e-6) == 0.0
    assert draft.memory_saving_usd(0.3, 2.0) == pytest.approx(0.15)


def test_months_observed_never_extrapolates_up(conn):
    for sid, start, end in [("s1", "2026-09-01T00:00:00Z", "2026-09-01T01:00:00Z"),
                            ("s2", "2026-10-30T00:00:00Z", "2026-10-31T00:00:00Z")]:
        conn.execute("INSERT INTO sessions (session_id, member_id, team, business_function, agent, started_at, "
                     "ended_at, ingested_at) VALUES (?, 'm', 't', 'bf', 'a', ?, ?, 'x')", (sid, start, end))
    assert draft.months_observed(conn, ["s1"]) == 1.0
    assert draft.months_observed(conn, ["s1", "s2"]) == pytest.approx(60 / 30)


# ---------------------------------------------------------------- stage

def test_stage_writes_both_drafts_and_attaches_them(seeded, tmp_path):
    msg = _run(seeded, tmp_path)
    assert "initiative doc" in msg and "memory file with 1 lines" in msg
    ds = _drafts(seeded)
    assert set(ds) == {DOC_ID, MEM_ID}   # the fixture Drafts were replaced
    doc, mem = ds[DOC_ID], ds[MEM_ID]
    Draft.model_validate({**doc, "source": "store"})

    rd = db.rows(seeded, "SELECT * FROM recurring_discoveries WHERE form='common_path'")[0]
    assert doc["type"] == "initiative_doc" and doc["filename"] == f"{SCR}.md"
    assert sorted(doc["source_resource_ids"]) == sorted(rd["resource_ids"])
    assert doc["tokens"] == d.count_tokens(doc["content"]) and doc["source_tokens"] == rd["tokens"] == 19700
    assert doc["tokens"] <= 0.25 * 19700
    for rid in rd["resource_ids"]:  # a section per source doc, each with its source link
        assert f"Source: [{rid}]({rid})" in doc["content"]

    # attached to the Recommendations citing the matching Practices, priced Estimated by the formula
    rec_doc, rec_mem = _rec(seeded, doc["recommendation_id"]), _rec(seeded, mem["recommendation_id"])
    assert (rec_doc["practice_id"], rec_doc["draft_id"], rec_doc["kind"]) == ("consolidated-initiative-doc", DOC_ID, "estimated")
    assert (rec_mem["practice_id"], rec_mem["draft_id"], rec_mem["kind"]) == ("initiative-memory-file", MEM_ID, "estimated")
    readers = rd["evidence"]
    rate = draft.input_rate(seeded, readers)
    assert rate > 0
    months = draft.months_observed(seeded, draft.analysed_session_ids(seeded, SCR))
    assert rec_doc["usd"] == pytest.approx((19700 - doc["tokens"]) * rd["session_count"] / months * rate, rel=1e-6)
    rep = db.rows(seeded, "SELECT * FROM recurring_discoveries WHERE form='repeated_discovery'")[0]
    assert rec_mem["usd"] == pytest.approx(rep["spend_usd"] / months, rel=1e-6)

    # memory file: one instruction-style line per repeated Discovery
    bullets = [l for l in mem["content"].splitlines() if l.startswith("- ")]
    assert len(bullets) == 1 and "STORAGE_ENV=staging" in bullets[0]
    assert mem["source_resource_ids"] == [] and mem["filename"] == f"{SCR}.memory.md"

    # files on disk, loadable by the harness
    files = draft.draft_files(SCR, tmp_path / "drafts")
    assert files["initiative_doc"].read_text() == doc["content"]
    assert files["memory"].read_text() == mem["content"]


def test_model_gets_docs_summaries_discoveries_and_no_raw_prompts(seeded, tmp_path):
    _run(seeded, tmp_path)
    prompts = [m["content"] for call in glm.chat.calls for m in call]
    first = [c[1]["content"] for c in glm.chat.calls if len(c) == 2]
    assert len(first) == 4
    tiering = (config.COMPANY_DOCS_DIR / "storage-tiering-policy.md").read_text()
    assert any(tiering in p for p in first)
    assert all("Prepared a Tidewater lifecycle rule for one bucket." in p for p in first)
    assert all("STORAGE_ENV=staging" in p for p in first)          # Discoveries
    everything = "\n".join(prompts + [m["content"] for c in glm.chat_json.calls for m in c])
    assert SECRET not in everything
    outside_docs = [re.sub(r"<<<DOC\n.*?\nDOC>>>", "", p, flags=re.S) for p in first]
    assert all("$" not in p for p in outside_docs)   # no dollar figure handed to the model beyond the docs


def test_stage_is_idempotent(seeded, tmp_path):
    _run(seeded, tmp_path)
    before = (_drafts(seeded), db.rows(seeded, "SELECT * FROM recommendations ORDER BY recommendation_id"))
    _run(seeded, tmp_path)
    after = (_drafts(seeded), db.rows(seeded, "SELECT * FROM recommendations ORDER BY recommendation_id"))
    assert before == after
    assert seeded.execute("SELECT COUNT(*) FROM recommendations WHERE draft_id IS NOT NULL").fetchone()[0] == 2


def test_over_budget_section_is_revised(seeded, tmp_path, monkeypatch):
    long = "### Everything (§1)\n" + "- padding line with words\n" * 2000
    fake = FakeChat(replies=[long])
    monkeypatch.setattr(glm, "chat", fake)
    _run(seeded, tmp_path, "--workers", "1")
    revised = [c for c in fake.calls if any("hard limit" in m["content"] and m["role"] == "user" for m in c[2:])]
    assert revised
    doc = _drafts(seeded)[DOC_ID]
    assert doc["tokens"] <= 0.25 * 19700 and "padding line" not in doc["content"]


def test_truncated_section_is_rewritten(seeded, tmp_path, monkeypatch):
    fake = FakeChat(replies=["### Table (§1)\n| a | b |\n|---|---|\n| 1 | 2"])
    monkeypatch.setattr(glm, "chat", fake)
    _run(seeded, tmp_path, "--workers", "1")
    assert any("cut off" in m["content"] for c in fake.calls for m in c if m["role"] == "user")
    assert "| 1 | 2\n" not in _drafts(seeded)[DOC_ID]["content"]


def test_model_failure_keeps_previous_draft(seeded, tmp_path, monkeypatch):
    _run(seeded, tmp_path)
    old = _drafts(seeded)[DOC_ID]
    monkeypatch.setattr(glm, "chat", FakeChat(replies=[RuntimeError("provider down")] * 20))
    msg = _run(seeded, tmp_path, "--workers", "1")
    assert "kept the previous Draft" in msg
    assert _drafts(seeded)[DOC_ID] == old
    assert _rec(seeded, old["recommendation_id"])["draft_id"] == DOC_ID


def test_no_glm_writes_memory_only(seeded, tmp_path):
    msg = _run(seeded, tmp_path, "--no-glm")
    assert "skipped (--no-glm)" in msg and not glm.chat.calls and not glm.chat_json.calls
    ds = _drafts(seeded)
    assert MEM_ID in ds and DOC_ID not in ds
    assert "d-scr-doc" in ds   # the existing initiative doc is left alone


def test_draft_without_recommendation_is_still_stored(seeded, tmp_path):
    seeded.execute("DELETE FROM recommendations")
    _run(seeded, tmp_path)
    assert {r["recommendation_id"] for r in _drafts(seeded).values()} == {None}


def test_non_doc_common_path_gets_no_doc(seeded, tmp_path):
    seeded.execute("UPDATE recurring_discoveries SET resource_ids_json='[\"repo:kestrel/x.go\"]' "
                   "WHERE form='common_path'")
    msg = _run(seeded, tmp_path)
    assert "no initiative doc" in msg
    assert {r["type"] for r in _drafts(seeded).values()} == {"memory"}


def test_input_rate_is_uncached_rate_weighted_by_input_tokens(seeded):
    rows = db.rows(seeded, "SELECT model, input_tokens FROM calls WHERE session_id='fx-scr-b01'")
    tok = sum(r["input_tokens"] for r in rows)
    want = sum(r["input_tokens"] * pricing.input_rate(r["model"], cached=False) for r in rows) / tok
    assert draft.input_rate(seeded, ["fx-scr-b01"]) == pytest.approx(want)


# ---------------------------------------------------------------- API

@pytest.fixture
def client_for():
    def make(conn):
        app.dependency_overrides[get_conn] = lambda: conn
        return TestClient(app)
    yield make
    app.dependency_overrides.pop(get_conn, None)


def test_endpoints_serve_store(seeded, tmp_path, client_for):
    _run(seeded, tmp_path)
    c = client_for(seeded)
    lst = DraftList.model_validate(c.get(f"/api/initiatives/{SCR}/drafts").json())
    assert lst.source == "store" and [x.draft_id for x in lst.items] == [DOC_ID, MEM_ID]
    one = c.get(f"/api/drafts/{DOC_ID}").json()
    assert one["source"] == "store" and one["tokens"] == _drafts(seeded)[DOC_ID]["tokens"]
    dl = c.get(f"/api/drafts/{MEM_ID}/download")
    assert dl.headers["content-disposition"] == f'attachment; filename="{SCR}.memory.md"'
    assert dl.text == _drafts(seeded)[MEM_ID]["content"]
    assert c.get("/api/drafts/d-nope").status_code == 404
    assert c.get("/api/initiatives/k8s-upgrade/drafts").json()["items"] == []


def test_endpoints_fall_back_to_fixtures_before_the_stage_runs(conn, client_for):
    c = client_for(conn)
    body = c.get(f"/api/initiatives/{SCR}/drafts").json()
    assert body["source"] == "fixture" and body["items"]
    assert c.get("/api/drafts/d-scr-doc").json()["source"] == "fixture"


# ---------------------------------------------------------------- draft_check (acceptance, reads ground truth)

def _must_keep():
    return yaml.safe_load(draft_check.PLANTED_FACTS.read_text())["draft_must_keep"]


def test_every_must_keep_fact_sits_in_its_source_doc():
    for doc, facts in _must_keep().items():
        text = (config.COMPANY_DOCS_DIR / f"{doc}.md").read_text()
        assert [f for f in facts if f not in text] == [], doc


def test_draft_check_passes_and_fails(seeded, tmp_path):
    _run(seeded, tmp_path)
    facts = [f for fs in _must_keep().values() for f in fs]
    good = "# doc\n" + " ".join(facts)
    seeded.execute("UPDATE drafts SET content=?, tokens=? WHERE draft_id=?", (good, d.count_tokens(good), DOC_ID))
    msg = draft_check.run(seeded, [])
    assert f"kept {len(facts)}/{len(facts)}" in msg and "pf1-storage-env-staging=yes" in msg
    seeded.execute("UPDATE drafts SET content=? WHERE draft_id=?", (good.replace("@priya.raman", ""), DOC_ID))
    with pytest.raises(draft_check.DraftCheckFailed, match="priya"):
        draft_check.run(seeded, [])
    seeded.execute("UPDATE drafts SET content=?, tokens=? WHERE draft_id=?", (good, 6000, DOC_ID))
    with pytest.raises(draft_check.DraftCheckFailed):
        draft_check.run(seeded, [])
    assert draft_check.missing_facts("STANDARD_IA", {"x": ["STANDARD_IA", "730"]}) == {"x": ["730"]}
