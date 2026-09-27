"""Classify stage (ticket 06). No live model calls: dwight.glm.chat_json is mocked."""
import builtins
import pathlib
import re

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from dwight import config, db, glm
from dwight.api.main import app
from dwight.api.serving import get_conn
from dwight.classifier import model as cmodel
from dwight.classifier.trail import is_read_tool, resource_id, shell_read
from dwight.classifier.transcript import StagedRow, render_transcript
from dwight.pipeline import discover


# --- a fake model -------------------------------------------------------------------------
class FakeModel:
    """Stands in for glm.chat_json. Picks an Initiative by keyword and reports a
    Discovery only where the transcript shows a failed attempt followed by a retry."""

    def __init__(self, fail_on: set[str] = frozenset()):
        self.calls: list[list[dict]] = []
        self.fail_on = fail_on

    def __call__(self, messages, *, schema=None, tier=None, **kw):
        self.calls.append(messages)
        user = messages[-1]["content"]
        transcript = user.split("Transcript (", 1)[1]
        for marker in self.fail_on:
            if marker in transcript:
                raise glm.GLMBadOutput("simulated bad output")
        if "Tidewater" in transcript:
            iid = "storage-cost-reduction"
        elif "auth" in transcript:
            iid = "auth-migration"
        elif "campaign" in transcript:
            iid = "peak-season-campaign"
        elif "postmortem" in transcript:
            iid = "incident-postmortems"
        else:
            iid = "k8s-upgrade"
        disc = []
        m = re.search(r"\[call (\d+)\] tool result \(\w+\): error: (\w+) is not set", transcript)
        fix = m and re.search(rf"\[call (\d+)\] assistant -> \w+ .*{m.group(2)}=(\w+)", transcript)
        if fix:
            disc.append({"statement": f"blobctl needs {m.group(2)}={fix.group(2)} set; contact ops@kestrel.example.",
                         "call_seq": int(fix.group(1))})
        body = {"summary": "Did some work for jane.doe@kestrel.example.", "initiative_id": iid,
                "complexity": "low" if "typo" in transcript else "med", "discoveries": disc}
        return schema.model_validate(body)


@pytest.fixture
def raw(conn):
    discover()["seed_fixtures"].run(conn, ["--raw-only"])
    return conn


@pytest.fixture
def fake(monkeypatch):
    f = FakeModel()
    monkeypatch.setattr(glm, "chat_json", f)
    return f


def classify(conn, *args):
    return discover()["classify"].run(conn, list(args))


# --- Trail ------------------------------------------------------------------------------------
@pytest.mark.parametrize("tool,args,expected", [
    ("read_doc", {"doc_id": "storage-tiering-policy"}, "company-docs/storage-tiering-policy.md"),
    ("read_doc", {"doc_id": "company-docs/storage-cost-dashboard.md"}, "company-docs/storage-cost-dashboard.md"),
    ("read_doc", {"doc_id": "perch:ENG/oidc-migration-plan"}, "perch:ENG/oidc-migration-plan"),
    ("get_page", {"page_id": "repo:kestrel/identity/docs/token-exchange.md"}, "repo:kestrel/identity/docs/token-exchange.md"),
    ("read_file", {"path": "./auth/../auth/session.py"}, "auth/session.py"),
    ("read_file", {"path": "/tmp/ws-123/company-docs/blobctl-migration-runbook.md"},
     "company-docs/blobctl-migration-runbook.md"),
    ("read_file", {"path": ".blobctl/ledger.jsonl"}, ".blobctl/ledger.jsonl"),
    ("Read", {"file_path": "src\\lib\\retry.py"}, "src/lib/retry.py"),
    ("fetch_url", {"url": "HTTPS://Perch.Kestrel.Internal/marketing/q3-attribution/?utm_source=x#top"},
     "https://perch.kestrel.internal/marketing/q3-attribution"),
    ("fetch_url", '{"url": "https://perch.kestrel.internal/a?b=2&a=1"}', "https://perch.kestrel.internal/a?a=1&b=2"),
])
def test_resource_ids_are_normalised(tool, args, expected):
    assert is_read_tool(tool)
    assert resource_id(tool, args) == expected


def test_only_read_type_tools_count():
    for name in ("write_file", "run_command", "search_docs", "list_files", "edit_file"):
        assert not is_read_tool(name)
    assert shell_read("run_command", {"cmd": "cat ./docs/runbook.md"}) == "docs/runbook.md"
    assert shell_read("run_command", {"cmd": "cat a.md | grep x"}) is None
    assert shell_read("write_file", {"cmd": "cat a.md"}) is None


# --- transcript --------------------------------------------------------------------------------
def test_transcript_tags_calls_and_truncates_long_results():
    rows = [
        StagedRow(0, "system_instructions", None, None, '[{"type":"text","content":"You are an agent."}]'),
        StagedRow(0, "input_messages", None, None, '[{"role":"user","parts":[{"type":"text","content":"Do X"}]}]'),
        StagedRow(0, "output_messages", None, None,
                  '[{"role":"assistant","parts":[{"type":"tool_call","id":"t1","name":"read_doc","arguments":{"doc_id":"d"}}]}]'),
        StagedRow(1, "system_instructions", None, None, '[{"type":"text","content":"You are an agent."}]'),
        StagedRow(1, "input_messages", None, None,
                  '[{"role":"tool","parts":[{"type":"tool_call_response","id":"t1","response":"' + "x" * 5000 + '"}]}]'),
    ]
    t = render_transcript(rows)
    assert t.count("system:") == 1                       # repeated system prompt shown once
    assert "[call 0] assistant -> read_doc" in t
    assert "[call 1] tool result (read_doc): xxx" in t   # results tagged with the Call that saw them
    assert len(t) < 1500


def test_transcript_fits_budget_keeping_head_and_tail():
    rows = [StagedRow(i, "output_messages", None, None,
                      '[{"role":"assistant","parts":[{"type":"text","content":"step %d %s"}]}]' % (i, "y" * 200))
            for i in range(200)]
    t = render_transcript(rows, limit=3000)
    assert len(t) <= 3000
    assert "step 0 " in t and "step 199 " in t and "lines omitted" in t


# --- model call ---------------------------------------------------------------------------------
def test_candidates_come_from_org_names_and_descriptions_only():
    cands = cmodel.candidates()
    ids = {c.initiative_id for c in cands}
    assert "storage-cost-reduction" in ids and len(cands) >= 10
    scr = next(c for c in cands if c.initiative_id == "storage-cost-reduction")
    assert scr.name == "Storage cost reduction" and scr.business_function == "Engineering"
    prompt = cmodel._user_prompt("t", cands, None)
    assert "STORAGE_ENV" not in prompt and "usual_resources" not in prompt and "company-docs/" not in prompt


def test_schema_rejects_unknown_initiative():
    schema = cmodel._schema(["a", "b"])
    schema.model_validate({"summary": "s", "initiative_id": "a", "complexity": "low", "discoveries": []})
    with pytest.raises(ValidationError):
        schema.model_validate({"summary": "s", "initiative_id": "zzz", "complexity": "low", "discoveries": []})


def test_redaction():
    out = cmodel.redact("mail bob@kestrel.example key sk-abcdefghijklmnop1234 token=hunter2 "
                        "blob 3f9a0c7e5b1d4a2f8e6c0b9a7d5e3f1a2b4c6d8e STORAGE_ENV=staging tidewater-kst-raw-prod-v2")
    assert "bob@" not in out and "sk-abc" not in out and "hunter2" not in out and "3f9a0c" not in out
    assert "STORAGE_ENV=staging" in out and "tidewater-kst-raw-prod-v2" in out


def test_classify_transcript_is_callable_directly(fake):
    c = cmodel.classify_transcript("[call 0] user: Project Tidewater task\n[call 2] tool result (run): error: X is "
                                   "not set\n[call 3] assistant -> run {\"cmd\": \"X=1 go\"}\n", max_seq=2)
    assert c.initiative_id == "storage-cost-reduction"
    assert c.discoveries[0].call_seq == 2                # clamped to the Session's last Call
    assert "[email]" in c.summary and "[email]" in c.discoveries[0].statement
    assert len(fake.calls) == 1


# --- the stage ------------------------------------------------------------------------------------
def test_stage_classifies_builds_trail_and_discards_content(raw, fake):
    n = raw.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    msg = classify(raw, "--workers", "3")
    assert f"classified {n}/{n}" in msg
    assert len(fake.calls) == n                          # one model call per Session
    # ADRs 0005/0008: no raw content survives classification
    assert raw.execute("SELECT COUNT(*) FROM staging_content").fetchone()[0] == 0

    s = db.rows(raw, "SELECT * FROM sessions WHERE session_id='fx-scr-b01'")[0]
    assert (s["initiative_id"], s["complexity"]) == ("storage-cost-reduction", "med")
    assert s["classified_at"] and "[email]" in s["summary"]
    trail = db.rows(raw, "SELECT resource_id, tokens, call_seq FROM trail_entries WHERE session_id='fx-scr-b01' "
                         "ORDER BY position")
    assert [t["resource_id"] for t in trail] == [
        "company-docs/storage-tiering-policy.md", "company-docs/storage-cost-dashboard.md",
        "company-docs/storage-service-ownership.md", "company-docs/blobctl-migration-runbook.md"]
    assert [t["call_seq"] for t in trail] == [0, 1, 2, 3] and all(t["tokens"] > 0 for t in trail)
    # write_file / run_command calls are not in the Trail
    assert not db.rows(raw, "SELECT 1 FROM trail_entries WHERE resource_id LIKE 'out/%'")

    disc = db.rows(raw, "SELECT session_id, statement, call_seq FROM discoveries ORDER BY session_id")
    assert {d["session_id"] for d in disc} == {"fx-scr-b01", "fx-scr-b02", "fx-scr-b03", "fx-scr-b04",
                                               "fx-scr-b05", "fx-scr-07"}
    assert all(d["call_seq"] == 5 and "STORAGE_ENV=staging" in d["statement"] for d in disc)

    ini = db.rows(raw, "SELECT * FROM initiatives WHERE initiative_id='storage-cost-reduction'")[0]
    expect = raw.execute("SELECT COUNT(*), SUM(spend_usd) FROM sessions "
                         "WHERE initiative_id='storage-cost-reduction'").fetchone()
    assert ini["session_count"] == expect[0] == 14
    assert ini["spend_usd"] == pytest.approx(expect[1])
    assert ini["business_function"] == "Engineering"


def test_stage_is_idempotent_and_only_runs_unclassified(raw, fake):
    classify(raw)
    first = (db.rows(raw, "SELECT * FROM trail_entries ORDER BY session_id, position"),
             db.rows(raw, "SELECT * FROM discoveries ORDER BY session_id, idx"),
             db.rows(raw, "SELECT * FROM initiatives ORDER BY initiative_id"))
    calls = len(fake.calls)
    assert "classified 0/0" in classify(raw)             # nothing staged -> no model calls
    assert len(fake.calls) == calls
    discover()["seed_fixtures"].run(raw, ["--raw-only"])  # re-ingest re-stages content -> classified again
    classify(raw)
    again = (db.rows(raw, "SELECT * FROM trail_entries ORDER BY session_id, position"),
             db.rows(raw, "SELECT * FROM discoveries ORDER BY session_id, idx"),
             db.rows(raw, "SELECT * FROM initiatives ORDER BY initiative_id"))
    assert again == first


def test_selection_flags(raw, fake):
    assert "classified 2/2" in classify(raw, "--session", "fx-rr-01", "--session", "fx-mo-01")
    assert "classified 3/3" in classify(raw, "--limit", "3")
    assert "classified 0/0" in classify(raw, "--dataset", "synthetic")
    classify(raw, "--dataset", "fixture")
    left = raw.execute("SELECT DISTINCT s.dataset FROM staging_content sc JOIN sessions s "
                       "ON s.session_id = sc.session_id").fetchall()
    assert "fixture" not in {r[0] for r in left}


def test_thinking_switch_reaches_the_model_call(raw, monkeypatch):
    """Ticket 15: classify turns reasoning off by default (thinking=False); --thinking on sends nothing extra."""
    seen = []
    model = FakeModel()

    def spy(messages, **kw):
        seen.append(kw.get("thinking", "unset"))
        return model(messages, **kw)

    monkeypatch.setattr(glm, "chat_json", spy)
    classify(raw, "--session", "fx-rr-01")
    assert seen == [False]
    classify(raw, "--session", "fx-mo-01", "--thinking", "on")
    assert seen[1] == "unset"
    assert glm._extra_body(False)["chat_template_kwargs"] == {"thinking": False, "enable_thinking": False}
    assert "chat_template_kwargs" not in glm._extra_body(None)


def test_failed_session_keeps_staging_for_retry(raw, monkeypatch):
    monkeypatch.setattr(glm, "chat_json", FakeModel(fail_on={"postmortem"}))
    monkeypatch.setattr("dwight.classifier.run.time.sleep", lambda s: None)
    msg = classify(raw, "--attempts", "2")
    assert "1 failed" in msg
    s = db.rows(raw, "SELECT classified_at, initiative_id FROM sessions WHERE session_id='fx-mo-01'")[0]
    assert s == {"classified_at": None, "initiative_id": None}
    assert {r[0] for r in raw.execute("SELECT DISTINCT session_id FROM staging_content")} == {"fx-mo-01"}
    monkeypatch.setattr(glm, "chat_json", FakeModel())
    assert "classified 1/1" in classify(raw)


def test_classifier_never_reads_ground_truth(raw, fake, monkeypatch):
    gt = str(config.GROUND_TRUTH_DIR)
    touched = []
    real_open, real_read = builtins.open, pathlib.Path.read_text

    def spy_open(file, *a, **k):
        touched.append(str(file))
        return real_open(file, *a, **k)

    def spy_read(self, *a, **k):
        touched.append(str(self))
        return real_read(self, *a, **k)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(pathlib.Path, "read_text", spy_read)
    classify(raw)
    assert any("org.yaml" in p for p in touched)
    assert not [p for p in touched if p.startswith(gt) or "ground-truth" in p or "planted" in p]
    for (text,) in raw.execute("SELECT statement FROM discoveries UNION ALL SELECT summary FROM sessions"):
        assert "ground" not in text


# --- API ------------------------------------------------------------------------------------------
@pytest.fixture
def client(raw, fake):
    classify(raw)
    raw.executemany("INSERT INTO waste_findings (finding_id, session_id, pattern, kind, usd) VALUES (?,?,?,?,?)", [
        ("w1", "fx-scr-b01", "redundant_read", "measured", 0.01),
        ("w2", "fx-scr-b02", "cache_miss", "measured", 0.002),
        ("w3", "fx-scr-b02", "redundant_read", "measured", 0.004),
        ("w4", "fx-mo-01", "model_overkill", "estimated", 0.003),
    ])
    raw.commit()
    app.dependency_overrides[get_conn] = lambda: raw
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_initiatives_endpoint_from_store(client, raw):
    r = client.get("/api/initiatives").json()
    assert r["source"] == "store"
    spends = [i["spend"]["usd"] for i in r["items"]]
    assert spends == sorted(spends, reverse=True) and all(i["session_count"] > 0 for i in r["items"])
    top = r["items"][0]
    assert top["initiative_id"] == "storage-cost-reduction" and top["name"] == "Storage cost reduction"
    assert top["spend"]["kind"] == "measured"
    assert top["measured_waste"] == {"usd": 0.016, "kind": "measured", "note": None}
    assert top["estimated_saving"] == {"usd": 0.0, "kind": "estimated", "note": None}
    assert top["top_waste_pattern"] == "redundant_read"
    pm = next(i for i in r["items"] if i["initiative_id"] == "incident-postmortems")
    assert pm["estimated_saving"]["usd"] == 0.003 and pm["top_waste_pattern"] == "model_overkill"


def test_initiative_and_sessions_endpoints_from_store(client):
    h = client.get("/api/initiatives/storage-cost-reduction").json()
    assert h["source"] == "store" and h["session_count"] == 14 and h["spend"]["kind"] == "measured"
    s = client.get("/api/initiatives/storage-cost-reduction/sessions").json()
    assert s["source"] == "store" and len(s["items"]) == 14
    b02 = next(x for x in s["items"] if x["session_id"] == "fx-scr-b02")
    assert b02["waste_patterns"] == ["cache_miss", "redundant_read"] and b02["experiment"] == "before"
    assert b02["total_tokens"] > 0 and b02["complexity"] == "med" and b02["spend"]["kind"] == "measured"
    # a known Initiative with no Sessions yet still renders; an unknown one is a 404
    empty = client.get("/api/initiatives/vendor-contract-review").json()
    assert empty["session_count"] == 0 and empty["name"] == "Vendor contract review"
    assert client.get("/api/initiatives/vendor-contract-review/sessions").json()["items"] == []
    assert client.get("/api/initiatives/no-such-thing").status_code == 404
