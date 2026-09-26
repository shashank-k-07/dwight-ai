"""Agent harness (ticket 03). No live model calls: dwight.glm's client is replaced by a scripted fake."""
import json
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from dwight import company, db
from dwight.harness import agent, checks, runner, stats, tasks, workspace
from dwight.harness.agent import SessionSpec, observed_signals, run_session
from dwight.harness.tools import Toolbox, protected_read
from dwight.ingest import attributes as A
from dwight.ingest.otlp import ingest_payload

MODEL = "/deployments/506a9a37/deepseek-ai/DeepSeek-V4.1-Flash"


# --- fakes -------------------------------------------------------------------

def tool_call(name, args, i=0):
    return SimpleNamespace(id=f"call_{name}_{i}", type="function",
                           function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def response(*, text="", calls=(), prompt_tokens=1000, completion_tokens=50, usage_extra=None, details=None):
    msg = SimpleNamespace(content=text, tool_calls=list(calls) or None, reasoning_content="thinking...",
                          model_extra={})
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                            prompt_tokens_details=details, model_extra=usage_extra or {})
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="tool_calls" if calls else "stop")],
                           usage=usage)


class FakeClient:
    """Scripted chat.completions.create. A script item may be a response, an exception,
    or a callable(kwargs) -> response."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item(kw) if callable(item) else item


@pytest.fixture(autouse=True)
def _isolated_harness_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "WORKSPACES_DIR", tmp_path / "ws")
    monkeypatch.setattr(workspace, "PRIVATE_DIR", tmp_path / "private")


def tiny_repo(session_id, root_dir):
    root = root_dir / session_id
    (root / "src").mkdir(parents=True)
    (root / "README.md").write_text("# tiny\nA tiny repo.\n")
    (root / "src" / "mod.py").write_text("def f():\n    return 1\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_fail.py").write_text("def test_x():\n    assert False\n")
    return workspace.Workspace(root=root.resolve(), kind="repo", env=workspace._base_env(root.resolve()))


def spec(tmp_path, **kw):
    base = dict(session_id="real-t01", prompt="Summarise README.md", system_prompt=tasks.repo_system_prompt("clean"),
                member_id="m001", team="Platform", business_function="Engineering",
                make_workspace=partial(tiny_repo, root_dir=tmp_path / "repos"), task_id="tiny-task",
                tools=tasks.REPO_TOOLS, model=MODEL)
    base.update(kw)
    return SessionSpec(**base)


def ingest(conn, result):
    ingest_payload(conn, result.payload)
    return db.rows(conn, "SELECT * FROM sessions")[0], db.rows(conn, "SELECT * FROM calls ORDER BY seq")


def chat_spans(payload):
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    out = []
    for s in spans:
        a = {kv["key"]: kv["value"] for kv in s["attributes"]}
        if a.get(A.OPERATION, {}).get("stringValue") == "chat":
            out.append(a)
    return out


# --- tools / sandbox ------------------------------------------------------------

def test_file_tools_cannot_read_blobctl_but_can_run_it():
    ws = workspace.kestrel_workspace("s-blob")
    tb = Toolbox(ws, docs=tasks.storage_docs())
    source = (workspace.KESTREL_WORKSPACE / "bin" / "blobctl").read_text()
    r = tb.execute("read_file", {"path": "bin/blobctl"})
    assert not r.ok and "permission denied" in r.text
    assert "_ENV_OK" not in (ws.root / "bin" / "blobctl").read_text()      # the workspace only holds a shim
    assert tb.execute("search", {"pattern": "ENV_OK|resolve_env"}).text == "(no matches)"
    assert not tb.execute("read_file", {"path": "../../../etc/passwd"}).ok
    for cmd in ("cat bin/blobctl", "head -50 ./bin/blobctl", "python3 bin/blobctl plan", "cat $BLOBCTL_IMPL",
                "cp bin/blobctl /tmp/x", "echo $(cat bin/blobctl)"):
        out = tb.execute("run_command", {"cmd": cmd})
        assert not out.ok and source[:200] not in out.text, cmd
    assert "E_NOENV" in tb.execute("run_command", {"cmd": "bin/blobctl status"}).text
    assert "E_BADREF" in tb.execute("run_command", {"cmd": "STORAGE_ENV=staging bin/blobctl plan --bucket "
                                                           "s3://kst-ml-snapshots --rule-id x-v1 --expire 9"}).text
    ok = tb.execute("run_command", {"cmd": "STORAGE_ENV=staging bin/blobctl status"})
    assert ok.ok and "[staging]" in ok.text
    assert tb.execute("run_command", {"cmd": "ls .blobctl"}).ok                    # state dir is readable


def test_protected_read_rules():
    assert not protected_read("STORAGE_ENV=staging bin/blobctl plan --bucket kst-a --rule-id a-v1 --expire 5")
    assert not protected_read("env STORAGE_ENV=staging ./bin/blobctl status && cat .blobctl/ledger.jsonl")
    assert not protected_read("bin/blobctl --help | head -20")
    assert protected_read("less bin/blobctl")
    assert protected_read("strings bin/blobctl")
    assert protected_read("find / -name blobctl")


def test_tool_output_is_deterministic(tmp_path):
    ws = tiny_repo("s-det", tmp_path)
    tb = Toolbox(ws, tools=tasks.REPO_TOOLS, sandbox=False)
    a = tb.execute("run_tests", {"path": "tests/test_fail.py"})
    b = tb.execute("run_tests", {"path": "tests/test_fail.py"})
    assert a.exit_code == 1 and a.text == b.text
    assert str(ws.root) not in a.text and "<duration>" in a.text


# --- telemetry ------------------------------------------------------------------

def test_session_telemetry_ingests_with_real_usage(tmp_path, conn):
    client = FakeClient([
        response(calls=[tool_call("read_file", {"path": "README.md"})], prompt_tokens=900, completion_tokens=40),
        response(calls=[tool_call("read_file", {"path": "README.md"}, 1)], prompt_tokens=1000, completion_tokens=30),
        response(text="Done: a tiny repo.", prompt_tokens=1100, completion_tokens=20),
    ])
    r = run_session(spec(tmp_path), client=client)
    assert r.calls == 3 and r.stop_reason == "final_answer" and not r.cache_read_reported
    assert {req["model"] for req in client.requests} == {MODEL}                 # one model per Session
    s, calls = ingest(conn, r)
    assert (s["member_id"], s["team"], s["business_function"], s["agent"], s["dataset"]) == (
        "m001", "Platform", "Engineering", "kestrel-devagent", "real")
    assert s["experiment"] is None and s["task_success"] is None
    assert [c["model"] for c in calls] == ["deepseek-v4.1-flash"] * 3
    assert [c["input_tokens"] for c in calls] == [900, 1000, 1100]
    assert [c["cache_read_tokens"] for c in calls] == [0, 0, 0]
    assert len({c["prompt_prefix_hash"] for c in calls}) == 1 and calls[0]["prompt_prefix_tokens"] > 0
    # cache read is not reported by the (fake) API, so the attribute is absent rather than invented
    assert all(A.CACHE_READ_TOKENS not in a for a in chat_spans(r.payload))
    tools = db.rows(conn, "SELECT * FROM tool_calls ORDER BY call_id")
    assert [(t["call_id"], t["name"]) for t in tools] == [("real-t01:0", "read_file"), ("real-t01:1", "read_file")]
    assert tools[0]["result_hash"] == tools[1]["result_hash"] and tools[0]["args_hash"] == tools[1]["args_hash"]
    staged = db.rows(conn, "SELECT seq, kind, content FROM staging_content WHERE call_id IS NOT NULL "
                           "AND kind IN ('system_instructions', 'input_messages') ORDER BY seq, kind")
    assert [(x["seq"], x["kind"]) for x in staged] == [(0, "input_messages"), (0, "system_instructions"),
                                                       (1, "input_messages"), (2, "input_messages")]
    assert [m["role"] for m in json.loads(staged[2]["content"])] == ["tool"]    # only new messages
    assert observed_signals(r)["duplicate_tool_results"] == 1


def test_cached_tokens_recorded_when_the_api_reports_them(tmp_path, conn):
    client = FakeClient([response(calls=[tool_call("list_files", {})], details={"cached_tokens": 512}),
                         response(text="ok", usage_extra={"prompt_cache_hit_tokens": 768})])
    r = run_session(spec(tmp_path), client=client)
    _, calls = ingest(conn, r)
    assert [c["cache_read_tokens"] for c in calls] == [512, 768] and r.cache_read_reported


def test_cache_miss_variant_has_volatile_header_but_stable_prefix_hash(tmp_path, conn):
    client = FakeClient([response(calls=[tool_call("list_files", {}, i)]) for i in range(2)] + [response(text="ok")])
    r = run_session(spec(tmp_path, variant="cache_miss"), client=client)
    systems = [req["messages"][0]["content"] for req in client.requests]
    assert len(set(systems)) == 3 and all(x.startswith("[kestrel-devagent session header] generated") for x in systems)
    _, calls = ingest(conn, r)
    assert len({c["prompt_prefix_hash"] for c in calls}) == 1
    staged = db.rows(conn, "SELECT seq FROM staging_content WHERE kind='system_instructions'")
    assert sorted(x["seq"] for x in staged) == [0, 1, 2]


def test_redundant_read_variant_reminds_the_agent_to_reread(tmp_path):
    client = FakeClient([response(calls=[tool_call("read_file", {"path": "README.md"})]), response(text="ok")])
    run_session(spec(tmp_path, variant="redundant_read", reread_reminder=tasks.REREAD_REMINDER), client=client)
    last = client.requests[1]["messages"][-1]
    assert last["role"] == "user" and "README.md" in last["content"]


def test_context_files_experiment_tags_and_task_success(tmp_path, conn):
    ctx = tmp_path / "storage-initiative-doc.md"
    ctx.write_text("# Draft\nAlways use bare bucket names.\n")
    client = FakeClient([response(text="done")])
    r = run_session(spec(tmp_path, experiment="after", context_files=[ctx],
                         check=lambda root: (True, ["ok"])), client=client)
    assert "Always use bare bucket names." in client.requests[0]["messages"][0]["content"]
    s, _ = ingest(conn, r)
    assert (s["experiment"], s["experiment_task_id"], s["task_success"]) == ("after", "tiny-task", 1)


def test_runaway_loop_retry_wrapper_runs_until_the_cap(tmp_path):
    run = response(calls=[tool_call("run_tests", {"path": "tests/test_fail.py"})])
    give_up = response(text="This test fails deterministically.")
    client = FakeClient([run, run, run, give_up, run, give_up])
    r = run_session(spec(tmp_path, variant="runaway_loop", tools=("run_tests",), max_calls=8,
                         retry_prompt=tasks.RUNAWAY_RETRY), client=client)
    assert r.calls == 8 and r.stop_reason == "max_calls"
    assert client.requests[4]["messages"][-1] == {"role": "user", "content": tasks.RUNAWAY_RETRY}
    assert observed_signals(r)["max_identical_consecutive_tool_calls"] == 3


def test_api_errors_are_retried(tmp_path):
    import httpx
    from openai import APIConnectionError

    err = APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))
    client = FakeClient([err, err, response(text="ok")])
    slept = []
    r = run_session(spec(tmp_path), client=client, sleep=slept.append)
    assert r.calls == 1 and len(slept) == 2


# --- storage tasks (04/16) ------------------------------------------------------

def test_storage_checks_accept_the_reference_solution_and_reject_a_wrong_one():
    t01 = next(t for t in company.storage_tasks()["tasks"] if t["id"].startswith("t01"))
    ws = workspace.kestrel_workspace("s-check")
    tb = Toolbox(ws, docs=tasks.storage_docs())
    ref = t01["reference"].replace("bin/blobctl", "STORAGE_ENV=staging bin/blobctl")
    assert tb.execute("run_command", {"cmd": ref}).ok
    answer = {"bucket": "s3://kst-telemetry-raw-prod", "rule_id": "data-infra-telemetry-raw-prod-v1",
              "monthly_cost_before_usd": 18860.0, "monthly_cost_after_usd": 5355.0, "monthly_saving_usd": 13505.0}
    (ws.root / "out" / "t01.json").write_text(json.dumps(answer))
    assert checks.evaluate(t01["check"], ws.root) == (True, ["plan data-infra-telemetry-raw-prod-v1: ok",
                                                              "out/t01.json: ok"])
    (ws.root / "out" / "t01.json").write_text(json.dumps({**answer, "monthly_saving_usd": 14317.70}))
    ok, notes = checks.evaluate(t01["check"], ws.root)
    assert not ok and "monthly_saving_usd" in notes[1]


def test_storage_specs_share_settings_between_before_and_after(tmp_path):
    ctx = tmp_path / "draft.md"
    ctx.write_text("draft")
    before = tasks.storage_specs(experiment="before", session_prefix="real-scr-b")
    after = tasks.storage_specs(experiment="after", session_prefix="real-scr-a", context_files=[ctx])
    assert len(before) == len(after) == 10
    assert [s.task_id for s in before] == [s.task_id for s in after]
    for b, a in zip(before, after):
        assert (b.system_prompt, b.max_calls, b.tools, sorted(b.docs), b.temperature) == (
            a.system_prompt, a.max_calls, a.tools, sorted(a.docs), a.temperature)
        assert b.context_files == [] and a.context_files == [ctx] and b.tag_task_id
    assert before[0].session_id == "real-scr-b-t01" and sorted(before[0].docs) == [
        "blobctl-migration-runbook", "storage-cost-dashboard", "storage-service-ownership", "storage-tiering-policy"]


# --- plan, batch outputs, stats --------------------------------------------------

def test_real_plan_has_planted_variants_and_no_model_overkill():
    plan = tasks.real_specs()
    assert 30 <= len(plan) <= 50 and len({s.session_id for s in plan}) == len(plan)
    by = {v: sum(1 for s in plan if s.variant == v) for v in agent.VARIANTS}
    assert by["clean"] >= 10 and all(by[v] >= 5 for v in ("redundant_read", "cache_miss", "runaway_loop"))
    assert "model_overkill" not in {s.variant for s in plan}
    assert {s.business_function for s in plan} == {"Engineering"}
    assert all(s.model is None for s in plan)            # model chosen by glm.model_for() at run time
    assert all(s.tools == ("run_tests",) and s.retry_prompt for s in plan if s.variant == "runaway_loop")


def test_run_batch_writes_otlp_labels_manifest_and_stats(tmp_path, monkeypatch):
    first = response(calls=[tool_call("read_file", {"path": "README.md"})])
    client = FakeClient([lambda kw: first if kw["messages"][-1]["role"] == "user" else response(text="ok")])
    specs = [spec(tmp_path, session_id="real-t01"),
             spec(tmp_path, session_id="real-t02", variant="cache_miss")]
    out, runs, labels = tmp_path / "otlp", tmp_path / "runs.json", tmp_path / "labels.yaml"
    results, failed = runner.run_batch(specs, workers=1, out_dir=out, client=client, runs_path=runs,
                                       labels_path=labels, log=lambda *_: None)
    assert failed == [] and sorted(p.name for p in out.iterdir()) == ["real-t01.json", "real-t02.json"]
    lab = yaml.safe_load(labels.read_text())["sessions"]
    assert (lab["real-t01"]["planted_pattern"], lab["real-t02"]["planted_pattern"]) == ("none", "cache_miss")
    assert json.loads(runs.read_text())["sessions"]["real-t01"]["settings"]["model"] == MODEL
    st = stats.compute(otlp_dir=out, labels_path=labels)
    assert st["all"]["sessions"] == 2 and st["models"] == {"deepseek-v4.1-flash": 4}
    assert st["pattern_rates"]["cache_miss"]["sessions"] == 1 and st["cache"]["calls_with_cache_read"] == 0
