from dwight import db
from dwight.pipeline import discover


def test_every_component_has_a_registered_stage():
    stages = discover()
    for name in ["ingest", "classify", "detect", "common_paths", "repeated_discoveries", "recommend", "draft"]:
        assert name in stages and stages[name].in_default_run
    orders = [s.order for s in stages.values()]
    assert orders == sorted(orders)


def test_seed_fixtures(conn):
    msg = discover()["seed_fixtures"].run(conn, [])
    assert "classified" in msg
    patterns = {r["pattern"] for r in db.rows(conn, "SELECT pattern FROM waste_findings")}
    assert patterns == {"redundant_read", "cache_miss", "runaway_loop", "model_overkill"}
    forms = {r["form"] for r in db.rows(conn, "SELECT form FROM recurring_discoveries")}
    assert forms == {"common_path", "repeated_discovery"}
    # classified Sessions have no staged raw content left; the unclassified tracer still does
    staged = {r["session_id"] for r in db.rows(conn, "SELECT DISTINCT session_id FROM staging_content")}
    assert staged == {"tracer-0001"}
    exp = db.rows(conn, "SELECT experiment, COUNT(*) n, SUM(task_success) ok FROM sessions "
                        "WHERE experiment IS NOT NULL GROUP BY experiment ORDER BY experiment")
    assert [(e["experiment"], e["n"], e["ok"]) for e in exp] == [("after", 6, 6), ("before", 6, 5)]
