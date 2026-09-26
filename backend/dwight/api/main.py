"""FastAPI app. Run: cd backend && .venv/bin/uvicorn dwight.api.main:app --reload --port 8000

Routers are discovered: every module in dwight/api/routes/ that defines
`router` is included. Adding an endpoint = adding (or editing your own) file.
"""
from __future__ import annotations

import importlib
import pkgutil

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dwight import config
from dwight.api import routes as _routes_pkg
from dwight.api.contract import Health
from dwight.api.serving import ENDPOINTS, get_conn

app = FastAPI(title="Dwight API", version="0.1.0",
              description="Contract: docs/api-contract.md and dwight/api/contract.py")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

for _info in pkgutil.iter_modules(_routes_pkg.__path__):
    _mod = importlib.import_module(f"{_routes_pkg.__name__}.{_info.name}")
    if hasattr(_mod, "router"):
        app.include_router(_mod.router)


@app.get("/api/health", response_model=Health)
def health(conn=Depends(get_conn)):
    n = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    return Health(ok=True, db_path=str(config.DB_PATH), sessions=n,
                  endpoint_sources={name: ep.source for name, ep in sorted(ENDPOINTS.items())})
