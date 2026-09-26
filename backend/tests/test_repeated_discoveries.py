"""Repeated Discoveries (ticket 11, build-spec §4.6.2).

No live model calls: `dwight.glm.chat_json` is replaced by a fake "model" that
groups the statements it is shown by a keyword, the way a real model would
group paraphrases of one fact.
"""
from __future__ import annotations

import json
import re

import pytest

from dwight import db, glm
from dwight.pipeline import discover
from dwight.pipeline.stages import repeated_discoveries as stage
from dwight.pipeline.stages._discovery_clusters import cluster_statements

# From fixtures/store/derived.json (fixtures/generate.py): the env-var fact, found in
# 6 of the 8 non-"after" storage Sessions, spend up to its call_seq summed over them.
ENV_SESSIONS = {"fx-scr-b01", "fx-scr-b02", "fx-scr-b03", "fx-scr-b04", "fx-scr-b05", "fx-scr-07"}
ENV_SPEND_USD = 0.13183247999999997


def _shown_items(messages) -> list[dict]:
    """The {id, statement} list the stage put in its prompt."""
    text = messages[-1]["content"]
    return json.loads(text[text.index("["):text.rindex("]") + 1])


def keyword_model(keywords=("STORAGE_ENV",), calls=None):
    """A fake chat_json: groups every shown statement containing a keyword."""
    def fake(messages, *, schema=None, tier=None, **kw):
        items = _shown_items(messages)
        if calls is not None:
            calls.append(items)
        groups = []
        for k in keywords:
            ids = [it["id"] for it in items if k in it["statement"]]
            if len(ids) >= 2:
                groups.append({"ids": ids, "statement": f"Always set {k} before running the tool."})
        return schema.model_validate({"groups": groups})
    return fake


@pytest.fixture
def seeded(conn):
    discover()["seed_fixtures"].run(conn, [])
    return conn


def _repeated(conn, initiative_id=None):
    sql = "SELECT * FROM recurring_discoveries WHERE form='repeated_discovery'"
    params: tuple = ()
    if initiative_id:
        sql += " AND initiative_id=?"
        params = (initiative_id,)
    return db.rows(conn, sql, params)


def test_planted_env_var_fact_is_one_repeated_discovery_and_one_offs_are_not(seeded, monkeypatch):
    monkeypatch.setattr(glm, "chat_json", keyword_model())
    discover()["repeated_discoveries"].run(seeded, [])

    rows = _repeated(seeded)
    assert len(rows) == 1
    rd = rows[0]
    assert rd["initiative_id"] == "storage-cost-reduction"
    assert rd["statement"] == "Always set STORAGE_ENV before running the tool."
    assert set(rd["evidence"]) == ENV_SESSIONS
    assert rd["session_count"] == 6
    assert rd["session_share"] == pytest.approx(0.75)   # 6 of 8: "after" runs are excluded
    assert rd["spend_usd"] == pytest.approx(ENV_SPEND_USD)
    assert rd["resource_ids"] is None and rd["tokens"] is None
    # the common_path row from the fixtures is not the stage's to touch
    assert {r["form"] for r in db.rows(seeded, "SELECT form FROM recurring_discoveries")} == {
        "common_path", "repeated_discovery"}


# --- thresholds and Measured spend (pure arithmetic) ---------------------------

def _found_in(n_sessions, spend=1.0):
    """One cluster found once in each of n Sessions, each with `spend` up to its call_seq."""
    ds = {(f"s{i}", 0): stage.Discovery(f"s{i}", 0, "fact", 3, spend) for i in range(n_sessions)}
    return [stage.Cluster(keys=tuple(ds), statement="Do the thing.", named=True)], ds


@pytest.mark.parametrize("found,population,repeated", [
    (5, 100, True),    # >= 5 Sessions, although only 5%
    (4, 10, True),     # 40% >= 20%, although < 5 Sessions
    (4, 30, False),    # 4 Sessions and 13%: neither
    (1, 1, False),     # 100%, but a one-off is never repeated
    (1, 3, False),     # the fixture's REDIS_URL one-off: 33% of auth-migration
])
def test_default_thresholds(found, population, repeated):
    clusters, ds = _found_in(found)
    assert bool(stage.score("i", clusters, ds, population)) is repeated


def test_thresholds_are_configurable():
    clusters, ds = _found_in(5)
    strict = stage.Thresholds(min_sessions=6, min_share=0.5, floor=2)
    assert stage.score("i", clusters, ds, 20, strict) == []
    assert stage.score("i", clusters, ds, 10, strict) != []   # 50%


def test_spend_counts_each_session_once_up_to_its_earliest_establishing_call():
    ds = {("a", 0): stage.Discovery("a", 0, "x", 2, 0.10),
          ("a", 1): stage.Discovery("a", 1, "x again", 7, 0.40),   # same Session, later: not added
          ("b", 0): stage.Discovery("b", 0, "x", 4, 0.25)}
    clusters = [stage.Cluster(keys=(("a", 1), ("b", 0), ("a", 0)), statement="Set X.", named=True)]
    [row] = stage.score("init", clusters, ds, population=4)
    assert row["session_count"] == 2
    assert row["session_share"] == 0.5
    assert row["spend_usd"] == pytest.approx(0.35)
    assert row["evidence"] == ["a", "b"]
    assert row["form"] == "repeated_discovery" and row["statement"] == "Set X."


def test_cli_thresholds_reach_the_stage(seeded, monkeypatch):
    monkeypatch.setattr(glm, "chat_json", keyword_model())
    discover()["repeated_discoveries"].run(seeded, ["--min-sessions", "7", "--min-share", "0.8"])
    assert _repeated(seeded) == []


# --- the stage in the store ------------------------------------------------------

def test_rerunning_gives_the_same_rows_and_leaves_common_paths_alone(seeded, monkeypatch):
    monkeypatch.setattr(glm, "chat_json", keyword_model())
    common_before = db.rows(seeded, "SELECT * FROM recurring_discoveries WHERE form='common_path'")
    discover()["repeated_discoveries"].run(seeded, [])
    first = _repeated(seeded)
    discover()["repeated_discoveries"].run(seeded, [])
    assert _repeated(seeded) == first
    assert db.rows(seeded, "SELECT * FROM recurring_discoveries WHERE form='common_path'") == common_before


def test_the_panel_endpoint_serves_the_rows_unchanged(seeded, monkeypatch):
    from fastapi.testclient import TestClient

    from dwight.api.main import app
    from dwight.api.serving import get_conn

    monkeypatch.setattr(glm, "chat_json", keyword_model())
    discover()["repeated_discoveries"].run(seeded, [])
    app.dependency_overrides[get_conn] = lambda: seeded
    try:
        r = TestClient(app).get("/api/initiatives/storage-cost-reduction/recurring-discoveries").json()
    finally:
        app.dependency_overrides.pop(get_conn, None)
    assert r["source"] == "store"
    [rep] = [i for i in r["items"] if i["form"] == "repeated_discovery"]
    assert rep["statement"] == "Always set STORAGE_ENV before running the tool."
    assert rep["session_count"] == 6
    assert rep["session_share"] == pytest.approx(rep["session_count"] / r["initiative_session_count"])
    assert rep["cost"]["kind"] == "measured" and rep["cost"]["note"] == "conservative upper bound"
    assert rep["cost"]["usd"] == pytest.approx(ENV_SPEND_USD, abs=1e-6)
    assert set(rep["evidence"]) == ENV_SESSIONS


def test_prompt_content_never_reaches_the_model(seeded, monkeypatch):
    """ADR 0008: only stored Discoveries go to the model, never staged prompt content."""
    seeded.execute("INSERT INTO staging_content (session_id, seq, kind, content) VALUES (?,?,?,?)",
                   ("fx-scr-b01", 1, "input_messages", "SECRET-PROMPT-TEXT"))
    seen = []
    monkeypatch.setattr(glm, "chat_json", keyword_model(calls=seen))
    discover()["repeated_discoveries"].run(seeded, [])
    shown = {it["statement"] for batch in seen for it in batch}
    stored = {r["statement"] for r in db.rows(seeded, "SELECT statement FROM discoveries")}
    assert seen and shown <= stored


def test_one_failing_initiative_keeps_its_old_rows_and_fails_the_stage(seeded, monkeypatch):
    monkeypatch.setattr(glm, "chat_json", keyword_model())
    discover()["repeated_discoveries"].run(seeded, [])
    before = _repeated(seeded, "storage-cost-reduction")

    def broken(*a, **kw):
        raise glm.GLMBadOutput("no JSON")
    monkeypatch.setattr(glm, "chat_json", broken)
    with pytest.raises(RuntimeError, match="storage-cost-reduction"):
        discover()["repeated_discoveries"].run(seeded, [])
    assert _repeated(seeded, "storage-cost-reduction") == before


# --- grouping by the model: validation and batching ------------------------------

def test_model_output_is_validated(monkeypatch):
    def sloppy(messages, *, schema=None, **kw):
        return schema.model_validate({"groups": [
            {"ids": ["d1", "d2", "d99"], "statement": "Set A=1."},   # d99 doesn't exist
            {"ids": ["d2", "d3"], "statement": "Set A=1 too."},      # d2 already claimed
            {"ids": ["d4"], "statement": "Alone."},                   # a group needs 2+
            {"ids": ["d5", "d6"], "statement": "   "},                # no statement
        ]})
    monkeypatch.setattr(glm, "chat_json", sloppy)
    items = [(k, f"statement {k}") for k in "abcdef"]
    # the batch is shown in its own order; map the shown ids back to keys by position
    import dwight.pipeline.stages._discovery_clusters as dc
    monkeypatch.setattr(dc, "_locality_key", lambda s: s)
    clusters = cluster_statements(items)
    assert sorted(c.keys for c in clusters) == [("a", "b"), ("c",), ("d",), ("e",), ("f",)]
    merged = next(c for c in clusters if c.keys == ("a", "b"))
    assert merged.statement == "Set A=1." and merged.named
    assert all(not c.named for c in clusters if c is not merged)


def test_a_fact_spread_across_batches_still_becomes_one_cluster(monkeypatch):
    calls = []
    monkeypatch.setattr(glm, "chat_json", keyword_model(keywords=("PLANTED_VAR",), calls=calls))
    items = [((f"s{i}", 0), f"Unrelated finding number {i} about module_{i}.") for i in range(230)]
    for i in range(0, 230, 23):   # 10 wordings of one fact, spread through the list
        items[i] = ((f"s{i}", 0), f"Variant {i}: the tool needs PLANTED_VAR set.")
    clusters = cluster_statements(items, batch_size=40, workers=3)
    assert all(len(batch) <= 40 for batch in calls) and len(calls) > 1
    fact = [c for c in clusters if len(c.keys) > 1]
    assert len(fact) == 1 and len(fact[0].keys) == 10
    assert sorted(k for c in clusters for k in c.keys) == sorted(k for k, _ in items)   # nothing lost


def test_parts_of_one_fact_grouped_in_different_batches_are_merged(monkeypatch):
    calls = []
    monkeypatch.setattr(glm, "chat_json", keyword_model(keywords=("planted variable",), calls=calls))
    letters = "abcdefghij"
    # no identifiers, so batches follow alphabetical order: each letter block holds 23
    # one-offs and 2 wordings of the fact, and the blocks span several batches
    items = [((f"{a}{b}", 0), f"{a}{b} unrelated note") for a in letters for b in "bcdefghijklmnopqrstuvwx"]
    items += [((f"{a}-fact-{n}", 0), f"{a}a the planted variable is needed, case {n}")
              for a in letters for n in (1, 2)]
    clusters = cluster_statements(items, batch_size=60)
    first_round = calls[:5]
    assert sum(1 for b in first_round if sum("planted variable" in it["statement"] for it in b) >= 2) >= 2
    fact = [c for c in clusters if len(c.keys) > 1]
    assert len(fact) == 1 and len(fact[0].keys) == 20
