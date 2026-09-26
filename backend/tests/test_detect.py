"""Waste detectors (ticket 05, build-spec §4.2).

Expected dollar figures are worked by hand from data/prices.yaml (USD per 1M tokens):
  glm-4.7     standard  input 0.60  cache_read 0.11  output 2.20
  glm-5.1     flagship  input 1.40  cache_read 0.26  output 4.40
  glm-4.5-air light     input 0.20  cache_read 0.03  output 1.10
"""
import json

import pytest

from dwight import config, db
from dwight.api.routes.overview import overview
from dwight.pipeline import discover
from dwight.pipeline.stages.detect import Call, ToolCall, find_waste


def approx(x):
    return pytest.approx(x, abs=1e-12)


def call(seq, *tools, model="glm-4.7", inp=1000, out=100, cr=0, prefix=(None, None)):
    return Call(call_id=f"s:{seq}", seq=seq, model=model, input_tokens=inp, output_tokens=out,
                cache_read_tokens=cr, cache_write_tokens=0,
                prompt_prefix_hash=prefix[0], prompt_prefix_tokens=prefix[1], tools=list(tools))


def read(path, result, tokens):
    return ToolCall(name="read_file", args_hash=f"args-{path}", result_hash=result, result_tokens=tokens)


def run_cmd(cmd, result, tokens=300):
    return ToolCall(name="run_command", args_hash=f"args-{cmd}", result_hash=result, result_tokens=tokens)


def by_pattern(findings, pattern):
    return [f for f in findings if f.pattern == pattern]


# --- clean -------------------------------------------------------------------
def test_clean_session_has_no_findings():
    p = ("sys-a", 500)
    calls = [call(0, read("a.py", "ra", 800), prefix=p, cr=0),
             call(1, read("b.py", "rb", 600), prefix=p, cr=512),
             call(2, run_cmd("pytest", "ok"), prefix=p, cr=1408),
             call(3, prefix=p, cr=1920)]
    assert find_waste(calls, complexity="med") == []


# --- Redundant Read ------------------------------------------------------------
def test_redundant_read_first_call_pays_uncached_later_calls_pay_cache_read():
    # c1 re-reads a.py; the duplicate 1000 tokens enter c2 (first Call to carry them:
    # uncached) and c3 (caching on: cache-read rate).
    calls = [call(0, read("a.py", "ra", 1000)),
             call(1, read("a.py", "ra", 1000), cr=512),
             call(2, cr=1536),
             call(3, cr=2560)]
    [f] = find_waste(calls, complexity="med")
    assert f.pattern == "redundant_read" and f.kind == "measured"
    # 1000 x 0.60/1M + 1000 x 0.11/1M, not 2 x 1000 x 0.60/1M = 0.0012
    assert f.usd == approx(0.00071)
    assert f.evidence == ["s:1", "s:2", "s:3"]


def test_redundant_read_without_caching_is_priced_uncached_on_every_call():
    calls = [call(0, read("a.py", "ra", 1000)),
             call(1, read("a.py", "ra", 1000)),
             call(2),
             call(3)]
    [f] = by_pattern(find_waste(calls, complexity="med"), "redundant_read")
    assert f.usd == approx(0.0012)


def test_each_later_duplicate_is_its_own_finding():
    calls = [call(0, read("a.py", "ra", 1000)),
             call(1, read("a.py", "ra", 1000), cr=512),
             call(2, read("b.py", "rb", 500), cr=1536),
             call(3, read("a.py", "ra", 1000), cr=2048),
             call(4, cr=3072)]
    fs = find_waste(calls, complexity="med")
    assert {f.pattern for f in fs} == {"redundant_read"}
    # dup on c1: c2 uncached 0.0006 + c3, c4 cached 2 x 0.00011 = 0.00082
    # dup on c3: c4 uncached = 0.0006
    assert [f.usd for f in fs] == [approx(0.00082), approx(0.0006)]
    assert [f.evidence for f in fs] == [["s:1", "s:2", "s:3", "s:4"], ["s:3", "s:4"]]


def test_duplicate_read_on_the_last_call_costs_nothing_and_is_not_a_finding():
    calls = [call(0, read("a.py", "ra", 1000)), call(1, read("a.py", "ra", 1000))]
    assert find_waste(calls, complexity="med") == []


# --- Cache Miss ----------------------------------------------------------------
def test_cache_miss_prices_the_missed_prefix_at_the_uncached_minus_cached_rate():
    p = ("sys-v", 2000)
    calls = [call(0, prefix=p),
             call(1, prefix=p, cr=0),         # full miss: 2000 x (0.60 - 0.11)/1M = 0.00098
             call(2, prefix=p, cr=512),       # well below: 1488 x 0.49/1M = 0.00072912
             call(3, prefix=p, cr=1920),      # a normal hit (>= half the prefix): not a miss
             call(4, prefix=("sys-w", 2000))]  # prefix changed: nothing to reuse, not a miss
    [f] = find_waste(calls, complexity="med")
    assert f.pattern == "cache_miss" and f.kind == "measured"
    assert f.usd == approx(0.00170912)
    assert f.evidence == ["s:1", "s:2"]


def test_cache_miss_threshold_is_configurable():
    p = ("sys-v", 2000)
    calls = [call(0, prefix=p), call(1, prefix=p, cr=1920)]
    [f] = find_waste(calls, complexity="med", cache_miss_ratio=1.0)
    assert f.usd == approx(0.0000392)  # 80 x 0.49/1M


def test_no_cache_miss_when_the_model_changes_between_calls():
    p = ("sys-v", 2000)
    calls = [call(0, prefix=p, model="glm-5.1"), call(1, prefix=p, cr=0)]
    assert by_pattern(find_waste(calls, complexity="med"), "cache_miss") == []


# --- Runaway Loop --------------------------------------------------------------
# Each Call below: 1000 uncached input + 100 output on glm-4.7 = 0.0006 + 0.00022 = 0.00082.
def looping_session():
    return [call(0, read("a.py", "ra", 1000)),
            call(1, run_cmd("pytest", "fail")),
            call(2, run_cmd("pytest", "fail")),
            call(3, run_cmd("pytest", "fail")),
            call(4, run_cmd("pytest", "fail")),
            call(5)]


def test_runaway_loop_is_the_spend_of_every_call_after_the_first_in_the_run():
    [f] = find_waste(looping_session(), complexity="med")  # the repeated results are not also Redundant Reads
    assert f.pattern == "runaway_loop" and f.kind == "measured"
    assert f.usd == approx(3 * 0.00082)  # Calls 2, 3, 4
    assert f.evidence == ["s:1", "s:2", "s:3", "s:4"]


def test_runaway_loop_length_is_configurable():
    assert by_pattern(find_waste(looping_session(), complexity="med", loop_min=4), "runaway_loop")
    assert by_pattern(find_waste(looping_session(), complexity="med", loop_min=5), "runaway_loop") == []


def test_a_single_retry_is_not_a_loop():
    calls = [call(0, run_cmd("pytest", "fail")), call(1, run_cmd("pytest", "fail")), call(2)]
    assert by_pattern(find_waste(calls, complexity="med"), "runaway_loop") == []


def test_repeating_a_call_that_returns_new_results_is_not_a_loop():
    # polling a job: same tool + args, but each result is new information
    calls = [call(0, run_cmd("status", "r0")), call(1, run_cmd("status", "r1")),
             call(2, run_cmd("status", "r2")), call(3, run_cmd("status", "r3")), call(4)]
    assert find_waste(calls, complexity="med") == []


def test_calls_already_priced_by_a_loop_are_not_priced_again():
    # a.py is re-read before the loop; its duplicate rides along on every later Call.
    # Loop Calls 3 and 4 are already counted in full, so Redundant Read bills only 2 and 5.
    calls = [call(0, read("a.py", "ra", 1000)),
             call(1, read("a.py", "ra", 1000)),
             call(2, run_cmd("pytest", "fail")),
             call(3, run_cmd("pytest", "fail")),
             call(4, run_cmd("pytest", "fail")),
             call(5)]
    fs = find_waste(calls, complexity="med")
    [loop] = by_pattern(fs, "runaway_loop")
    [rr] = by_pattern(fs, "redundant_read")
    assert loop.usd == approx(2 * 0.00082)
    assert rr.usd == approx(2 * 0.0006)  # Calls 2 and 5, uncached (no caching in this Session)
    assert rr.evidence == ["s:1", "s:2", "s:5"]


# --- Model Overkill -------------------------------------------------------------
def overkill_session(model="glm-5.1"):
    # c0 on glm-5.1: 1000 x 1.40 + 100 x 4.40 = 1840 -> $0.00184; at glm-4.5-air 200 + 110 = 310
    # c1 on glm-5.1: 1000 unc x 1.40 + 1000 cr x 0.26 + 50 x 4.40 = 1880; at air 200 + 30 + 55 = 285
    return [call(0, model=model, inp=1000, out=100),
            call(1, model=model, inp=2000, cr=1000, out=50)]


def test_model_overkill_is_session_spend_minus_the_same_tokens_at_the_cheaper_tier():
    [f] = find_waste(overkill_session(), complexity="low")
    assert f.pattern == "model_overkill" and f.kind == "estimated"
    assert f.usd == approx(0.003125)  # (1840 - 310 + 1880 - 285) / 1M
    assert f.evidence == ["s:0", "s:1"]


@pytest.mark.parametrize("complexity", ["med", "high", None])
def test_no_model_overkill_unless_the_classifier_says_low(complexity):
    assert find_waste(overkill_session(), complexity=complexity) == []


@pytest.mark.parametrize("model", ["glm-4.7", "glm-4.5-air"])
def test_no_model_overkill_below_the_flagship_tier(model):
    assert find_waste(overkill_session(model), complexity="low") == []


@pytest.mark.parametrize("model", ["deepseek-v4.1-flash", "glm-5.3-flash"])
def test_no_model_overkill_on_the_real_layer_pool_models(model):
    # Decision 2026-09-26: both are tier light, so there is no cheaper model to re-price at.
    assert find_waste(overkill_session(model), complexity="low") == []


# --- the stage, on the committed fixture Sessions ---------------------------------
PLANTED = {  # worked by hand from the fixture Calls (see `run seed_fixtures --raw-only`)
    # re-reads of auth/session.py (2400 tokens) on Calls 1 and 3; every later Call caches:
    #   Call 1: 2400 x 0.60 + 5 x 2400 x 0.11 = 2760;  Call 3: 1440 + 3 x 264 = 2232
    "fx-rr-01": ("redundant_read", "measured", [0.00276, 0.002232]),
    # 4 Calls x 3000-token prefix x (0.60 - 0.11), no cache reads
    "fx-cm-01": ("cache_miss", "measured", [0.00588]),
    # 6 identical pytest runs on Calls 1-6; Spend of Calls 2-6 = 786.72 + 832.56 + 878.4 + 924.24 + 970.08
    "fx-rl-01": ("runaway_loop", "measured", [0.004392]),
    # glm-5.1 Spend 6184.64 - the same tokens on glm-4.5-air 975.92
    "fx-mo-01": ("model_overkill", "estimated", [0.00520872]),
}


@pytest.fixture
def fixture_store(conn):
    discover()["seed_fixtures"].run(conn, ["--raw-only"])
    derived = json.loads((config.STORE_FIXTURES_DIR / "derived.json").read_text())
    for s in derived["sessions"]:  # the complexity the classifier would have written
        conn.execute("UPDATE sessions SET complexity=? WHERE session_id=?", (s["complexity"], s["session_id"]))
    conn.commit()
    return conn


def findings(conn):
    return db.rows(conn, "SELECT * FROM waste_findings ORDER BY session_id, pattern, usd DESC")


def test_stage_finds_each_planted_pattern_and_nothing_on_clean_sessions(fixture_store):
    discover()["detect"].run(fixture_store, [])
    got: dict[str, list] = {}
    for f in findings(fixture_store):
        got.setdefault(f["session_id"], []).append(f)
    assert set(got) == set(PLANTED)
    for sid, (pattern, kind, usds) in PLANTED.items():
        assert [(f["pattern"], f["kind"]) for f in got[sid]] == [(pattern, kind)] * len(usds), sid
        assert [f["usd"] for f in got[sid]] == [approx(u) for u in usds], sid
    rl = got["fx-rl-01"][0]
    assert rl["evidence"] == [f"fx-rl-01:{i}" for i in range(1, 7)]


def test_stage_is_idempotent(fixture_store):
    detect = discover()["detect"]
    detect.run(fixture_store, [])
    first = findings(fixture_store)
    detect.run(fixture_store, [])
    assert findings(fixture_store) == first


def test_stage_can_run_on_chosen_sessions_and_loop_length_is_a_cli_option(fixture_store):
    detect = discover()["detect"]
    detect.run(fixture_store, [])
    others = [f for f in findings(fixture_store) if f["session_id"] != "fx-rl-01"]
    detect.run(fixture_store, ["--session", "fx-rl-01", "--loop-min", "7"])
    after = findings(fixture_store)
    assert [f for f in after if f["session_id"] != "fx-rl-01"] == others
    # 6 runs < 7: no loop, so the repeated results are priced as Redundant Reads instead
    assert {f["pattern"] for f in after if f["session_id"] == "fx-rl-01"} == {"redundant_read"}


def test_overview_totals_measured_waste_and_estimated_saving_separately(fixture_store):
    discover()["detect"].run(fixture_store, [])
    o = overview.serve(fixture_store)
    assert o.source == "store"
    assert o.measured_waste.kind == "measured" and o.estimated_saving.kind == "estimated"
    assert o.spend.kind == "measured"
    # Money is rounded to 6 decimals
    assert o.measured_waste.usd == pytest.approx(0.015264, abs=5e-7)  # 0.00276 + 0.002232 + 0.00588 + 0.004392
    assert o.estimated_saving.usd == pytest.approx(0.005209, abs=5e-7)
