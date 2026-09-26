"""SQLite store. One file (config.DB_PATH, override with DWIGHT_DB).

SQLite rather than DuckDB: the API and many pipeline processes (and ~9 agents'
tests) touch the store at once; DuckDB allows only one read-write process,
SQLite in WAL mode handles concurrent readers + a writer fine.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from dwight import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


@contextmanager
def session(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """`with db.session() as conn:` commits on success, rolls back on error."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
    """Run a query and return plain dicts. Columns ending in _json are decoded
    and renamed without the suffix (resource_ids_json -> resource_ids)."""
    out = []
    for r in conn.execute(sql, params).fetchall():
        d = {}
        for k in r.keys():
            v = r[k]
            if k.endswith("_json"):
                d[k[:-5]] = json.loads(v) if v is not None else None
            else:
                d[k] = v
        out.append(d)
    return out


def dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))
