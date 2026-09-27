"""Policy export (ticket 14): turn a Policy (a Team + its allowed models) into the
config the Customer's own gateway enforces. Dwight never enforces it (ADR 0002).

The Customer's gateway is LiteLLM (Infra Profile `gateway.type`), so the export is a
LiteLLM team model allowlist: one `teams:` entry whose fields are those of LiteLLM's
team object (`/team/new`, `/team/update`): `team_alias`, `models`, `metadata`. It lands in
config.POLICY_OUT_DIR/<team id>.yaml, the file the Admin commits to the gateway's
config repo at `gateway.team_config_path`.

Teams come from data/company/org.yaml, models from the Infra Profile's tiers.
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from dwight import company, config, db


class PolicyError(ValueError):
    """The request names a Team or model the org / Infra Profile doesn't have."""


# --- Options ----------------------------------------------------------------------
def teams() -> list[dict]:
    """Every Team in org.yaml: {team_id, team, business_function} (display names)."""
    org = company.org() or {}
    bf_names = {bf["id"]: bf["name"] for bf in org.get("business_functions") or []}
    return [{"team_id": t["id"], "team": t["name"],
             "business_function": bf_names.get(t.get("business_function"), t.get("business_function") or "")}
            for t in org.get("teams") or []]


def model_tiers() -> list[dict]:
    """The Infra Profile's tiers, in profile order: {model, tier, gateway_alias, intended_for}."""
    profile = company.infra_profile() or {}
    return [{"model": t["model"], "tier": t["tier"], "gateway_alias": t.get("gateway_alias"),
             "intended_for": t.get("intended_for")}
            for t in (profile.get("models") or {}).get("tiers") or []]


def options() -> dict:
    """PolicyOptions body (minus source)."""
    return {"teams": [{"team": t["team"], "business_function": t["business_function"]} for t in teams()],
            "models": [{"model": m["model"], "tier": m["tier"]} for m in model_tiers()]}


# --- Validation ----------------------------------------------------------------------
def resolve_team(name: str) -> dict:
    """Find a Team by display name ("Data Infrastructure") or org id ("data-infra"),
    case-insensitively. Raises PolicyError if there is no such Team."""
    key = (name or "").strip().casefold()
    for t in teams():
        if key in (t["team"].casefold(), t["team_id"].casefold()):
            return t
    raise PolicyError(f"unknown Team {name!r}: not in data/company/org.yaml")


def normalise_models(models: list[str]) -> list[dict]:
    """Dedupe, check each model is an Infra Profile tier, and order flagship -> economy."""
    tiers = model_tiers()
    known = {m["model"] for m in tiers}
    unknown = sorted({m for m in models if m not in known})
    if unknown:
        raise PolicyError(f"not in the Infra Profile's model tiers: {', '.join(unknown)} "
                          f"(choose from {', '.join(m['model'] for m in tiers)})")
    wanted = set(models)
    return [m for m in tiers if m["model"] in wanted]


# --- Render ------------------------------------------------------------------------
class _IndentedDumper(yaml.SafeDumper):
    """Indent list items under their key (`models:\\n  - a`), the style LiteLLM docs use."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def output_filename(team: dict) -> str:
    return f"{team['team_id']}.yaml"


def render(team_name: str, allowed_models: list[str]) -> dict:
    """PolicyRender body (minus source): {team, allowed_models, format, rendered_config}.

    An empty model list renders comments only: in LiteLLM an empty team `models` list
    means *every* model, so Dwight never writes one (apply() refuses it)."""
    team = resolve_team(team_name)
    tiers = normalise_models(allowed_models)
    profile = company.infra_profile() or {}
    gw = profile.get("gateway") or {}
    gw_name = gw.get("name", "the gateway")
    target = f"{gw.get('config_repo', 'the gateway config repo')}:{gw.get('team_config_path', '')}{output_filename(team)}"

    header = [
        "# LiteLLM team model allowlist, rendered by Dwight. Enforced by the Customer's gateway (ADR 0002).",
        f"# Team: {team['team']} ({team['business_function']})",
    ]
    if not tiers:
        header += ["# No models chosen. Nothing to export: an empty LiteLLM `models` list allows every model."]
        return {"team": team["team"], "allowed_models": [], "format": "litellm",
                "rendered_config": "\n".join(header) + "\n"}

    header += ["# Allowed: " + "; ".join(
        f"{m['tier']} {m['model']}" + (f" (alias {m['gateway_alias']})" if m.get("gateway_alias") else "")
        for m in tiers)]
    header += [f"# Gateway: {gw_name}. Commit to {target},",
               "# or send the team entry to the proxy's /team/update (or /team/new)."]
    models: list[str] = []
    for m in tiers:  # the model name and its gateway alias, so either way of calling it is allowed
        for name in (m["model"], m.get("gateway_alias")):
            if name and name not in models:
                models.append(name)
    body = {"teams": [{
        "team_alias": team["team_id"],
        "models": models,
        "metadata": {"managed_by": "dwight", "team": team["team"],
                     "business_function": team["business_function"]},
    }]}
    rendered = "\n".join(header) + "\n" + yaml.dump(body, Dumper=_IndentedDumper, sort_keys=False,
                                                     default_flow_style=False, allow_unicode=True)
    return {"team": team["team"], "allowed_models": [m["model"] for m in tiers], "format": "litellm",
            "rendered_config": rendered}


# --- Apply -------------------------------------------------------------------------
def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(config.REPO_ROOT))
    except ValueError:
        return str(path)


def apply(conn: sqlite3.Connection, team_name: str, allowed_models: list[str]) -> dict:
    """Write the rendered config to config.POLICY_OUT_DIR/<team id>.yaml (replacing that
    Team's previous file) and store a policies row. Returns the Policy body (minus source)."""
    r = render(team_name, allowed_models)
    if not r["allowed_models"]:
        raise PolicyError("choose at least one model: an empty LiteLLM allowlist allows every model")
    team = resolve_team(r["team"])
    out_dir = Path(config.POLICY_OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / output_filename(team)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(r["rendered_config"])
    os.replace(tmp, path)

    policy = {
        "policy_id": f"pol-{uuid.uuid4().hex[:10]}",
        "team": r["team"],
        "allowed_models": r["allowed_models"],
        "rendered_config": r["rendered_config"],
        "output_path": _display_path(path),
        "applied_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    conn.execute("INSERT INTO policies (policy_id, team, allowed_models_json, rendered_config, output_path, applied_at) "
                 "VALUES (?, ?, ?, ?, ?, ?)",
                 (policy["policy_id"], policy["team"], db.dumps(policy["allowed_models"]),
                  policy["rendered_config"], policy["output_path"], policy["applied_at"]))
    conn.commit()
    return policy


def list_policies(conn: sqlite3.Connection) -> dict:
    """PolicyList body (minus source), newest first."""
    rows = db.rows(conn, "SELECT policy_id, team, allowed_models_json, rendered_config, output_path, applied_at "
                         "FROM policies ORDER BY applied_at DESC, rowid DESC")
    return {"items": rows}


# --- For the Recommendation engine (09) --------------------------------------------
def prefill(target_id: str, suggested_models: list[str] | None) -> dict | None:
    """Recommendation.policy_prefill from a recommendations row (target_id + suggested_models).
    Uses the Team's display name, drops models the Infra Profile doesn't list, and returns
    None when there is no Team or no usable model (then the "Apply as Policy" link is hidden)."""
    if not suggested_models:
        return None
    try:
        team = resolve_team(target_id)
    except PolicyError:
        return None
    known = [m["model"] for m in model_tiers()]
    models = [m for m in known if m in set(suggested_models)]
    return {"team": team["team"], "allowed_models": models} if models else None
