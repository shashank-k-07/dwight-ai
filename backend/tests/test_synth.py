"""Synthetic company dataset (ticket 07). No live model calls: content.build gets
a fake glm module, and generation uses a tiny in-test content library."""
from __future__ import annotations

import json
import threading
import time
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from dwight import company, db, pricing
from dwight.ingest.otlp import ingest_file
from dwight.pipeline.stages.detect import find_waste, load_calls
from dwight.synth import content, generate
from dwight.synth import params as P

ORG = company.org()
PARAMS = P.load(calibration=None)


def _step(tool: str, i: int, text: str) -> dict:
    return {"tool": tool, "args": {"cmd": f"{tool} {i}"}, "result": f"{text} #{i}"}


def tiny_library() -> dict:
    """A library with the same shape content.build produces, written by hand."""
    inis = {}
    for ini in ORG["initiatives"]:
        agent = content.agent_for(ini, ORG, PARAMS)
        tools = PARAMS["agents"]["work_tools"][agent]
        name = ini["name"]
        inis[ini["id"]] = {
            "tasks": [{"prompt": f"{c} task {k} for {name}", "complexity": c, "ambiguous": k == 1,
                       "plan": f"I'll start on {name}.", "summary": f"Done with {name} ({c})."}
                      for c in ("low", "med", "high") for k in range(2)],
            "resources": {r["id"]: f"# {r['id']}\nexcerpt" for r in ini["usual_resources"]},
            "extra": [{"resource_id": f"perch:ENG/{ini['id']}-extra-{k}", "excerpt": f"extra {k}"} for k in range(4)],
            "work_steps": [_step(tools[k % len(tools)], k, f"ok {ini['id']}") for k in range(12)],
            "failing_steps": [{"tool": tools[0], "args": {"cmd": "pytest -x"}, "result": "FAILED test_x - AssertionError"}],
            "discoveries": [{"statement": d["statement"],
                             "failed_step": {"tool": tools[0], "args": {"cmd": f"try {j}"}, "result": f"error {j}"},
                             "fixed_step": {"tool": tools[0], "args": {"cmd": f"try {j} --fixed"}, "result": f"ok {j}"},
                             "note": f"Learned: {d['statement']}"}
                            for j, d in enumerate(ini["repeated_discoveries"])],
            "one_offs": [{"statement": "one-off fact", "failed_step": {"tool": tools[0], "args": {"cmd": "a"}, "result": "e"},
                          "fixed_step": {"tool": tools[0], "args": {"cmd": "b"}, "result": "fine"}, "note": "Noted."}],
        }
    return {"version": 1, "initiatives": inis, "jobs": {}}


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    d = tmp_path_factory.mktemp("synth")
    summary = generate.generate(PARAMS, tiny_library(), org=ORG, sessions=400, seed=11, out_dir=d / "otlp",
                                ground_truth=d / "gt.jsonl", summary_path=d / "summary.json")
    gts = [json.loads(line) for line in (d / "gt.jsonl").read_text().splitlines()]
    conn = db.connect(d / "store.sqlite")
    for f in sorted((d / "otlp").glob("*.jsonl")):
        ingest_file(conn, f)
    yield {"dir": d, "summary": summary, "gt": gts, "conn": conn}
    conn.close()


# --- content library: bounded, concurrent, cached, no live calls ---------------------------
class FakeGLM:
    def __init__(self):
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def chat_json(self, messages, *, schema=None, **kw):
        with self.lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.01)
        with self.lock:
            self.active -= 1
        step = content.ToolStep(tool="write_file", args={"path": "out.md"}, result="ok")
        if schema is content.TaskBatch:
            return schema(tasks=[content.Task(prompt=f"p{c}", complexity=c, ambiguous=False, plan="p", summary="s")
                                 for c in ("low", "med", "high")])
        if schema is content.ResourceBatch:
            return schema(usual=[], extra=[content.ResourceText(resource_id="perch:ENG/x", excerpt="x")])
        script = content.DiscoveryScript(statement="s", failed_step=step, fixed_step=step, note="n")
        return schema(work_steps=[step] * 5, failing_steps=[step], discoveries=[script] * 3, one_offs=[script])


def test_content_build_is_bounded_concurrent_and_cached(tmp_path):
    fake = FakeGLM()
    path = tmp_path / "lib.json"
    lib = content.build(PARAMS, org=ORG, path=path, glm_mod=fake, log=lambda m: None)
    n_jobs = len(ORG["initiatives"]) * (PARAMS["content"]["task_batches"] + 2)
    assert fake.calls == n_jobs                       # one call per job, not per Session
    assert fake.max_active <= PARAMS["content"]["max_concurrency"] <= 4
    assert set(lib["initiatives"]) == {i["id"] for i in ORG["initiatives"]}
    scr = lib["initiatives"]["storage-cost-reduction"]
    assert set(scr["resources"]) == {r["id"] for r in ORG["initiatives"][0]["usual_resources"]}
    assert "STORAGE_ENV=staging" in scr["discoveries"][0]["fixed_step"]["args"]["cmd"]  # hand-written, real blobctl
    auth = lib["initiatives"]["auth-migration"]
    assert [d["statement"] for d in auth["discoveries"]] == [
        d["statement"] for d in ORG["initiatives"][1]["repeated_discoveries"]]
    content.build(PARAMS, org=ORG, path=path, glm_mod=fake, log=lambda m: None)
    assert fake.calls == n_jobs                       # cached: second build makes no calls


def test_content_build_retries_a_failing_job(tmp_path):
    fake = FakeGLM()
    real = fake.chat_json
    failed = {"n": 0}

    def flaky(messages, **kw):
        if kw.get("schema") is content.StepBatch and failed["n"] == 0:
            failed["n"] += 1
            raise RuntimeError("API hiccup")
        return real(messages, **kw)

    fake.chat_json = flaky
    params = {**PARAMS, "content": {**PARAMS["content"], "retries": 2}}
    lib = content.build(params, org=ORG, path=tmp_path / "lib.json", glm_mod=fake, log=lambda m: None)
    assert len(lib["jobs"]) == len(ORG["initiatives"]) * 4


# --- generation ---------------------------------------------------------------------------
def test_org_shape_and_engineering_share(dataset):
    gts, s = dataset["gt"], dataset["summary"]
    assert s["sessions"] == len(gts) == 400
    bf = Counter(g["business_function"] for g in gts)
    assert 0.62 <= bf["Engineering"] / len(gts) <= 0.80
    assert set(bf) == {b["name"] for b in ORG["business_functions"]}
    assert len({g["team"] for g in gts}) == 12
    assert len({g["initiative_id"] for g in gts}) == 15
    assert s["members"] > 120                                   # 400 Sessions; the full 4K reach ~all 200


def test_ingested_through_otlp_as_synthetic(dataset):
    conn = dataset["conn"]
    rows = db.rows(conn, "SELECT session_id, dataset, team, business_function, member_id, agent, spend_usd, "
                         "initiative_id FROM sessions")
    assert len(rows) == 400
    assert {r["dataset"] for r in rows} == {"synthetic"}
    assert all(r["initiative_id"] is None for r in rows)          # the true Initiative is NOT in telemetry
    gt = {g["session_id"]: g for g in dataset["gt"]}
    for r in rows:
        g = gt[r["session_id"]]
        assert (r["team"], r["business_function"], r["member_id"], r["agent"]) == (
            g["team"], g["business_function"], g["member_id"], g["agent"])
        assert r["spend_usd"] == pytest.approx(g["spend_usd"], abs=1e-6)
    models = {m for (m,) in conn.execute("SELECT DISTINCT model FROM calls")}
    assert models <= {"glm-5.1", "glm-4.7", "glm-4.5-air"}
    assert conn.execute("SELECT COUNT(DISTINCT model) FROM calls GROUP BY session_id ORDER BY 1 DESC").fetchone()[0] == 1
    staged = conn.execute("SELECT content FROM staging_content WHERE kind='input_messages' LIMIT 1").fetchone()[0]
    assert "task" in staged                                        # prompt content is there for the classifier


def test_ground_truth_is_separate_from_telemetry(dataset):
    otlp_text = "".join(f.read_text() for f in (dataset["dir"] / "otlp").glob("*.jsonl"))
    assert "initiative_id" not in otlp_text and "waste_patterns" not in otlp_text
    assert str(P.GROUND_TRUTH_PATH).startswith(str(P.config.GROUND_TRUTH_DIR))


def test_same_seed_same_bytes(tmp_path):
    outs = []
    for k in range(2):
        d = tmp_path / str(k)
        generate.generate(PARAMS, tiny_library(), org=ORG, sessions=60, seed=3, out_dir=d,
                          ground_truth=d / "gt.jsonl", summary_path=None)
        outs.append([f.read_bytes() for f in sorted(d.glob("*.jsonl"))])
    assert outs[0] == outs[1]


def test_usual_docs_and_repeated_discoveries_planted(dataset):
    gts = dataset["gt"]
    scr = [g for g in gts if g["initiative_id"] == "storage-cost-reduction"]
    reads = Counter(r for g in scr for r in g["usual_resources_read"])
    assert all(reads[r["id"]] / len(scr) >= 0.5 for r in ORG["initiatives"][0]["usual_resources"])
    env = sum(1 for g in scr for d in g["discoveries"] if d["statement"].startswith("blobctl needs STORAGE_ENV"))
    assert 0.15 <= env / len(scr) <= 0.6                          # org.yaml strength 0.35


def test_trail_ids_match_org_resource_ids(dataset):
    from dwight.classifier.trail import build_trail
    conn = dataset["conn"]
    g = next(g for g in dataset["gt"] if len(g["usual_resources_read"]) >= 2)
    trail = {e.resource_id for e in build_trail(conn, g["session_id"])}
    assert set(g["usual_resources_read"]) <= trail


def test_detectors_find_planted_patterns_and_clean_sessions_are_clean(dataset):
    conn, gts = dataset["conn"], dataset["gt"]
    seen = Counter()
    for g in gts:
        found = {f.pattern for f in find_waste(load_calls(conn, g["session_id"]), g["complexity"])}
        planted = set(g["waste_patterns"])
        measured = planted - {"model_overkill"}
        assert measured <= found, (g["session_id"], planted, found)
        assert found - {"model_overkill"} <= measured, (g["session_id"], planted, found)  # no false positives
        assert ("model_overkill" in found) == ("model_overkill" in planted)
        seen.update(planted)
    for p in ("redundant_read", "cache_miss", "runaway_loop", "model_overkill"):
        assert seen[p] > 0, p
    mo = [g for g in gts if "model_overkill" in g["waste_patterns"]]
    assert all(g["model"] == "glm-5.1" and g["complexity"] == "low" for g in mo)
    assert len(mo) / len(gts) >= 0.05                                   # a meaningful rate


def test_calibrate_overlays_real_layer_shapes(tmp_path):
    from dwight.ingest.builder import SessionBuilder
    from dwight.synth.calibrate import calibrate

    real = tmp_path / "real"
    real.mkdir()
    for k in range(6):
        b = SessionBuilder(f"r{k}", member_id="m1", team="Platform", business_function="Engineering")
        for i in range(4 + k):
            c = b.call(model="glm-4.7", input_tokens=1000 + i, output_tokens=100 + 10 * i, prefix_tokens=4000,
                       prefix_hash="h")
            b.tool(c, "run_command", {"cmd": f"step {i}"}, "x" * 400, result_tokens=100 + i)
        b.call(model="glm-4.7", input_tokens=2000, output_tokens=300)
        (real / f"r{k}.json").write_text(json.dumps(b.otlp()))
    out = tmp_path / "calibration.yaml"
    doc = calibrate([real], out=out)
    assert doc["stats"]["sessions"] == 6
    merged = P.load(calibration=out)
    assert doc["stats"]["prefix_tokens_median"] == 4000
    assert merged["agents"] == PARAMS["agents"]                    # harness prefix != kestrel-devagent's
    assert merged["shapes"]["med"]["work_steps"] == [5, 9]         # real work steps p25..p95 (4..9 per Session)
    lo, hi = merged["shapes"]["output_tokens"]["tool_call"]
    assert (lo + hi) / 2 == doc["stats"]["output_tokens_tool_call"]["p50"]
    assert merged["shapes"]["high"] == PARAMS["shapes"]["high"]
    assert merged["waste_rates"] == PARAMS["waste_rates"]          # rates untouched without --rates-from


def test_overview_spend_by_business_function_stacked_by_team(dataset):
    from dwight.api.main import app

    conn = db.connect()  # the API's store (conftest's DWIGHT_DB)
    for t in ("tool_calls", "calls", "staging_content", "waste_findings", "sessions"):
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
    for f in sorted((dataset["dir"] / "otlp").glob("*.jsonl")):
        ingest_file(conn, f)
    conn.close()
    r = TestClient(app).get("/api/overview").json()
    assert r["source"] == "store" and r["session_count"] == 400
    rows = r["spend_by_business_function"]
    assert rows[0]["business_function"] == "Engineering"
    assert len(rows) == 5 and sum(len(b["teams"]) for b in rows) == 12
    for b in rows:
        assert b["spend"]["kind"] == "measured"
        assert sum(t["spend"]["usd"] for t in b["teams"]) == pytest.approx(b["spend"]["usd"], abs=1e-4)
        assert all(t["spend"]["kind"] == "measured" for t in b["teams"])
    assert sum(b["spend"]["usd"] for b in rows) == pytest.approx(r["spend"]["usd"], abs=1e-3)
    assert pricing.price("glm-5.1").tier == "flagship"
