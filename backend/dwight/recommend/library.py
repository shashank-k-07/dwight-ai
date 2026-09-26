"""Practice Library + Infra Profile lookups for the Recommendation engine (ticket 09).

Pure code, no GLM. Other tickets may reuse these:
  * practice(id) / practice_title(id)          (12: find the Practice a Draft attaches to)
  * infra_refs() / is_infra_ref(ref)           (every `ref` in the Infra Profile)
  * eligible_practices(fix)                    (the matching rule in practices.yaml's header)
  * policy_models()                            (14: the non-flagship models a Policy may allow)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from dwight import company

# Draftable Practices: the one Ticket 12 attaches a Draft to, per Recurring Discovery form.
DRAFT_PRACTICE = {"common_path": "consolidated-initiative-doc", "repeated_discovery": "initiative-memory-file"}
POLICY_PRACTICE = "team-model-allowlist-policy"


@dataclass(frozen=True)
class Practice:
    id: str
    title: str
    fixes: tuple[str, ...]
    description: str
    applies_when: str
    infra_requirements: tuple[str, ...]
    cites: tuple[str, ...] = field(default_factory=tuple)


@lru_cache(maxsize=1)
def _profile() -> dict:
    return company.infra_profile() or {}


@lru_cache(maxsize=1)
def library() -> dict[str, Practice]:
    raw = company.practices() or {}
    items = raw.get("practices", raw) if isinstance(raw, dict) else raw
    out: dict[str, Practice] = {}
    for p in items or []:
        out[p["id"]] = Practice(
            id=p["id"], title=p.get("title", p["id"]), fixes=tuple(p.get("fixes") or ()),
            description=" ".join(str(p.get("description", "")).split()),
            applies_when=" ".join(str(p.get("applies_when", "")).split()),
            infra_requirements=tuple(p.get("infra_requirements") or ()), cites=tuple(p.get("cites") or ()))
    return out


def practice(practice_id: str) -> Practice | None:
    return library().get(practice_id)


def practice_title(practice_id: str) -> str:
    p = practice(practice_id)
    return p.title if p else practice_id


def capabilities() -> set[str]:
    return set(_profile().get("capabilities") or [])


def meets_requirements(p: Practice) -> bool:
    return set(p.infra_requirements) <= capabilities()


def eligible_practices(fix: str) -> list[Practice]:
    """Practices whose `fixes` include `fix` (a Waste Pattern or Recurring Discovery form)
    and whose `infra_requirements` are all in the Infra Profile's `capabilities`."""
    return [p for p in library().values() if fix in p.fixes and meets_requirements(p)]


def _walk(node: Any, section: str, out: dict[str, str]) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("ref"), str):
            out[node["ref"]] = _describe(node, section)
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                _walk(v, section, out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, section, out)


def _describe(node: dict, section: str) -> str:
    bits = []
    for k, v in node.items():
        if k == "ref" or isinstance(v, (dict, list)) and k not in ("tools", "spaces", "context_file"):
            continue
        if isinstance(v, dict):
            v = ", ".join(f"{a}={b}" for a, b in v.items())
        elif isinstance(v, list):
            v = ", ".join(map(str, v))
        bits.append(f"{k}: {' '.join(str(v).split())}")
    return f"[{section}] " + "; ".join(bits)


@lru_cache(maxsize=1)
def infra_catalog() -> dict[str, str]:
    """Every Infra Profile `ref` -> a one-line description (what the model is shown)."""
    out: dict[str, str] = {}
    for section, node in _profile().items():
        if isinstance(node, (dict, list)):
            _walk(node, section, out)
    return out


def infra_refs() -> set[str]:
    return set(infra_catalog())


def is_infra_ref(ref: str) -> bool:
    return ref in infra_catalog()


def cited_refs(p: Practice) -> list[str]:
    """The real refs a Practice's `cites` point at (entries ending in ':' are prefixes)."""
    refs = sorted(infra_catalog())
    out: list[str] = []
    for c in p.cites:
        matches = [r for r in refs if r.startswith(c)] if c.endswith(":") else [r for r in refs if r == c]
        out.extend(m for m in matches if m not in out)
    return out


def agent_ref(agent_name: str | None) -> str | None:
    """Map a Session's `agent` (e.g. 'kestrel-devagent') to its Infra Profile ref, if any."""
    if not agent_name:
        return None
    ref = f"agent:{agent_name}"
    return ref if is_infra_ref(ref) else None


def agent_refs_for_business_function(business_function: str | None) -> list[str]:
    """Infra Profile agents whose `used_by` names this Business Function."""
    agents = (_profile().get("agents") or {}).get("list") or []
    return [a["ref"] for a in agents
            if business_function and business_function.lower() in str(a.get("used_by", "")).lower()]


def refs_for_resources(resource_ids: list[str]) -> list[str]:
    """Infra Profile refs named by Trail resource ids: repos ('repo:kestrel/identity/pkg/x.go'),
    the company-docs mirror and the Perch wiki."""
    out = []
    for r in sorted(infra_catalog()):
        if r.startswith("repo:") and any(rid == r or rid.startswith(r + "/") for rid in resource_ids):
            out.append(r)
    if any(rid.startswith("company-docs/") for rid in resource_ids):
        out.append("docs:company-docs")
    if any(rid.startswith("perch:") or "perch.kestrel.internal" in rid for rid in resource_ids):
        out.append("docs:perch")
    return [r for r in out if is_infra_ref(r)]


def tiers() -> list[dict]:
    return list((_profile().get("models") or {}).get("tiers") or [])


def policy_models() -> list[str]:
    """Models a Model Overkill Policy allows by default: every non-flagship tier in the
    Infra Profile, cheapest last (flagship stays available on request, per the Practice)."""
    return [t["model"] for t in tiers() if t.get("tier") != "flagship" and t.get("model")]
