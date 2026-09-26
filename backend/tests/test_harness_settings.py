"""Storage-run settings file (ticket 04 writes it, 16 reuses it). No live model calls."""
import json

import pytest

from dwight import config
from dwight.harness import __main__ as cli
from dwight.harness import runner, settings, tasks, workspace
from dwight.harness.tools import Toolbox

MODEL = "/deployments/506a9a37/deepseek-ai/DeepSeek-V4.1-Flash"


@pytest.fixture(autouse=True)
def _isolated_harness_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "WORKSPACES_DIR", tmp_path / "ws")
    monkeypatch.setattr(workspace, "PRIVATE_DIR", tmp_path / "private")


def test_fingerprint_tools_match_what_storage_sessions_get():
    spec = tasks.storage_specs(experiment="before", session_prefix="x", task_ids=["t01"])[0]
    tb = Toolbox(spec.make_workspace("fp-check"), docs=spec.docs, tools=spec.tools)
    assert [t["function"]["name"] for t in tb.specs()] == settings.fingerprint()["tools"]


def test_settings_round_trip_and_drift_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "s.json"
    settings.write(path, model=MODEL)
    assert settings.load(path) == {"model": MODEL, "max_calls": tasks.STORAGE_MAX_CALLS, "repeat": 1,
                                   "tasks": None, "workers": runner.MAX_WORKERS}
    monkeypatch.setattr(tasks, "STORAGE_SYSTEM", tasks.STORAGE_SYSTEM + "\nnew rule")
    monkeypatch.setattr(config, "GLM_THINKING", "disabled")
    with pytest.raises(ValueError, match="system_prompt_sha, thinking"):
        settings.load(path)


def test_settings_require_a_model(tmp_path):
    with pytest.raises(ValueError):
        settings.build(model="")
    path = tmp_path / "s.json"
    settings.write(path, model=MODEL)
    s = json.loads(path.read_text())
    s["params"]["model"] = None
    path.write_text(json.dumps(s))
    with pytest.raises(ValueError, match="model"):
        settings.load(path)


def test_cli_storage_uses_the_settings_file_verbatim(tmp_path, monkeypatch):
    path = tmp_path / "s.json"
    assert cli.main(["storage-settings", "--model", MODEL, "--max-calls", "12", "--tasks", "t01,t02",
                     "--out", str(path)]) == 0
    seen = {}

    def fake_specs(**kw):
        seen["specs"] = kw
        return []

    def fake_batch(specs, **kw):
        seen["batch"] = kw
        return [], []

    monkeypatch.setattr(tasks, "storage_specs", fake_specs)
    monkeypatch.setattr(runner, "run_batch", fake_batch)
    ctx = tmp_path / "draft.md"
    ctx.write_text("draft")
    assert cli.main(["storage", "--settings", str(path), "--experiment", "after", "--prefix", "real-scr-a",
                     "--context-file", str(ctx), "--out", str(tmp_path / "otlp")]) == 0
    kw = seen["specs"]
    assert (kw["model"], kw["max_calls"], kw["repeat"], kw["task_ids"]) == (MODEL, 12, 1, ["t01", "t02"])
    assert kw["experiment"] == "after" and kw["context_files"] == [ctx]
    assert seen["batch"]["workers"] == runner.MAX_WORKERS

    with pytest.raises(SystemExit):   # --settings pins the model; passing one too is an error
        cli.main(["storage", "--settings", str(path), "--model", "other", "--experiment", "after",
                  "--prefix", "real-scr-a"])


def test_committed_settings_file_matches_the_current_harness():
    """data/real_scr_settings.json is what 04 ran with; 16 must be able to load it unchanged."""
    if not settings.DEFAULT_PATH.exists():
        pytest.skip("no committed settings file yet")
    p = settings.load(settings.DEFAULT_PATH)
    assert p["model"] == MODEL and p["tasks"] is None and p["repeat"] == 1


def test_storage_sessions_continue_a_reply_cut_off_by_max_tokens():
    """A reply that hits max_tokens with no tool call is not a final answer (the first 04 batch lost
    2/10 tasks to that). Storage specs re-prompt, and send their larger max_tokens."""
    from types import SimpleNamespace

    from dwight.harness import agent

    def resp(text, finish):
        msg = SimpleNamespace(content=text, tool_calls=None, reasoning_content="...", model_extra={})
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=10, prompt_tokens_details=None, model_extra={})
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)], usage=usage)

    script = [resp("", "length"), resp("done", "stop")]
    reqs = []

    def create(**kw):
        reqs.append(kw)
        return script.pop(0)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    spec = tasks.storage_specs(experiment="before", session_prefix="x", task_ids=["t01"], model=MODEL)[0]
    assert spec.continue_on_length and spec.max_tokens == tasks.STORAGE_MAX_TOKENS
    r = agent.run_session(spec, client=client)
    assert r.calls == 2 and r.stop_reason == "final_answer" and r.final_answer == "done"
    assert reqs[1]["messages"][-1] == {"role": "user", "content": agent.LENGTH_CONTINUE}
    assert all(q["max_tokens"] == tasks.STORAGE_MAX_TOKENS for q in reqs)
    # the real layer (03) keeps its behaviour: a cut-off reply ends the Session
    assert agent.SessionSpec.continue_on_length is False and agent.SessionSpec.max_tokens == 4096
