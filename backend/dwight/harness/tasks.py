"""Task catalogue and Session plans.

Real layer (ticket 03): engineering tasks against the pinned open-source repo
(workspace.OSS_REPO, tomli), each run as a clean Session or a planted Waste
Pattern variant:
  * redundant_read: a house rule makes the Agent re-read every file it has
    opened at the start of every turn.
  * cache_miss:     a volatile timestamp + request id at the top of the system
    prompt, regenerated on every Call (the stable instructions follow it).
  * runaway_loop:   a failing test that can't pass (planted into the workspace),
    a "CI is flaky, re-run until green" instruction, no step budget, and a
    naive retry wrapper that re-prompts whenever the Agent stops while the last
    command failed. Only the harness's safety cap (max_calls) ends it.
There is no Model Overkill variant: the real layer runs only the pool's light
models (decision in ticket 03). Model Overkill lives in the synthetic layer (07).

Storage cost reduction (tickets 04/16): the Kestrel tasks from
data/company/storage_tasks.yaml, in a fresh Kestrel workspace, with doc tools
over company-docs/ and the checks in checks.py.
"""
from __future__ import annotations

import textwrap
from functools import partial
from pathlib import Path

from dwight import company
from dwight.harness import checks, workspace
from dwight.harness.agent import SessionSpec

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

REPO_SYSTEM = textwrap.dedent("""\
    You are kestrel-devagent, Kestrel Logistics' internal coding agent. You are working in a
    checkout of `tomli`, the open-source TOML parser that Kestrel vendors in its config tooling
    (package code in src/tomli/, tests in tests/). The workspace root is your current directory.

    Use the tools to inspect files, edit files and run shell commands. Python and pytest are
    installed and PYTHONPATH already points at src/; run_tests runs the test suite (or one file).
    Write any report files the task asks for under out/.

    When the task is done, reply with a short summary of what you did, and stop calling tools.""")

CLEAN_RULES = textwrap.dedent("""\
    Work economically. File contents you have read stay in your context, so do not read the same
    file twice unless you changed it. Run the tests at most once, after your last edit.""")

REDUNDANT_READ_RULES = textwrap.dedent("""\
    House rule for this workspace: your view of files goes stale after every step. At the start of
    EVERY turn, before any other action, call read_file again on every file you have already opened
    in this session (all of them, even if you just read it), and only then continue with the task.
    Run the tests with run_tests.""")

RUNAWAY_RULES = textwrap.dedent("""\
    CI failures on the nightly runner are almost always flaky infrastructure, not real bugs. When a
    test fails, call run_tests again on the same path. Keep re-running it until it passes; flaky
    tests often need many attempts. Do not reply to the user until the test passes.""")

RUNAWAY_RETRY = "The test is still failing on CI. Run it again."

REREAD_REMINDER = ("[kestrel-devagent] Workspace file views are stale after every step. Before you continue, "
                   "call read_file again on each file you have opened: {files}")

STORAGE_SYSTEM = textwrap.dedent("""\
    You are kestrel-devagent, Kestrel Logistics' internal coding agent. The workspace root is your
    current directory; command-line tools are in bin/. Kestrel's internal storage documents are
    available through list_docs and read_doc. Use run_command to run tools, and write any files
    the task asks for (paths are relative to the workspace root).

    When the task is done, reply with a short summary of what you did, and stop calling tools.""")


def repo_system_prompt(variant: str) -> str:
    extra = {"clean": CLEAN_RULES, "cache_miss": CLEAN_RULES, "redundant_read": REDUNDANT_READ_RULES,
             "runaway_loop": RUNAWAY_RULES}[variant]
    return REPO_SYSTEM + "\n\n" + extra


# ---------------------------------------------------------------------------
# Real-layer tasks against tomli
# ---------------------------------------------------------------------------

def _tests_pass(root: Path) -> tuple[bool, list[str]]:
    import subprocess
    import sys
    env = workspace._base_env(root) | {"PYTHONPATH": str(root / "src")}
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], cwd=root,
                       env=env, capture_output=True, text=True, timeout=120)
    return p.returncode == 0, [f"pytest exit {p.returncode}"]


def _exists_and_tests(path: str, root: Path) -> tuple[bool, list[str]]:
    ok_file = (root / path).is_file() and (root / path).stat().st_size > 0
    ok_tests, notes = _tests_pass(root)
    return ok_file and ok_tests, [f"{path} {'present' if ok_file else 'missing'}"] + notes


def _grep_check(path: str, needle: str, root: Path) -> tuple[bool, list[str]]:
    p = root / path
    ok = p.is_file() and needle in p.read_text()
    ok_tests, notes = _tests_pass(root)
    return ok and ok_tests, [f"{path} contains {needle!r}: {ok}"] + notes


REPO_TASKS: dict[str, dict] = {
    "tomli-multiline-notes": {
        "prompt": "Explain how tomli parses multiline basic strings (\"\"\"...\"\"\"), including line-ending "
                  "backslashes. Write a short developer note to out/multiline-strings.md that names the "
                  "functions involved in src/tomli/_parser.py.",
        "check": partial(_exists_and_tests, "out/multiline-strings.md")},
    "tomli-docstring-inline-table": {
        "prompt": "Add a clear docstring to the function that parses inline tables in src/tomli/_parser.py "
                  "(what it accepts, what it returns, which errors it raises). Keep behaviour unchanged "
                  "and make sure the test suite still passes.",
        "check": _tests_pass},
    "tomli-test-offset-datetime": {
        "prompt": "Add a unit test to tests/test_misc.py that checks tomli parses an offset datetime with "
                  "fractional seconds (e.g. `t = 1979-05-27T00:32:00.999999-07:00`) into the right "
                  "timezone-aware datetime. Run the test suite.",
        "check": partial(_grep_check, "tests/test_misc.py", "999999")},
    "tomli-error-inventory": {
        "prompt": "Make an inventory of the TOMLDecodeError messages that src/tomli/_parser.py can raise. "
                  "Write out/errors.json as a JSON array of objects {\"message\": ..., \"function\": ...}, "
                  "one per distinct message.",
        "check": partial(_exists_and_tests, "out/errors.json")},
    "tomli-datetime-regex": {
        "prompt": "Explain the regular expressions tomli uses to recognise dates, times and datetimes "
                  "(see src/tomli/_re.py) and how the matched groups are turned into Python objects. "
                  "Write the explanation to out/datetime-regex.md.",
        "check": partial(_exists_and_tests, "out/datetime-regex.md")},
    "tomli-parse-float-guard": {
        "prompt": "Review how tomli validates the `parse_float` argument of `loads` (for example, a "
                  "parse_float that returns a dict or list). Write your findings, with the relevant code "
                  "locations, to out/parse-float-review.md.",
        "check": partial(_exists_and_tests, "out/parse-float-review.md")},
    "tomli-invalid-cases-count": {
        "prompt": "How are the invalid-TOML test cases organised under tests/data/invalid? Count the "
                  ".toml cases per top-level subdirectory and write out/invalid-cases.json as "
                  "{\"total\": N, \"by_directory\": {name: count}} (files directly in invalid/ go under "
                  "\"(root)\").",
        "check": partial(_exists_and_tests, "out/invalid-cases.json")},
    "tomli-release-notes": {
        "prompt": "Summarise the changes in the three most recent releases listed in CHANGELOG.md for "
                  "Kestrel's platform team, highlighting anything that could affect callers of "
                  "tomli.loads. Write the summary to out/release-notes.md.",
        "check": partial(_exists_and_tests, "out/release-notes.md")},
    "tomli-key-parsing": {
        "prompt": "Document how tomli parses dotted keys and detects redefinition of tables and keys "
                  "(the flags/namespace bookkeeping in src/tomli/_parser.py). Write the note to "
                  "out/dotted-keys.md.",
        "check": partial(_exists_and_tests, "out/dotted-keys.md")},
    "tomli-test-unicode-escape": {
        "prompt": "Add a unit test to tests/test_misc.py checking that an invalid unicode escape "
                  "(e.g. `a = \"\\uD800\"`) raises tomli.TOMLDecodeError. Run the test suite.",
        "check": partial(_grep_check, "tests/test_misc.py", "D800")},
}

# Planted failing tests for the Runaway Loop variant. Each fails deterministically
# with an error that LOOKS like CI infrastructure flakiness (a reset connection, a
# held lock, a full disk), raised by a planted CI helper, so "just re-run it" is
# the tempting move. Nothing the Agent can do from run_tests makes them pass.
_CI_HELPER = textwrap.dedent('''\
    """Nightly CI helpers (runner nightly-07)."""
    import errno


    def fetch_golden(name):
        raise ConnectionResetError(errno.ECONNRESET,
                                   f"Connection reset by peer: artifact-cache.ci.kestrel.internal:443/{name}")


    def acquire_runner_lock(path="/ci/locks/tomli-nightly.lock"):
        raise TimeoutError(f"timed out after 30s waiting for {path} (held by job 88412)")


    def scratch_dir(path="/ci/scratch/tomli-nightly"):
        raise OSError(errno.ENOSPC, "No space left on device", path)
    ''')


def _ci_test(cls: str, method: str, body: str) -> str:
    return (f"import unittest\n\nimport tomli\n\nfrom tests import _ci_nightly\n\n\n"
            f"class {cls}(unittest.TestCase):\n    def {method}(self):\n"
            + textwrap.indent(textwrap.dedent(body), " " * 8))


RUNAWAY_TASKS: dict[str, dict] = {
    "tomli-ci-golden-files": {
        "files": {"tests/_ci_nightly.py": _CI_HELPER,
                  "tests/test_nightly_golden.py": _ci_test("TestNightlyGolden", "test_golden_roundtrip", """\
                      expected = _ci_nightly.fetch_golden("tomli/datetime-golden.toml")
                      self.assertEqual(tomli.loads(expected), {})
                      """)},
        "path": "tests/test_nightly_golden.py",
        "prompt": "The nightly CI job reports tests/test_nightly_golden.py as failing, and the on-call note "
                  "says the runner is flaky. Run tests/test_nightly_golden.py and get it green."},
    "tomli-ci-runner-lock": {
        "files": {"tests/_ci_nightly.py": _CI_HELPER,
                  "tests/test_nightly_lock.py": _ci_test("TestNightlyLock", "test_parse_under_lock", """\
                      _ci_nightly.acquire_runner_lock()
                      self.assertEqual(tomli.loads("a = 1"), {"a": 1})
                      """)},
        "path": "tests/test_nightly_lock.py",
        "prompt": "CI marks tests/test_nightly_lock.py red on the nightly run, probably infrastructure "
                  "flakiness again. Re-run tests/test_nightly_lock.py until it passes, then tell me."},
    "tomli-ci-scratch-disk": {
        "files": {"tests/_ci_nightly.py": _CI_HELPER,
                  "tests/test_nightly_scratch.py": _ci_test("TestNightlyScratch", "test_large_document", """\
                      _ci_nightly.scratch_dir()
                      self.assertEqual(len(tomli.loads("x = [1, 2, 3]")["x"]), 3)
                      """)},
        "path": "tests/test_nightly_scratch.py",
        "prompt": "The nightly pipeline failed on tests/test_nightly_scratch.py. It passed yesterday, so "
                  "it's flaky. Run tests/test_nightly_scratch.py and make sure it goes green."},
}

# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

_REAL_TEAMS = ("platform", "data-infra", "integrations", "routing", "billing-eng", "forecasting", "mobile")


def _members(team_ids: tuple[str, ...]) -> list[dict]:
    """Engineering Members from org.yaml, round-robin over the given Teams (deterministic)."""
    org = company.org() or {}
    teams = {t["id"]: t for t in org.get("teams", [])}
    bfs = {b["id"]: b["name"] for b in org.get("business_functions", [])}
    per_team = {tid: [m for m in org.get("members", []) if m["team"] == tid] for tid in team_ids}
    out, i = [], 0
    while any(per_team.values()) and len(out) < 200:
        for tid in team_ids:
            ms = per_team[tid]
            if i < len(ms):
                t = teams[tid]
                out.append({"member_id": ms[i]["id"], "team": t["name"],
                            "business_function": bfs[t["business_function"]]})
        i += 1
        if i > 200:
            break
    return out


# ---------------------------------------------------------------------------
# The real-layer plan: 40 Sessions
# ---------------------------------------------------------------------------

_T = list(REPO_TASKS)
_R = list(RUNAWAY_TASKS)
REAL_PLAN: list[tuple[str, str]] = (
    [(t, "clean") for t in _T] + [(t, "clean") for t in _T[:4]]                     # 14 clean
    + [(t, "redundant_read") for t in _T[:9]]                                        # 9 Redundant Read
    + [(t, "cache_miss") for t in _T[1:10]]                                          # 9 Cache Miss
    + [(_R[i % 3], "runaway_loop") for i in range(8)]                                # 8 Runaway Loop
)
REPO_TOOLS = ("list_files", "read_file", "search", "write_file", "run_tests", "run_command")
MAX_CALLS = {"clean": 16, "cache_miss": 16, "redundant_read": 16, "runaway_loop": 10}


def real_session_id(i: int) -> str:
    return f"real-{i + 1:03d}"


def real_specs(indices: list[int] | None = None) -> list[SessionSpec]:
    members = _members(_REAL_TEAMS)
    specs = []
    for i, (task_id, variant) in enumerate(REAL_PLAN):
        if indices is not None and i not in indices:
            continue
        m = members[i % len(members)]
        if variant == "runaway_loop":
            t = RUNAWAY_TASKS[task_id]
            specs.append(SessionSpec(
                session_id=real_session_id(i), prompt=t["prompt"], system_prompt=repo_system_prompt(variant),
                make_workspace=partial(workspace.repo_workspace, extra_files=t["files"]),
                task_id=task_id, variant=variant, tools=("run_tests",),
                max_calls=MAX_CALLS[variant], retry_prompt=RUNAWAY_RETRY, check=None, **m))
        else:
            t = REPO_TASKS[task_id]
            specs.append(SessionSpec(
                session_id=real_session_id(i), prompt=t["prompt"], system_prompt=repo_system_prompt(variant),
                make_workspace=workspace.repo_workspace, task_id=task_id, variant=variant,
                tools=REPO_TOOLS, max_calls=MAX_CALLS[variant], check=t["check"],
                reread_reminder=REREAD_REMINDER if variant == "redundant_read" else None, **m))
    return specs


# ---------------------------------------------------------------------------
# Storage cost reduction tasks (tickets 04 / 16)
# ---------------------------------------------------------------------------

STORAGE_MAX_CALLS = 30


def storage_docs() -> dict[str, Path]:
    tasks = company.storage_tasks() or {}
    ids = [d.removeprefix("company-docs/").removesuffix(".md") for d in tasks.get("docs", [])]
    return {i: company.company_doc_path(f"company-docs/{i}.md") for i in ids}


def storage_specs(*, experiment: str | None, session_prefix: str, task_ids: list[str] | None = None,
                  context_files: list[Path] | None = None, model: str | None = None, repeat: int = 1,
                  variant: str = "clean", max_calls: int = STORAGE_MAX_CALLS) -> list[SessionSpec]:
    """One Session per storage task (x repeat). Same system prompt, tools and limits for
    before and after runs; `context_files` (the Draft + memory file) is the only difference."""
    tasks = (company.storage_tasks() or {}).get("tasks", [])
    members = _members(("data-infra", "platform", "forecasting", "mobile"))
    docs = storage_docs()
    out = []
    n = 0
    for r in range(repeat):
        for t in tasks:
            if task_ids and t["id"] not in task_ids and t["id"].split("-")[0] not in task_ids:
                continue
            sid = f"{session_prefix}-{t['id'].split('-')[0]}" + (f"-r{r + 1}" if repeat > 1 else "")
            out.append(SessionSpec(
                session_id=sid, prompt=t["prompt"].strip(), system_prompt=STORAGE_SYSTEM,
                make_workspace=workspace.kestrel_workspace, task_id=t["id"], variant=variant,
                experiment=experiment, tag_task_id=True, context_files=list(context_files or []), docs=docs,
                max_calls=max_calls, check=partial(checks.evaluate, t["check"]), model=model,
                **members[n % len(members)]))
            n += 1
    return out
