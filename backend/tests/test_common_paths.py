"""Common paths (ticket 10, build-spec §4.6.1).

Seams: the stage's run(conn, args), observed through the rows it owns in
recurring_discoveries (form='common_path'), and the Recurring Discovery endpoint.
Expected values are worked by hand from data/prices.yaml, not recomputed like the code.
"""
import pytest

from dwight import db
from dwight.pipeline import discover

STORAGE_DOCS = [
    "company-docs/blobctl-migration-runbook.md",
    "company-docs/storage-cost-dashboard.md",
    "company-docs/storage-service-ownership.md",
    "company-docs/storage-tiering-policy.md",
]


def run_stage(conn, *args):
    return discover()["common_paths"].run(conn, list(args))


def common_paths(conn, initiative_id=None):
    sql = "SELECT * FROM recurring_discoveries WHERE form='common_path'"
    params = ()
    if initiative_id:
        sql += " AND initiative_id=?"
        params = (initiative_id,)
    return db.rows(conn, sql + " ORDER BY initiative_id", params)


@pytest.fixture
def seeded(conn):
    discover()["seed_fixtures"].run(conn, [])
    return conn


def test_fixture_storage_docs_are_the_common_path(seeded):
    run_stage(seeded)
    [cp] = common_paths(seeded, "storage-cost-reduction")
    assert sorted(cp["resource_ids"]) == STORAGE_DOCS


def test_fixture_common_path_counts_the_sessions_that_read_every_doc(seeded):
    # 8 analysed storage Sessions (b01-b06, 07, 08; the 6 'after' runs are excluded).
    # fx-scr-08 skipped the ownership doc, so 7 of 8 read all 4 docs.
    run_stage(seeded)
    [cp] = common_paths(seeded, "storage-cost-reduction")
    assert cp["session_count"] == 7
    assert cp["session_share"] == pytest.approx(0.875)
    assert cp["evidence"] == ["fx-scr-07", "fx-scr-b01", "fx-scr-b02", "fx-scr-b03",
                              "fx-scr-b04", "fx-scr-b05", "fx-scr-b06"]
    # one full read of the path: 5600 + 4800 + 4100 + 5200
    assert cp["tokens"] == 19700


def add_session(conn, sid, initiative_id, calls, trail, experiment=None):
    """calls: [(model, cache_read_tokens)] by seq; trail: [(resource_id, tokens, call_seq)]."""
    conn.execute("INSERT OR IGNORE INTO initiatives (initiative_id, name) VALUES (?, ?)", (initiative_id, initiative_id))
    conn.execute("INSERT INTO sessions (session_id, member_id, team, business_function, agent, started_at, ended_at, "
                 "experiment, initiative_id, ingested_at) VALUES (?, 'm1', 'Platform', 'Engineering', 'agent', "
                 "'2026-09-01T00:00:00Z', '2026-09-01T01:00:00Z', ?, ?, '2026-09-01T02:00:00Z')",
                 (sid, experiment, initiative_id))
    for seq, (model, cache_read) in enumerate(calls):
        conn.execute("INSERT INTO calls (call_id, session_id, seq, model, input_tokens, cache_read_tokens) "
                     "VALUES (?, ?, ?, ?, 50000, ?)", (f"{sid}:{seq}", sid, seq, model, cache_read))
    for pos, (rid, tokens, call_seq) in enumerate(trail):
        conn.execute("INSERT INTO trail_entries (session_id, position, resource_id, tokens, call_seq) "
                     "VALUES (?, ?, ?, ?, ?)", (sid, pos, rid, tokens, call_seq))
    conn.commit()


@pytest.fixture
def priced(conn):
    """Initiative 'x', 3 analysed Sessions. doc/a.md is in 2 of 3 Trails (common), doc/b.md in 1 (not)."""
    # s1: read at Call 0 -> carried by Calls 1, 2, 3. Call 1 is the first to carry it (uncached, even though
    # it has cache reads); Call 2 cache-read on glm-4.7; Call 3 cache-read on glm-5.1.
    add_session(conn, "s1", "x", [("glm-4.7", 0), ("glm-4.7", 900), ("glm-4.7", 500), ("glm-5.1", 800)],
                [("doc/a.md", 1000, 0), ("doc/b.md", 3000, 1)])
    # s2 (glm-5.1): read at Call 0 -> Calls 1, 2. Call 2 had no cache reads, so it paid uncached again.
    # The re-read at the last Call enters no billed Call.
    add_session(conn, "s2", "x", [("glm-5.1", 0), ("glm-5.1", 0), ("glm-5.1", 0)],
                [("doc/a.md", 2000, 0), ("doc/a.md", 2000, 2)])
    add_session(conn, "s3", "x", [("glm-4.7", 0)], [("doc/c.md", 700, 0)])
    return conn


def test_common_path_spend_is_tokens_times_the_input_rate_each_call_paid(priced):
    run_stage(priced)
    [cp] = common_paths(priced, "x")
    assert cp["resource_ids"] == ["doc/a.md"]
    assert cp["evidence"] == ["s1", "s2"]
    assert cp["session_count"] == 2
    assert cp["session_share"] == pytest.approx(2 / 3)
    # s1: 1000 x $0.60/M (Call 1, uncached) + 1000 x $0.11/M (Call 2) + 1000 x $0.26/M (Call 3) = $0.00097
    # s2: 2000 x $1.40/M (Call 1) + 2000 x $1.40/M (Call 2, no cache reads) + 0 (last-Call re-read) = $0.0056
    assert cp["spend_usd"] == pytest.approx(0.00657, abs=1e-12)
    # mean tokens per read of doc/a.md: (1000 + 2000 + 2000) / 3
    assert cp["tokens"] == 1667


def test_fixture_common_path_spend(seeded):
    # All glm-4.7 ($0.60/M uncached, $0.11/M cache-read); every Call after the first has cache reads.
    # 8-Call Session (b01-b05, 07): docs read at Calls 0-3, so uncached 19700 once, cache-read
    #   5200x6 + 4800x5 + 4100x4 + 5600x3 = 88400 -> $0.011820 + $0.009724 = $0.021544
    # b06 (7 Calls): cache-read 5200x5 + 4800x4 + 4100x3 + 5600x2 = 68700 -> $0.011820 + $0.007557 = $0.019377
    # 08 (5 Calls, 3 docs at Calls 0-2): uncached 15600, cache-read 5200x3 + 4800x2 + 5600 = 30800
    #   -> $0.009360 + $0.003388 = $0.012748
    run_stage(seeded)
    [cp] = common_paths(seeded, "storage-cost-reduction")
    assert cp["spend_usd"] == pytest.approx(6 * 0.021544 + 0.019377 + 0.012748, abs=1e-9)


def test_share_threshold_is_configurable(priced):
    run_stage(priced)
    assert len(common_paths(priced, "x")) == 1
    run_stage(priced, "--threshold", "0.9")  # doc/a.md is in 2/3 of Trails: below 90%, so the stale row goes
    assert common_paths(priced, "x") == []
    run_stage(priced, "--threshold", "0.3")  # 1/3 now qualifies: doc/b.md and doc/c.md join
    [cp] = common_paths(priced, "x")
    assert cp["resource_ids"] == ["doc/a.md", "doc/b.md", "doc/c.md"]
    assert cp["evidence"] == []  # no Session read all three


def test_after_runs_are_not_analysed(priced):
    # 'after' runs had the Draft loaded; counting them would dilute the share (2/6 < 60%)
    for i in range(3):
        add_session(priced, f"a{i}", "x", [("glm-4.7", 0), ("glm-4.7", 0)], [], experiment="after")
    run_stage(priced)
    [cp] = common_paths(priced, "x")
    assert cp["session_share"] == pytest.approx(2 / 3)


def test_rerun_is_idempotent_and_leaves_repeated_discoveries_alone(priced):
    priced.execute("INSERT INTO recurring_discoveries (recurring_discovery_id, initiative_id, form, statement, "
                   "session_count, session_share, spend_usd) VALUES ('rd-11', 'x', 'repeated_discovery', "
                   "'needs STORAGE_ENV=staging', 2, 0.66, 0.01)")
    run_stage(priced)
    first = common_paths(priced, "x")
    run_stage(priced)
    assert common_paths(priced, "x") == first
    forms = db.rows(priced, "SELECT recurring_discovery_id, form FROM recurring_discoveries ORDER BY form")
    assert forms == [{"recurring_discovery_id": first[0]["recurring_discovery_id"], "form": "common_path"},
                     {"recurring_discovery_id": "rd-11", "form": "repeated_discovery"}]


def test_full_run_drops_common_paths_of_initiatives_without_sessions(priced):
    priced.execute("INSERT INTO initiatives (initiative_id, name) VALUES ('gone', 'Gone')")
    priced.execute("INSERT INTO recurring_discoveries (recurring_discovery_id, initiative_id, form, resource_ids_json, "
                   "session_count, session_share, spend_usd) VALUES ('rd-old', 'gone', 'common_path', '[]', 1, 1, 0)")
    run_stage(priced, "--initiative", "x")  # scoped run: other Initiatives untouched
    assert [cp["initiative_id"] for cp in common_paths(priced)] == ["gone", "x"]
    run_stage(priced)
    assert [cp["initiative_id"] for cp in common_paths(priced)] == ["x"]


@pytest.fixture
def api(seeded):
    from fastapi.testclient import TestClient

    from dwight.api.main import app
    from dwight.api.serving import get_conn

    app.dependency_overrides[get_conn] = lambda: seeded
    yield TestClient(app)
    app.dependency_overrides.pop(get_conn, None)


def test_endpoint_serves_both_forms_from_the_store(api, seeded):
    run_stage(seeded)  # the repeated_discovery row comes from the seeded fixtures (ticket 11 writes it for real)
    r = api.get("/api/initiatives/storage-cost-reduction/recurring-discoveries").json()
    assert r["source"] == "store"
    assert r["initiative_session_count"] == 8
    cp, rep = r["items"]
    assert cp["form"] == "common_path"
    assert cp["resources"] == [
        {"resource_id": "company-docs/blobctl-migration-runbook.md", "tokens": 5600},
        {"resource_id": "company-docs/storage-cost-dashboard.md", "tokens": 4800},
        {"resource_id": "company-docs/storage-service-ownership.md", "tokens": 4100},
        {"resource_id": "company-docs/storage-tiering-policy.md", "tokens": 5200},
    ]
    assert (cp["tokens"], cp["session_count"], cp["session_share"]) == (19700, 7, 0.875)
    assert cp["cost"] == {"usd": 0.161389, "kind": "measured", "note": None}
    assert len(cp["evidence"]) == 7
    assert rep["form"] == "repeated_discovery"
    assert rep["statement"] == "blobctl plan/apply needs STORAGE_ENV=staging for Tidewater migrations."
    assert rep["resources"] == []
    assert rep["session_count"] == 6
    assert rep["cost"]["kind"] == "measured"
    assert rep["cost"]["note"] == "conservative upper bound"


def test_endpoint_for_an_initiative_with_nothing_recurring(api, seeded):
    run_stage(seeded)
    r = api.get("/api/initiatives/auth-migration/recurring-discoveries").json()
    assert (r["source"], r["initiative_session_count"], r["items"]) == ("store", 3, [])


def test_fixture_has_no_other_common_paths(seeded):
    # auth-migration's 3 Sessions share no resource; the rest have < 3 Sessions
    run_stage(seeded)
    assert [cp["initiative_id"] for cp in common_paths(seeded)] == ["storage-cost-reduction"]
