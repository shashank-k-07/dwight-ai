"""Recommendation engine (build-spec §4.4, ticket 09).

For each Target (an Initiative, or a Team as a Policy candidate):
  1. code collects its WasteFindings by Waste Pattern and its RecurringDiscoveries,
     each with a dollar total (a Group);
  2. code narrows the Practice Library to Practices whose `fixes` match the Group and
     whose `infra_requirements` the Infra Profile meets;
  3. GLM picks Practices and writes each Recommendation (title, body, infra_refs) as JSON;
  4. code validates it (real, eligible practice_id; >= 1 real Infra Profile ref; no dollar
     figures) and rejects + retries bad output, then attaches `usd` and `kind` from the
     Group (ADRs 0006, 0007).

GLM is never shown a dollar figure: the prompt carries token counts, Session counts and
finding counts only, and any `$` amount in a finding's detail text is redacted first.
If GLM still fails after its retries, code writes a plain Recommendation from the
Practice's own text, so a target never silently loses its Recommendations.

This module does no DB writes: collect_* read the store, write_recommendations() is pure
given a Target (plus GLM), and the recommend stage stores the result.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel, Field

from dwight import db
from dwight.recommend import library as lib
from dwight.recommend.library import Practice

PATTERN_LABEL = {"redundant_read": "Redundant Read", "cache_miss": "Cache Miss",
                 "runaway_loop": "Runaway Loop", "model_overkill": "Model Overkill",
                 "common_path": "Recurring Discovery (common path)",
                 "repeated_discovery": "Recurring Discovery (repeated Discovery)"}

# Any currency amount ("$12", "12.5 USD", "USD 40", "3k dollars"). GLM output matching this is rejected.
MONEY_RE = re.compile(r"[$€£]\s*\d|\b\d[\d,.]*\s*(?:[km]\s*)?(?:usd|dollars?|cents?|eur|euros?)\b|\busd\s*\d",
                      re.IGNORECASE)
_REDACT_RE = re.compile(r"[$€£]\s*[\d,.]+\s*[kKmM]?|\b[\d,.]+\s*(?:usd|dollars?)\b", re.IGNORECASE)

MAX_ATTEMPTS = 3


# --- Targets and Groups -------------------------------------------------------------------
@dataclass
class Group:
    """One thing to fix within a Target: a Waste Pattern's findings or one RecurringDiscovery."""
    key: str                          # "cache_miss" | "rd:<recurring_discovery_id>"
    fix: str                          # the `fixes` value it matches: pattern or form
    usd: float                        # dollar total, from the store (never shown to GLM)
    kind: str                         # measured | estimated
    facts: list[str]                  # non-dollar evidence lines for the prompt
    candidates: list[Practice]
    recurring_discovery_id: str | None = None
    required: str | None = None       # practice_id that must be recommended for this Group


@dataclass
class Target:
    target_type: str                  # initiative | team
    target_id: str
    name: str
    context: list[str]
    groups: list[Group]
    hint_refs: list[str] = field(default_factory=list)   # refs named by the Target's own data
    spend_usd: float = 0.0            # for ordering only
    suggested_models: list[str] | None = None            # team targets: Policy prefill

    @property
    def min_recs(self) -> int:
        n = len(self.practice_ids())
        return min(1 if self.target_type == "team" else 2, n)

    @property
    def max_recs(self) -> int:
        # One per Group plus one alternative: Recommendations for the same Group share its
        # dollar figure, so more of them only repeats the same Waste.
        return min(max(self.min_recs, len(self.groups) + 1), len(self.practice_ids()))

    def practice_ids(self) -> set[str]:
        return {p.id for g in self.groups for p in g.candidates}

    def group(self, key: str) -> Group | None:
        return next((g for g in self.groups if g.key == key), None)


def _redact(text: str | None) -> str:
    return _REDACT_RE.sub("[amount]", text or "").strip()


def _pct(x: float) -> str:
    return f"{round(100 * x)}%"


def collect_initiatives(conn, initiative_ids: list[str] | None = None) -> list[Target]:
    """One Target per Initiative that has WasteFindings or RecurringDiscoveries."""
    inits = db.rows(conn, "SELECT * FROM initiatives ORDER BY spend_usd DESC")
    if initiative_ids:
        inits = [i for i in inits if i["initiative_id"] in initiative_ids]
    targets = []
    for ini in inits:
        iid = ini["initiative_id"]
        groups = _pattern_groups(conn, "s.initiative_id = ?", (iid,)) + _rd_groups(conn, iid)
        groups = [g for g in groups if g.candidates]
        if not groups:
            continue
        ctx, hints = _initiative_context(conn, ini)
        targets.append(Target("initiative", iid, ini["name"], ctx, groups, hints, ini["spend_usd"] or 0.0))
    return targets


def collect_teams(conn) -> list[Target]:
    """One Target per Team with Model Overkill findings: the Policy candidates."""
    teams = db.rows(conn, "SELECT s.team, s.business_function, SUM(w.usd) usd FROM waste_findings w "
                          "JOIN sessions s USING (session_id) WHERE w.pattern = 'model_overkill' "
                          "GROUP BY s.team, s.business_function ORDER BY usd DESC")
    targets = []
    for t in teams:
        groups = [g for g in _pattern_groups(conn, "s.team = ? AND w.pattern = 'model_overkill'", (t["team"],))
                  if g.candidates]
        if not groups:
            continue
        for g in groups:
            if any(p.id == lib.POLICY_PRACTICE for p in g.candidates):
                g.required = lib.POLICY_PRACTICE
        models = lib.policy_models()
        n_team = conn.execute("SELECT COUNT(*) FROM sessions WHERE team = ?", (t["team"],)).fetchone()[0]
        inis = [r["initiative_id"] for r in db.rows(
            conn, "SELECT s.initiative_id, COUNT(*) n FROM waste_findings w JOIN sessions s USING (session_id) "
                  "WHERE s.team = ? AND w.pattern = 'model_overkill' AND s.initiative_id IS NOT NULL "
                  "GROUP BY s.initiative_id ORDER BY n DESC LIMIT 5", (t["team"],))]
        ctx = [f"Team: {t['team']} (Business Function: {t['business_function']}), {n_team} Sessions observed.",
               f"Initiatives where its Model Overkill happened: {', '.join(inis) or 'unknown'}.",
               "Infra Profile model tiers: " + "; ".join(
                   f"{x.get('tier')} = {x.get('model')} (alias {x.get('gateway_alias')}, for {x.get('intended_for')})"
                   for x in lib.tiers()),
               f"Models a Policy for this Team would allow (computed by Dwight): {', '.join(models)}; "
               "flagship on request."]
        targets.append(Target("team", t["team"], t["team"], ctx, groups,
                              ["gateway:kestrel-llm-gateway"] if lib.is_infra_ref("gateway:kestrel-llm-gateway") else [],
                              t["usd"] or 0.0, suggested_models=models))
    return targets


def _pattern_groups(conn, where: str, params: tuple) -> list[Group]:
    rows = db.rows(conn, f"SELECT w.pattern, w.kind, COUNT(*) n, COUNT(DISTINCT w.session_id) sessions, "
                         f"SUM(w.usd) usd FROM waste_findings w JOIN sessions s USING (session_id) "
                         f"WHERE {where} GROUP BY w.pattern, w.kind ORDER BY usd DESC", params)
    groups = []
    for r in rows:
        details = [d["detail"] for d in db.rows(
            conn, f"SELECT DISTINCT w.detail FROM waste_findings w JOIN sessions s USING (session_id) "
                  f"WHERE {where} AND w.pattern = ? AND w.detail IS NOT NULL LIMIT 4", params + (r["pattern"],))]
        facts = [f"{r['n']} {PATTERN_LABEL[r['pattern']]} findings across {r['sessions']} Sessions "
                 f"({'Measured Waste' if r['kind'] == 'measured' else 'Estimated Saving'})."]
        facts += [f"Detector note: {_redact(d)}" for d in details if _redact(d)]
        if r["pattern"] == "model_overkill":
            mods = db.rows(conn, f"SELECT c.model, s.complexity, COUNT(DISTINCT s.session_id) n FROM waste_findings w "
                                 f"JOIN sessions s USING (session_id) JOIN calls c ON c.session_id = s.session_id "
                                 f"WHERE {where} AND w.pattern = 'model_overkill' GROUP BY c.model, s.complexity",
                           params)
            facts += [f"{m['n']} flagged Sessions ran {m['model']} with complexity {m['complexity']}." for m in mods]
        key = r["pattern"] if r["kind"] == ("estimated" if r["pattern"] == "model_overkill" else "measured") \
            else f"{r['pattern']}:{r['kind']}"
        groups.append(Group(key, r["pattern"], r["usd"] or 0.0, r["kind"], facts, lib.eligible_practices(r["pattern"])))
    return groups


def _rd_groups(conn, initiative_id: str) -> list[Group]:
    groups = []
    for rd in db.rows(conn, "SELECT * FROM recurring_discoveries WHERE initiative_id = ? ORDER BY spend_usd DESC",
                      (initiative_id,)):
        n, frac = rd["session_count"], rd["session_share"] or 0
        base = round(n / frac) if frac else None
        share = (f"{n} of the {base} Sessions analysed ({_pct(frac)})" if base else f"{n} Sessions")
        if rd["form"] == "common_path":
            res = rd.get("resource_ids") or []
            facts = [f"Common path: {share} read the same {len(res)} resources to get started, "
                     f"about {rd.get('tokens') or 'unknown'} tokens per Session.",
                     "Resources: " + ", ".join(res)]
        else:
            facts = [f"Repeated Discovery: {share} each worked out separately: \"{_redact(rd.get('statement'))}\""]
        form = rd["form"]
        cands = lib.eligible_practices(form)
        req = lib.DRAFT_PRACTICE[form] if any(p.id == lib.DRAFT_PRACTICE[form] for p in cands) else None
        # Until the Drafter (12) re-prices it, a Recurring Discovery's Recommendation carries the
        # repetition's measured cost as its Estimated Saving (build-spec §4.6.4: stays Estimated).
        groups.append(Group(f"rd:{rd['recurring_discovery_id']}", form, rd["spend_usd"] or 0.0, "estimated",
                            facts, cands, rd["recurring_discovery_id"], req))
    return groups


def _initiative_context(conn, ini: dict) -> tuple[list[str], list[str]]:
    iid = ini["initiative_id"]
    n = conn.execute("SELECT COUNT(*) FROM sessions WHERE initiative_id = ?", (iid,)).fetchone()[0]
    teams = db.rows(conn, "SELECT team, COUNT(*) n FROM sessions WHERE initiative_id = ? GROUP BY team "
                          "ORDER BY n DESC LIMIT 4", (iid,))
    agents = db.rows(conn, "SELECT agent, COUNT(*) n FROM sessions WHERE initiative_id = ? GROUP BY agent "
                           "ORDER BY n DESC LIMIT 3", (iid,))
    trail = db.rows(conn, "SELECT t.resource_id, COUNT(DISTINCT t.session_id) n, CAST(AVG(t.tokens) AS INT) tok "
                          "FROM trail_entries t JOIN sessions s USING (session_id) WHERE s.initiative_id = ? "
                          "GROUP BY t.resource_id ORDER BY n DESC, tok DESC LIMIT 8", (iid,))
    summaries = [r["summary"] for r in db.rows(
        conn, "SELECT DISTINCT summary FROM sessions WHERE initiative_id = ? AND summary IS NOT NULL LIMIT 5", (iid,))]
    ctx = [f"Initiative: {ini['name']} (id {iid}, Business Function {ini.get('business_function') or 'unknown'}), "
           f"{n} Sessions.",
           f"Description: {ini.get('description') or 'none'}",
           "Teams: " + ", ".join(f"{t['team']} ({t['n']})" for t in teams),
           "Agents: " + ", ".join(f"{a['agent']} ({a['n']} Sessions)" for a in agents)]
    if trail:
        ctx.append("Most-read resources: " + "; ".join(f"{t['resource_id']} ({t['n']} Sessions, ~{t['tok']} tokens)"
                                                       for t in trail))
    if summaries:
        ctx.append("Session summaries: " + " | ".join(summaries))
    hints = [r for r in (lib.agent_ref(a["agent"]) for a in agents) if r]
    hints = hints or lib.agent_refs_for_business_function(ini.get("business_function"))
    hints += lib.refs_for_resources([t["resource_id"] for t in trail])
    return ctx, hints


# --- GLM ----------------------------------------------------------------------------------
class RecOut(BaseModel):
    addresses: str = Field(description="The `key` of the Group this Recommendation fixes")
    practice_id: str = Field(description="One of that Group's candidate Practice ids")
    title: str = Field(description="Imperative, specific, at most 90 characters")
    body: str = Field(description="Markdown, 2-4 sentences. No dollar figures.")
    infra_refs: list[str] = Field(description="1-4 Infra Profile refs, copied exactly from the catalog")


class EngineOut(BaseModel):
    recommendations: list[RecOut]


SYSTEM = """You are Dwight's Recommendation writer. Dwight shows an enterprise (the Customer) what its AI Agents spend money on and recommends how to spend less.

You get one target (an Initiative or a Team), the Groups of Waste found for it (each with a `key` and candidate Practices from Dwight's curated Practice Library), and a catalog of the Customer's Infra Profile refs.

Write Recommendations. Rules:
- Each Recommendation fixes exactly one Group (`addresses` = that Group's key) and applies exactly one of THAT Group's candidate Practices (`practice_id`). Never use a Practice that is not listed for the Group. Use each practice_id at most once.
- Cover every Group. When a Group lists a REQUIRED practice, you must include a Recommendation with it for that Group.
- `infra_refs`: 1-4 refs copied exactly from the Infra Profile catalog (e.g. "mcp:perch-docs-mcp"). Prefer refs the Practice cites and refs this target's Sessions actually use. Never invent refs, repos, servers or tools.
- `title`: a concrete action, at most 90 characters.
- `body`: markdown, 2-4 sentences. Say what the Sessions showed (use the token counts, Session counts and finding counts you are given) and exactly what to change in the named infra (config repo, gateway alias, MCP server, memory file path...). Tailor it to this target; don't restate the Practice's generic description.
- NEVER write dollar figures, prices, costs in currency, or savings amounts. Dwight computes every dollar figure in code and attaches it separately.
- Use Dwight's vocabulary: Session, Agent, Initiative, Team, Waste, Waste Pattern, Practice, Draft, Policy, Recurring Discovery.
"""


def build_messages(target: Target) -> list[dict]:
    catalog = lib.infra_catalog()
    lines = [f"TARGET ({target.target_type}):", *[f"- {c}" for c in target.context], ""]
    if target.hint_refs:
        lines += ["Infra Profile refs that match this target's Sessions (agents, repos, docs read) or its "
                  "Business Function: " + ", ".join(target.hint_refs), ""]
    lines.append(f"GROUPS (write between {target.min_recs} and {target.max_recs} Recommendations in total):")
    for g in target.groups:
        lines.append(f"\n## key: {g.key}  ({PATTERN_LABEL.get(g.fix, g.fix)})")
        lines += [f"- {f}" for f in g.facts]
        if g.required:
            lines.append(f"- REQUIRED practice for this Group: {g.required}")
        lines.append("- Candidate Practices:")
        for p in g.candidates:
            cites = ", ".join(lib.cited_refs(p)) or "none"
            lines.append(f"  - {p.id}: {p.title}. {p.description} Applies when: {p.applies_when} Cites: {cites}")
    lines += ["", "INFRA PROFILE CATALOG (ref: description):"]
    lines += [f"- {ref}: {desc}" for ref, desc in sorted(catalog.items())]
    if target.target_type == "team":
        lines += ["", "This is a Policy candidate: the Admin can limit this Team's model access at the gateway. "
                      "The team-model-allowlist-policy Recommendation should name the allowed models listed above."]
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(lines)}]


def rec_errors(target: Target, r: RecOut, seen: set[str]) -> list[str]:
    errs = []
    g = target.group(r.addresses)
    if g is None:
        errs.append(f"addresses {r.addresses!r} is not a Group key")
    elif r.practice_id not in {p.id for p in g.candidates}:
        errs.append(f"practice_id {r.practice_id!r} is not a candidate for Group {g.key!r}")
    if r.practice_id in seen:
        errs.append(f"practice_id {r.practice_id!r} used twice")
    real = [x for x in r.infra_refs if lib.is_infra_ref(x)]
    bad = [x for x in r.infra_refs if not lib.is_infra_ref(x)]
    if bad:
        errs.append(f"infra_refs {bad} are not refs in the Infra Profile catalog")
    if not real:
        errs.append("needs at least one real infra_ref")
    if not r.title.strip() or not r.body.strip():
        errs.append("title and body must be non-empty")
    if MONEY_RE.search(r.title) or MONEY_RE.search(r.body):
        errs.append("contains a dollar figure or currency; Dwight adds all dollar figures itself, remove them")
    return errs


def validate(target: Target, out: EngineOut) -> tuple[list[RecOut], list[str]]:
    """(valid Recommendations, errors). Errors cover each bad Recommendation plus
    target-level rules (count, required practices, every Group covered)."""
    valid, errors, seen = [], [], set()
    for i, r in enumerate(out.recommendations):
        errs = rec_errors(target, r, seen)
        if errs:
            errors.append(f"recommendations[{i}] ({r.practice_id}): " + "; ".join(errs))
        else:
            valid.append(r)
            seen.add(r.practice_id)
    errors += _coverage_errors(target, valid)
    return valid, errors


def _coverage_errors(target: Target, recs: list[RecOut]) -> list[str]:
    errs = []
    covered = {r.addresses for r in recs}
    picked = {(r.addresses, r.practice_id) for r in recs}
    for g in target.groups:
        if g.required and (g.key, g.required) not in picked:
            errs.append(f"Group {g.key!r} needs a Recommendation with the REQUIRED practice {g.required!r}")
        elif g.key not in covered:
            errs.append(f"Group {g.key!r} has no Recommendation")
    if len(recs) < target.min_recs:
        errs.append(f"need at least {target.min_recs} valid Recommendations, got {len(recs)}")
    if len(recs) > target.max_recs:
        errs.append(f"at most {target.max_recs} Recommendations, got {len(recs)}")
    return errs


def fallback_refs(target: Target, p: Practice) -> list[str]:
    """Refs for a fallback: the Practice's cited refs this target's data names, else its
    exact (non-prefix) cites. [] means the Practice can't be tailored to this target."""
    cited = lib.cited_refs(p)
    hinted = [r for r in target.hint_refs if r in cited]
    return hinted or [c for c in p.cites if not c.endswith(":") and lib.is_infra_ref(c)][:2]


def fallback_rec(target: Target, g: Group, p: Practice) -> RecOut:
    """Plain Recommendation from the Practice's own text, used only when GLM output
    could not be validated. Still cites real refs and carries no dollar figure."""
    fact = g.facts[0] if g.facts else ""
    return RecOut(addresses=g.key, practice_id=p.id, title=f"{p.title} for {target.name}"[:90],
                  body=f"{fact} {p.description}".strip(), infra_refs=fallback_refs(target, p))


def _complete(target: Target, recs: list[RecOut]) -> tuple[list[RecOut], int]:
    """Fill what GLM left missing (required practices, uncovered Groups, the minimum
    count) with fallback Recommendations. Returns (recs, number of fallbacks)."""
    recs = list(recs)[: target.max_recs]
    used = {r.practice_id for r in recs}
    n = 0

    def add(g: Group, p: Practice) -> None:
        nonlocal n
        recs.append(fallback_rec(target, g, p))
        used.add(p.id)
        n += 1

    for g in target.groups:
        picked = {r.practice_id for r in recs if r.addresses == g.key}
        if g.required and g.required not in picked and g.required not in used:
            add(g, lib.practice(g.required))
        elif not picked:
            p = next((p for p in g.candidates if p.id not in used and fallback_refs(target, p)), None)
            if p:
                add(g, p)
    for g in sorted(target.groups, key=lambda g: -g.usd):
        while len(recs) < target.min_recs:
            p = next((p for p in g.candidates if p.id not in used and fallback_refs(target, p)), None)
            if p is None:
                break
            add(g, p)
    return recs, n


ChatJson = Callable[..., EngineOut]


def write_recommendations(target: Target, *, chat_json: ChatJson | None, tier: str | None = None
                          ) -> tuple[list[dict], dict]:
    """GLM picks and writes, code validates (reject + retry), code prices.
    `chat_json=None` skips GLM (fallback text only). Returns (rows, stats)."""
    stats = {"attempts": 0, "rejected": 0, "fallbacks": 0, "error": None}
    recs: list[RecOut] = []
    if chat_json is not None:
        msgs = build_messages(target)
        best: list[RecOut] = []
        for _ in range(MAX_ATTEMPTS):
            stats["attempts"] += 1
            try:
                out = chat_json(msgs, schema=EngineOut, tier=tier)
            except Exception as e:  # noqa: BLE001  (bad JSON after retries, API errors)
                from dwight.glm import GLMNotConfigured
                if isinstance(e, GLMNotConfigured):
                    raise
                stats["error"] = f"{type(e).__name__}: {e}"
                continue
            valid, errors = validate(target, out)
            if len(valid) > len(best) or not errors:
                best = valid
            if not errors:
                break
            stats["rejected"] += 1
            msgs = msgs + [{"role": "assistant", "content": out.model_dump_json()},
                           {"role": "user", "content": "Rejected. Fix these problems and reply with the full JSON "
                                                        "again:\n- " + "\n- ".join(errors)}]
        recs = best
    recs, stats["fallbacks"] = _complete(target, recs)
    return [_price(target, r) for r in recs], stats


def _price(target: Target, r: RecOut) -> dict:
    """Code attaches usd + kind from the Group's findings. Never from GLM output."""
    g = target.group(r.addresses)
    refs = list(dict.fromkeys(x for x in r.infra_refs if lib.is_infra_ref(x)))
    policy = target.target_type == "team" and r.practice_id == lib.POLICY_PRACTICE
    return {
        "target_type": "policy" if policy else target.target_type,
        "target_id": target.target_id,
        "practice_id": r.practice_id,
        "title": r.title.strip(),
        "body": r.body.strip(),
        "infra_refs": refs,
        "usd": round(g.usd, 8),
        "kind": g.kind,
        "recurring_discovery_id": g.recurring_discovery_id,
        "suggested_models": target.suggested_models if policy else None,
        "addresses": g.key,
    }


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def recommendation_id(row: dict) -> str:
    """Stable across reruns, so a Draft's recommendation_id (12) survives a re-run."""
    return f"r-{slug(row['target_id'])}-{row['practice_id']}"
