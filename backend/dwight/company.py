"""Loaders for the fictional Customer's hand-written content (ticket 02).

All loaders tolerate a missing file and return None, so stages can start before
02 lands. They never read data/ground-truth/ (see config.GROUND_TRUTH_DIR).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from dwight import config


def _load(path: Path) -> Any | None:
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text())


def infra_profile() -> dict | None:
    """Models/tiers, gateway, caching, internal docs/MCP servers, repositories."""
    return _load(config.INFRA_PROFILE_PATH)


def practices() -> Any | None:
    """Practice Library (versioned)."""
    return _load(config.PRACTICES_PATH)


def org() -> dict | None:
    """Business Functions, Teams, Members, Initiatives."""
    return _load(config.ORG_PATH)


def storage_tasks() -> Any | None:
    """The ~10 storage cost reduction task prompts with pass/fail checks."""
    return _load(config.STORAGE_TASKS_PATH)


def company_doc_path(resource_id: str) -> Path:
    """Where a company-docs resource lives. resource_id is repo-relative,
    e.g. 'company-docs/storage-tiers.md'. Drafter re-fetches from here (ADR 0008)."""
    rel = resource_id.removeprefix("company-docs/")
    return config.COMPANY_DOCS_DIR / rel
