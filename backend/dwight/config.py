"""Paths and settings. Everything configurable is an env var (see /.env.example).

A `.env` file at the repo root is loaded if present (simple KEY=VALUE lines).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


def _load_dotenv() -> None:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if value[:1] in ('"', "'") and value[0] in value[1:]:
            value = value[1:value.index(value[0], 1)]  # quoted: keep everything inside the quotes
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()  # drop an inline "  # comment"
        os.environ.setdefault(key.strip(), value)


_load_dotenv()


def _path(env: str, default: Path) -> Path:
    value = os.environ.get(env)
    return Path(value).expanduser().resolve() if value else default


# --- Store -----------------------------------------------------------------
# SQLite file. Tests and experiments should point DWIGHT_DB at their own file.
DB_PATH = _path("DWIGHT_DB", BACKEND_DIR / "var" / "dwight.sqlite")

# --- Content shared with ticket 02 (read-only for pipeline code) ----------
DATA_DIR = REPO_ROOT / "data"
PRICES_PATH = _path("DWIGHT_PRICES", DATA_DIR / "prices.yaml")
COMPANY_DIR = DATA_DIR / "company"
INFRA_PROFILE_PATH = COMPANY_DIR / "infra_profile.yaml"
PRACTICES_PATH = COMPANY_DIR / "practices.yaml"
ORG_PATH = COMPANY_DIR / "org.yaml"
STORAGE_TASKS_PATH = COMPANY_DIR / "storage_tasks.yaml"
COMPANY_DOCS_DIR = REPO_ROOT / "company-docs"
# Hidden labels (true Initiatives, planted patterns, planted facts).
# NEVER read from the classifier, detectors or any pipeline stage except the
# accuracy eval (ticket 08) and acceptance checks (ticket 15).
GROUND_TRUTH_DIR = DATA_DIR / "ground-truth"

# --- Fixtures ----------------------------------------------------------------
FIXTURES_DIR = BACKEND_DIR / "fixtures"
API_FIXTURES_DIR = FIXTURES_DIR / "api"
OTLP_FIXTURES_DIR = FIXTURES_DIR / "otlp"
STORE_FIXTURES_DIR = FIXTURES_DIR / "store"
# "1" forces every API endpoint to serve its fixture JSON (frontend dev).
FORCE_FIXTURES = os.environ.get("DWIGHT_FORCE_FIXTURES", "0") == "1"

# --- Demo pricing --------------------------------------------------------------
# Every dollar figure the API serves is multiplied by this (serving.money()), so the
# demo can show list prices x100 without touching data/prices.yaml or the store.
# 1 = real list prices. Percentages (token drop, accuracy) are never scaled.
PRICE_MULTIPLIER = float(os.environ.get("DWIGHT_PRICE_MULTIPLIER", "1") or 1)

# --- Outputs -----------------------------------------------------------------
OUT_DIR = _path("DWIGHT_OUT_DIR", REPO_ROOT / "out")
POLICY_OUT_DIR = OUT_DIR / "policies"   # ticket 14: "Apply" writes here
DRAFT_OUT_DIR = OUT_DIR / "drafts"      # ticket 12: exported Draft files
# Ticket 15: committed Drafts that `draft` imports instead of regenerating (so the demo
# store shows the exact files the after runs (16) loaded). Unset = always regenerate.
DRAFT_PINNED_DIR = _path("DWIGHT_DRAFT_PINNED_DIR", None) if os.environ.get("DWIGHT_DRAFT_PINNED_DIR") else None

# --- GLM (see dwight/glm.py) -------------------------------------------------
GLM_API_KEY = os.environ.get("SCIFORIUM_API_KEY") or os.environ.get("DWIGHT_GLM_API_KEY")
# The hackathon serves GLM through Sciforium's OpenAI-compatible endpoint.
GLM_BASE_URL = os.environ.get("DWIGHT_GLM_BASE_URL", "https://api.sciforium.com/v1")
# Model tier used by Dwight's own GLM calls when a caller doesn't pass one.
GLM_DEFAULT_TIER = os.environ.get("DWIGHT_GLM_TIER", "standard")
GLM_TIER_MODELS = {
    "flagship": os.environ.get("DWIGHT_GLM_MODEL_FLAGSHIP", "glm-5.1"),
    "standard": os.environ.get("DWIGHT_GLM_MODEL_STANDARD", "glm-4.7"),
    "light": os.environ.get("DWIGHT_GLM_MODEL_LIGHT", "glm-4.5-air"),
}
# Models Dwight's own calls spread across (comma-separated). Calls that don't pass a
# tier round-robin over this pool and fail over to the next model on an API error.
GLM_MODEL_POOL = [m.strip() for m in os.environ.get("DWIGHT_GLM_MODEL_POOL", "").split(",") if m.strip()]
GLM_EMBED_MODEL = os.environ.get("DWIGHT_GLM_EMBED_MODEL", "embedding-3")
# GLM 4.5+ "thinking" mode. Unset = send nothing (the provider may not accept the
# Z.ai-specific `thinking` field); set "disabled"/"enabled" to send it.
GLM_THINKING = os.environ.get("DWIGHT_GLM_THINKING", "")
