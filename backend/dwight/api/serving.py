"""Fixture-or-store serving. Each endpoint is declared once:

    ep = Endpoint("initiatives", InitiativeList, real=None)   # serves fixtures/api/initiatives.json

    @router.get("/api/initiatives", response_model=InitiativeList)
    def list_initiatives(conn=Depends(get_conn)):
        return ep.serve(conn)

When your stage lands, write `def _from_store(conn, **params) -> dict` and pass
real=_from_store. The dict must match the response model (minus `source`).
DWIGHT_FORCE_FIXTURES=1 forces fixtures everywhere (frontend dev).

Demo pricing: DWIGHT_PRICE_MULTIPLIER (config.PRICE_MULTIPLIER, default 1) scales every
dollar figure as it enters a response, here in money() (and in fixture bodies), so no
store rebuild is needed. Build every figure from raw store dollars with money(); never
feed a served Money's usd back into money(), or it is scaled twice.

Fixture files: fixtures/api/<name>.json holds the response body. For endpoints
with an ID in the path, the file is {"_keyed_by": "<param>", "items": {<id>: body}};
an unknown ID falls back to the first item (so any link renders something).
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Callable, Optional

from fastapi import HTTPException
from pydantic import BaseModel

from dwight import config, db

ENDPOINTS: dict[str, "Endpoint"] = {}


@lru_cache(maxsize=64)
def _fixture_file(name: str) -> Any:
    path = config.API_FIXTURES_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(500, f"missing fixture {path}")
    return json.loads(path.read_text())


def fixture(name: str, key: Optional[str] = None) -> dict:
    data = _fixture_file(name)
    if isinstance(data, dict) and "_keyed_by" in data:
        items = data["items"]
        body = items.get(key) if key is not None else None
        if body is None:
            body = next(iter(items.values()))
        data = body
    return json.loads(json.dumps(data))  # deep copy


class Endpoint:
    def __init__(self, name: str, model: type[BaseModel], real: Optional[Callable[..., dict]] = None):
        self.name, self.model, self.real = name, model, real
        ENDPOINTS[name] = self

    @property
    def source(self) -> str:
        return "fixture" if (self.real is None or config.FORCE_FIXTURES) else "store"

    def serve(self, conn=None, key: Optional[str] = None, **params) -> BaseModel:
        if self.source == "fixture":
            body = _scale_fixture(fixture(self.name, key))
            body["source"] = "fixture"
        else:
            body = self.real(conn, **params)
            body["source"] = "store"
        return self.model.model_validate(body)


def get_conn():
    """FastAPI dependency: one SQLite connection per request."""
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def price_multiplier() -> float:
    """The demo pricing multiplier in force (1 = list prices)."""
    return config.PRICE_MULTIPLIER


def scale(usd: float | None) -> float:
    """A raw store dollar amount at the pricing in force (for text that isn't a Money object)."""
    return float(usd or 0.0) * config.PRICE_MULTIPLIER


@contextmanager
def list_prices():
    """Serve at list prices (multiplier 1) inside the block: the demo snapshot's manifest is canonical."""
    saved = config.PRICE_MULTIPLIER
    config.PRICE_MULTIPLIER = 1.0
    try:
        yield
    finally:
        config.PRICE_MULTIPLIER = saved


def _scale_fixture(obj):
    """Apply the multiplier to every Money object in a fixture body (they bypass money())."""
    if isinstance(obj, dict):
        if "usd" in obj and "kind" in obj:
            return {**obj, "usd": round(scale(obj["usd"]), 6)}
        return {k: _scale_fixture(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scale_fixture(v) for v in obj]
    return obj


def money(usd: float | None, kind: str, note: str | None = None) -> dict:
    """Build a Money dict from a raw store dollar amount. The only way a dollar figure should
    enter a response. Applies the demo pricing multiplier (DWIGHT_PRICE_MULTIPLIER)."""
    d = {"usd": round(scale(usd), 6), "kind": kind}
    if note:
        d["note"] = note
    return d
