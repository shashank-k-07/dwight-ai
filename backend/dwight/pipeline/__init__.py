"""Pipeline stage registry.

Every stage is its own module in dwight/pipeline/stages/. A module is a stage
if it defines `run(conn, args)`. Discovery is by module name, so adding a stage
= adding a file; nothing shared needs editing.

Stage module contract:
    ORDER: int            position in `run-all` (ingest=10 ... draft=70)
    TICKET: str           owning ticket, e.g. "05"
    DESCRIPTION: str      one line
    IN_DEFAULT_RUN: bool  (optional, default True) include in `run-all`
    def run(conn: sqlite3.Connection, args: list[str]) -> str | None
        do the work, commit, return a one-line summary. Parse your own CLI
        args (argparse) from `args`.

CLI: python -m dwight.pipeline --help
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from types import ModuleType

from dwight.pipeline import stages as _stages_pkg


@dataclass
class Stage:
    name: str
    order: int
    ticket: str
    description: str
    in_default_run: bool
    module: ModuleType

    def run(self, conn, args: list[str] | None = None):
        return self.module.run(conn, list(args or []))


def discover() -> dict[str, Stage]:
    found: dict[str, Stage] = {}
    for info in pkgutil.iter_modules(_stages_pkg.__path__):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{_stages_pkg.__name__}.{info.name}")
        if not callable(getattr(mod, "run", None)):
            continue
        found[info.name] = Stage(
            name=info.name, order=getattr(mod, "ORDER", 999), ticket=getattr(mod, "TICKET", "?"),
            description=getattr(mod, "DESCRIPTION", ""), in_default_run=getattr(mod, "IN_DEFAULT_RUN", True),
            module=mod)
    return dict(sorted(found.items(), key=lambda kv: (kv[1].order, kv[0])))


class NotImplementedYet(Exception):
    """Raised by stub stages. run-all reports and skips them."""
