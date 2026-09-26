"""Compose synthetic Sessions from the content library, deterministically from a seed.

No model calls happen here: `content.py` wrote the text once; this module picks
from it with `random.Random(seed)` and simulates token accounting, caching and
the planted Waste Patterns. Output:

  data/otlp/synthetic/day-YYYY-MM-DD.jsonl   one OTLP JSON payload per line (one Session each),
                                             ingested by `python -m dwight.pipeline run ingest`
  data/ground-truth/synthetic_sessions.jsonl true Initiative, complexity, planted Waste Patterns
                                             and Discoveries per Session (classifier never reads it)
  data/ground-truth/synthetic_summary.json   counts, for humans and later tickets

Telemetry shape (docs/dev.md "Emitting telemetry"), via dwight.ingest.builder:
  * resource: dwight.business_function / dwight.team (org.yaml display names),
    dwight.member.id, dwight.dataset=synthetic, service.name = the Agent
  * one model per Session, from the fictional company's tiers (glm-5.1 / glm-4.7 /
    glm-4.5-air), NOT the Sciforium model that wrote the content
  * read tools and the Trail resource_id they map to (for the classifier, 06):
        read_doc        {"doc_id": "storage-tiering-policy"}               -> company-docs/storage-tiering-policy.md
        perch.get_page  {"page_id": "perch:ENG/oidc-migration-plan"}       -> perch:ENG/oidc-migration-plan
        code.read_file  {"path": "repo:kestrel/identity/pkg/x.go"}         -> repo:kestrel/identity/pkg/x.go
    (ids are passed already namespaced, so dwight.classifier.trail keeps them as is)
    dwight.tool.result_tokens is the full read size (org.yaml `tokens`), while the
    result text is an excerpt, to keep the files small.

Planted Waste Patterns (what the detectors, 05, see):
  redundant_read  a resource already read in the Session is read again later (same
                  args, same result text -> same result_hash), never on consecutive Calls
  cache_miss      same prompt_prefix_hash on every Call, but cache_read_tokens = 0 on
                  most Calls after the first (system prompt header has a timestamp)
  runaway_loop    the same failing tool step (same args, same result) on 5-9
                  consecutive Calls, one tool per Call. NOTE: its repeated results
                  also repeat a result_hash, which is what the fixture fx-rl-01 does too
  model_overkill  complexity=low Session on glm-5.1 (Estimated; needs 06's complexity)
Every other tool result in a Session is made unique, so clean Sessions have no
duplicate result_hash, and caching serves the previous Call's input.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dwight import company, pricing
from dwight.ingest.builder import SessionBuilder
from dwight.synth import params as P
from dwight.synth.content import STORAGE_BUCKETS

SYSTEM_PROMPTS = {
    "kestrel-devagent": (
        "You are kestrel-devagent, Kestrel Logistics' internal coding agent. You work in the Member's checkout "
        "of a kestrel/* repository. Read the relevant Perch pages and code before changing anything, run the "
        "tests, keep changes small and explain what you did. Tools: perch.get_page, perch.search, code.read_file, "
        "code.search, read_doc, run_command, write_file, incidents.get, finops.query_cost."),
    "ops-copilot": (
        "You are ops-copilot, the operations assistant for Kestrel Logistics. You help Fleet and Warehouse "
        "Operations with runbooks, shipment lookups and carrier communication. Follow the Perch OPS runbooks; "
        "never promise customers dates the TMS does not show. Tools: perch.get_page, perch.search, "
        "tms.get_shipment, tms.update_eta, carrier.send_message, sheets.read_range, write_file."),
    "desk-agent": (
        "You are desk-agent, Kestrel Logistics' document and spreadsheet agent for Finance, Marketing and "
        "Customer Experience. Ground every answer in the Perch pages and systems you can read, cite them, and "
        "draft outputs as files for the Member to review. Tools: perch.get_page, perch.search, sheets.read_range, "
        "netsuite.query, zendesk.get_macro, zendesk.update_macro, write_file."),
}
TRANSITIONS = ["Checking {r} next.", "Let me look at {r}.", "Reading {r} for context.", "Now {r}."]
WORK_TEXT = ["Running that now.", "Next step.", "Applying the change.", "Checking the result.", ""]
GIVE_UP = ("I could not get past this: the same step keeps failing with the same error, so I'm stopping here. "
           "Someone should look at it before we retry.")


# --- small helpers -----------------------------------------------------------------------
def _rng(*parts: Any) -> random.Random:
    return random.Random(":".join(map(str, parts)))


def _between(rng: random.Random, r: list) -> int:
    return rng.randint(int(r[0]), int(r[1]))


def _pick_weighted(rng: random.Random, mix: dict[str, float]) -> str:
    keys = list(mix)
    return rng.choices(keys, weights=[mix[k] for k in keys])[0]


def _tokens_of(text: str) -> int:
    return max(1, len(text) // 4)


def read_step(resource_id: str) -> tuple[str, dict]:
    """The read tool + args that produce `resource_id` in a Trail (see module docstring)."""
    if resource_id.startswith("company-docs/"):
        return "read_doc", {"doc_id": resource_id.removeprefix("company-docs/").removesuffix(".md")}
    if resource_id.startswith("perch:"):
        return "perch.get_page", {"page_id": resource_id}
    if resource_id.startswith("repo:"):
        return "code.read_file", {"path": resource_id}
    return "read_doc", {"doc_id": resource_id}


def _fill(obj: Any, subs: dict[str, str]) -> Any:
    if isinstance(obj, str):
        for k, v in subs.items():
            obj = obj.replace("{" + k + "}", v)
        return obj
    if isinstance(obj, dict):
        return {k: _fill(v, subs) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fill(v, subs) for v in obj]
    return obj


class World:
    """Everything the generator needs that doesn't depend on the Session sample."""

    def __init__(self, params: dict, library: dict, org: dict):
        self.params, self.org = params, org
        self.lib = library["initiatives"]
        self.seed = params["seed"]
        self.bf_name = {b["id"]: b["name"] for b in org["business_functions"]}
        self.team_name = {t["id"]: t["name"] for t in org["teams"]}
        self.team_bf = {t["id"]: self.bf_name[t["business_function"]] for t in org["teams"]}
        self.inis = [i for i in org["initiatives"] if i["id"] in self.lib and self.lib[i["id"]]["tasks"]]
        missing = [i["id"] for i in org["initiatives"] if i not in self.inis]
        if missing:
            raise ValueError(f"content library is missing Initiatives {missing}; run `python -m dwight.synth content`")
        mrng = _rng(self.seed, "members")
        self.members: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for m in org["members"]:
            self.members[m["team"]].append((m["id"], math.exp(mrng.gauss(0, params["member_activity_sigma"]))))
        # Usual resources: fixed size and fixed read probability per resource.
        self.usual: dict[str, list[dict]] = {}
        for ini in self.inis:
            rows = []
            for r in ini["usual_resources"]:
                tokens = r["tokens"]
                if tokens == "real":
                    tokens = _tokens_of(company.company_doc_path(r["id"]).read_text())
                lo, hi = params["usual_read_prob"]
                prob = _rng(self.seed, "usual", r["id"]).uniform(lo, hi)
                rows.append({"id": r["id"], "tokens": int(tokens), "prob": prob,
                             "text": self.lib[ini["id"]]["resources"].get(r["id"]) or f"# {r['id']}\n"})
            self.usual[ini["id"]] = rows

    def extra_tokens(self, rid: str) -> int:
        return _between(_rng(self.seed, "extra", rid), self.params["shapes"]["result_tokens"]["extra_resource"])


# --- one Session ----------------------------------------------------------------------------
def _plan_session(w: World, rng: random.Random, ini: dict) -> dict:
    p = w.params
    lib = w.lib[ini["id"]]
    bf = w.bf_name[ini["business_function"]]
    # Team: first primary Team gets primary_team_share, the rest split the remainder.
    teams = ini["primary_teams"]
    share = p["primary_team_share"] if len(teams) > 1 else 1.0
    tw = [share] + [(1 - share) / (len(teams) - 1)] * (len(teams) - 1) if len(teams) > 1 else [1.0]
    team_id = rng.choices(teams, weights=tw)[0]
    mem = w.members[team_id]
    member = rng.choices([m for m, _ in mem], weights=[a for _, a in mem])[0]
    agent = p["agents"]["by_business_function"][bf]
    team = w.team_name[team_id]
    model = _pick_weighted(rng, p["model_mix"]["teams"].get(team) or p["model_mix"]["default"])
    cmix = p["complexity_mix"].get(bf) or p["complexity_mix"]["default"]
    complexity = _pick_weighted(rng, cmix)
    pool = [t for t in lib["tasks"] if t["complexity"] == complexity] or lib["tasks"]
    task_idx = lib["tasks"].index(rng.choice(pool))
    complexity = lib["tasks"][task_idx]["complexity"]

    def rate(name: str) -> float:
        r = p["waste_rates"][name]
        return r.get("agents", {}).get(agent, r["default"])

    patterns = set()
    if rng.random() < rate("redundant_read"):
        patterns.add("redundant_read")
    if rng.random() < rate("cache_miss"):
        patterns.add("cache_miss")
    rl = p["waste_rates"]["runaway_loop"]
    if complexity in rl["eligible_complexity"] and lib["failing_steps"]:
        eligible = sum(cmix.get(c, 0) for c in rl["eligible_complexity"]) or 1
        if rng.random() < rate("runaway_loop") / eligible:
            patterns.add("runaway_loop")
    # Repeated Discoveries at their org.yaml strength (share of the Initiative's Sessions).
    dcfg = p["discoveries"]
    eligible = sum(cmix.get(c, 0) for c in dcfg["eligible_complexity"]) or 1
    planted: list[tuple[str, dict]] = []
    for script, spec in zip(lib["discoveries"], ini["repeated_discoveries"]):
        if complexity in dcfg["eligible_complexity"] and rng.random() < min(1.0, spec["strength"] / eligible):
            planted.append(("repeated", script))
    if lib["one_offs"] and complexity in dcfg["eligible_complexity"] and rng.random() < dcfg["one_off_prob"]:
        planted.append(("one_off", rng.choice(lib["one_offs"])))
    return {"initiative": ini, "bf": bf, "team": team, "member": member, "agent": agent, "model": model,
            "complexity": complexity, "task_idx": task_idx, "patterns": patterns, "planted": planted}


def _compose_steps(w: World, rng: random.Random, s: dict) -> list[dict]:
    """The ordered tool steps of a Session. Each step: {tool, args, result, tokens, solo, kind, ...}."""
    p = w.params
    ini = s["initiative"]
    lib = w.lib[ini["id"]]
    shape = p["shapes"][s["complexity"]]
    rt = p["shapes"]["result_tokens"]

    def read(rid: str, text: str, tokens: int, kind: str = "read") -> dict:
        tool, args = read_step(rid)
        return {"tool": tool, "args": args, "result": text, "tokens": tokens, "kind": kind, "resource_id": rid}

    reads = [read(u["id"], u["text"], u["tokens"], "usual_read") for u in w.usual[ini["id"]]
             if rng.random() < u["prob"] * shape["usual_read_factor"]]
    for i in range(len(reads) - 1):  # light reordering: Members start from different docs
        if rng.random() < 0.25:
            reads[i], reads[i + 1] = reads[i + 1], reads[i]
    extras = rng.sample(lib["extra"], min(len(lib["extra"]), _between(rng, shape["extra_reads"])))
    extra_steps = [read(e["resource_id"], e["excerpt"], w.extra_tokens(e["resource_id"])) for e in extras]
    if rng.random() < p["cross_read_prob"]:
        others = [o for o in w.inis if o["business_function"] == ini["business_function"] and o["id"] != ini["id"]]
        if others:
            u = rng.choice(w.usual[rng.choice(others)["id"]])
            extra_steps.append(read(u["id"], u["text"], u["tokens"], "cross_read"))
    n_early = len(extra_steps) // 2
    head = reads + extra_steps[:n_early]

    def work(step: dict, kind: str = "work") -> dict:
        tool = step["tool"]
        if tool == "write_file":
            tokens = _between(rng, rt["write"])
        elif "search" in tool:
            tokens = max(_tokens_of(step["result"]), _between(rng, rt["search"]))
        else:
            tokens = max(_tokens_of(step["result"]), min(_between(rng, rt["command"]), 4 * _tokens_of(step["result"])))
        return {"tool": tool, "args": step["args"], "result": step["result"], "tokens": tokens, "kind": kind}

    k = _between(rng, shape["work_steps"])
    pool = lib["work_steps"]
    # Past the pool size, steps repeat (a re-run test, a second write); _uniquify keeps their results distinct.
    chosen = rng.sample(pool, min(k, len(pool))) + rng.choices(pool, k=max(0, k - len(pool)))
    body = [work(st) for st in chosen] + extra_steps[n_early:]
    rng.shuffle(body)
    # Discovery scripts: failed attempt, then the fix on the next Call.
    bucket = rng.choice(STORAGE_BUCKETS)
    subs = {"bucket": bucket, "rule": f"tidewater-{bucket}-v{rng.randint(1, 3)}"}
    for kind, script in s["planted"]:
        script = _fill(script, subs)
        pos = rng.randint(0, len(body))
        fail = {**work(script["failed_step"], "discovery_fail"), "solo": True}
        fix = {**work(script["fixed_step"], "discovery_fix"), "solo": True, "note": script["note"],
               "statement": script["statement"], "discovery_kind": kind}
        body[pos:pos] = [fail, fix]
    s["gave_up"] = False
    if "runaway_loop" in s["patterns"]:
        failing = work(rng.choice(lib["failing_steps"]), "loop")
        n = _between(rng, p["waste_rates"]["runaway_loop"]["repeats"])
        pos = _safe_insert_pos(rng, body)
        body[pos:pos] = [{**failing, "solo": True, "loop": True} for _ in range(n)]
        if rng.random() < 0.5:  # the Agent gives up after the loop
            body = body[:pos + n]
            s["gave_up"] = True
    steps = head + body
    if "redundant_read" in s["patterns"]:
        earlier = [i for i, st in enumerate(steps) if st["kind"] in ("usual_read", "read", "cross_read")]
        rereads = rng.sample(earlier, min(len(earlier), _between(rng, p["waste_rates"]["redundant_read"]["rereads"])))
        for i in sorted(rereads, reverse=True):
            src = steps[i]
            # insert at least 2 steps later, and not inside a loop or a discovery pair
            candidates = [j for j in range(i + 2, len(steps) + 1) if _gap_ok(steps, j)]
            if not candidates:
                continue
            j = rng.choice(candidates)
            steps.insert(j, {**src, "kind": "reread", "solo": True})
        if not any(st["kind"] == "reread" for st in steps):
            s["patterns"].discard("redundant_read")
    return steps


def _gap_ok(steps: list[dict], j: int) -> bool:
    """True if inserting at j doesn't split a loop or a discovery fail/fix pair."""
    if 0 < j < len(steps):
        a, b = steps[j - 1], steps[j]
        if a.get("loop") and b.get("loop"):
            return False
        if a["kind"] == "discovery_fail" and b["kind"] == "discovery_fix":
            return False
    return True


def _safe_insert_pos(rng: random.Random, body: list[dict]) -> int:
    return rng.choice([j for j in range(len(body) + 1) if _gap_ok(body, j)])


def _uniquify(steps: list[dict], rng: random.Random) -> None:
    """Make every tool result unique within the Session unless it is a planted repeat."""
    seen: set[str] = set()
    for st in steps:
        h = hashlib.sha256(json.dumps(st["result"], sort_keys=True).encode()).hexdigest()
        intended = st["kind"] == "reread" or st.get("loop")
        base = st["result"]
        while h in seen and not intended:
            st["result"] = f"{base}\n(completed in {rng.uniform(0.4, 9.0):.2f}s)"
            h = hashlib.sha256(json.dumps(st["result"], sort_keys=True).encode()).hexdigest()
        seen.add(h)


def _group_calls(steps: list[dict], rng: random.Random, p2: float) -> list[list[dict]]:
    calls, i = [], 0
    while i < len(steps):
        a = steps[i]
        if (i + 1 < len(steps) and not a.get("solo") and not steps[i + 1].get("solo")
                and a["kind"] != "reread" and rng.random() < p2):
            calls.append([a, steps[i + 1]])
            i += 2
        else:
            calls.append([a])
            i += 1
    return calls


def build_session(w: World, sid: str, start: datetime, plan: dict, rng: random.Random) -> tuple[dict, dict]:
    """-> (OTLP payload, ground-truth row)."""
    p = w.params
    ini, lib = plan["initiative"], w.lib[plan["initiative"]["id"]]
    task = lib["tasks"][plan["task_idx"]]
    steps = _compose_steps(w, rng, plan)
    _uniquify(steps, rng)
    shape = p["shapes"][plan["complexity"]]
    calls = _group_calls(steps, rng, shape["tools_per_call_2_prob"])
    agent, model = plan["agent"], plan["model"]
    cm = "cache_miss" in plan["patterns"]
    prefix_tokens = int(p["agents"]["prefix_tokens"][agent])
    system = SYSTEM_PROMPTS[agent]
    if cm:  # older agent-config: volatile header at the top of the system prompt
        system = (f"Current time: {start.isoformat().replace('+00:00', 'Z')}\n"
                  f"git status: {rng.randint(1, 14)} files changed on branch {plan['member']}/wip\n\n" + system)
    prefix_hash = f"{agent}/sys-v13-header" if cm else f"{agent}/sys-v14"
    b = SessionBuilder(sid, member_id=plan["member"], team=plan["team"], business_function=plan["bf"],
                       agent=agent, dataset="synthetic", start_ns=int(start.timestamp() * 1e9),
                       call_gap_ns=_between(rng, p["shapes"]["call_gap_seconds"]) * 1_000_000_000)
    ot = p["shapes"]["output_tokens"]
    block = int(p["caching"]["block"])
    ctx = prefix_tokens + _tokens_of(task["prompt"]) + int(p["shapes"]["user_prompt_overhead_tokens"])
    prev_input = 0
    new_msgs: list[dict] = [{"role": "user", "parts": [{"type": "text", "content": task["prompt"]}]}]
    pending_note: str | None = None
    discoveries_gt, seq_patterns, missed = [], [], []
    n_calls = len(calls) + 1
    for i in range(n_calls):
        tools = calls[i] if i < len(calls) else []
        text = ""
        if i == 0:
            text = task["plan"]
        elif pending_note:
            text, pending_note = pending_note, None
        elif tools and tools[0]["kind"] in ("usual_read", "read", "cross_read") and rng.random() < 0.35:
            text = rng.choice(TRANSITIONS).format(r=tools[0]["resource_id"].split("/")[-1])
        elif tools and rng.random() < 0.2:
            text = rng.choice(WORK_TEXT)
        if not tools:  # closing answer
            text = (text + "\n\n" if text else "") + (GIVE_UP if plan["gave_up"] else task["summary"])
            out_tokens = _between(rng, ot["final"])
        elif any(t["tool"] == "write_file" for t in tools):
            out_tokens = _between(rng, ot["write"])
        else:
            out_tokens = _between(rng, ot["tool_call"])
        parts: list[dict] = [{"type": "text", "content": text}] if text else []
        parts += [{"type": "tool_call", "id": f"{sid}-tc{i}-{j}", "name": t["tool"], "arguments": t["args"]}
                  for j, t in enumerate(tools)]
        caching = p["caching"]["enabled"] and i > 0
        # A Cache Miss Session always misses on Call 1, then on miss_prob_per_call of the rest.
        if caching and cm and (i == 1 or rng.random() < p["waste_rates"]["cache_miss"]["miss_prob_per_call"]):
            caching = False
            repeat = bool(tools and tools[0].get("loop") and calls[i - 1][0].get("loop"))
            if not repeat:  # a loop repeat is priced by the Runaway Loop finding, not as a Cache Miss
                missed.append(i)
        cr = (prev_input // block) * block if caching else 0
        span = b.call(model=model, input_tokens=ctx, output_tokens=out_tokens, cache_read_tokens=cr,
                      prefix_hash=prefix_hash, prefix_tokens=prefix_tokens,
                      system_instructions=[{"type": "text", "content": system}] if i == 0 else None,
                      input_messages=new_msgs or None,
                      output_messages=[{"role": "assistant", "parts": parts,
                                        "finish_reason": "tool_call" if tools else "stop"}])
        new_msgs = []
        prev_input = ctx
        ctx += out_tokens
        for j, t in enumerate(tools):
            b.tool(span, t["tool"], t["args"], t["result"], result_tokens=t["tokens"])
            new_msgs.append({"role": "tool", "parts": [{"type": "tool_call_response", "id": f"{sid}-tc{i}-{j}",
                                                        "response": t["result"]}]})
            ctx += t["tokens"]
            if t["kind"] == "discovery_fix":
                pending_note = t["note"]
                discoveries_gt.append({"statement": t["statement"], "kind": t["discovery_kind"], "call_seq": i})
            if t["kind"] in ("reread", "loop"):
                seq_patterns.append((t["kind"], i))
    payload = b.otlp()
    if not missed:
        plan["patterns"].discard("cache_miss")
    mo = plan["complexity"] == "low" and pricing.price(model).tier == "flagship"
    patterns = sorted(plan["patterns"] | ({"model_overkill"} if mo else set()))
    gt = {
        "session_id": sid, "initiative_id": ini["id"], "initiative_name": ini["name"],
        "business_function": plan["bf"], "team": plan["team"], "member_id": plan["member"], "agent": agent,
        "model": model, "complexity": plan["complexity"], "task_idx": plan["task_idx"],
        "ambiguous": bool(task.get("ambiguous")), "started_at": start.isoformat().replace("+00:00", "Z"),
        "call_count": n_calls, "waste_patterns": patterns,
        "reread_call_seqs": [s for k, s in seq_patterns if k == "reread"],
        "loop_call_seqs": [s for k, s in seq_patterns if k == "loop"],
        "cache_miss_call_seqs": missed,
        "discoveries": discoveries_gt,
        "usual_resources_read": sorted({st["resource_id"] for st in steps if st["kind"] == "usual_read"}),
        "cross_read": [st["resource_id"] for st in steps if st["kind"] == "cross_read"],
    }
    return payload, gt


# --- the whole dataset -------------------------------------------------------------------------
def _start_times(p: dict, rng: random.Random, n: int) -> list[datetime]:
    per = p["period"]
    t0 = datetime.fromisoformat(per["start"].replace("Z", "+00:00"))
    days = [t0 + timedelta(days=d) for d in range(per["days"])]
    weights = [per["weekend_factor"] if d.weekday() >= 5 else 1.0 for d in days]
    out = []
    for _ in range(n):
        day = rng.choices(days, weights=weights)[0]
        hour = min(23.99, max(0.0, rng.gauss(per["hour_utc_mean"], per["hour_utc_sd"])))
        out.append(day + timedelta(seconds=int(hour * 3600)))
    return sorted(out)


def generate(params: dict, library: dict, *, org: dict | None = None, sessions: int | None = None,
             seed: int | None = None, out_dir: Path = P.OTLP_OUT_DIR, ground_truth: Path = P.GROUND_TRUTH_PATH,
             summary_path: Path | None = P.SUMMARY_PATH) -> dict:
    params = {**params, "seed": params["seed"] if seed is None else seed}
    n = int(sessions or params["sessions"])
    w = World(params, library, org or company.org())
    rng = random.Random(w.seed)
    weights = [i["weight"] for i in w.inis]
    starts = _start_times(params, rng, n)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("day-*.jsonl"):
        old.unlink()
    ground_truth.parent.mkdir(parents=True, exist_ok=True)
    by_day: dict[str, list[str]] = defaultdict(list)
    gts: list[dict] = []
    spend: Counter = Counter()
    for k, start in enumerate(starts):
        ini = rng.choices(w.inis, weights=weights)[0]
        plan = _plan_session(w, rng, ini)
        payload, gt = build_session(w, f"syn-{k + 1:05d}", start, plan, rng)
        by_day[start.date().isoformat()].append(json.dumps(payload, separators=(",", ":")))
        gt["spend_usd"] = round(_payload_spend(payload), 6)
        spend[gt["business_function"]] += gt["spend_usd"]
        gts.append(gt)
    for day, lines in by_day.items():
        (out_dir / f"day-{day}.jsonl").write_text("\n".join(lines) + "\n")
    ground_truth.write_text("".join(json.dumps(g, separators=(",", ":")) + "\n" for g in gts))
    summary = summarise(gts, params)
    root = P.config.REPO_ROOT
    otlp_dir = out_dir.resolve()
    summary["files"] = {"otlp_dir": str(otlp_dir.relative_to(root) if otlp_dir.is_relative_to(root) else otlp_dir),
                        "otlp_files": len(by_day),
                        "otlp_bytes": sum(f.stat().st_size for f in out_dir.glob("day-*.jsonl"))}
    if summary_path is not None:
        summary_path.write_text(json.dumps(summary, indent=1))
    return summary


def _payload_spend(payload: dict) -> float:
    total = 0.0
    for rs in payload["resourceSpans"]:
        for ss in rs["scopeSpans"]:
            for sp in ss["spans"]:
                a = {kv["key"]: kv["value"] for kv in sp["attributes"]}
                if a.get("gen_ai.operation.name", {}).get("stringValue") != "chat":
                    continue
                iv = lambda k: int(a.get(k, {}).get("intValue", 0))  # noqa: E731
                total += pricing.call_spend(a["gen_ai.request.model"]["stringValue"], iv("gen_ai.usage.input_tokens"),
                                            iv("gen_ai.usage.output_tokens"), iv("gen_ai.usage.cache_read.input_tokens"))
    return total


def summarise(gts: list[dict], params: dict) -> dict:
    n = len(gts)
    pat = Counter(p for g in gts for p in g["waste_patterns"])
    bf = Counter(g["business_function"] for g in gts)
    ini = Counter(g["initiative_id"] for g in gts)
    disc = Counter((g["initiative_id"], d["statement"]) for g in gts for d in g["discoveries"] if d["kind"] == "repeated")
    usual = defaultdict(Counter)
    for g in gts:
        for r in g["usual_resources_read"]:
            usual[g["initiative_id"]][r] += 1
    return {
        "sessions": n, "seed": params["seed"], "calibrated_from": params.get("_calibrated_from"),
        "members": len({g["member_id"] for g in gts}), "teams": len({g["team"] for g in gts}),
        "period": [gts[0]["started_at"], gts[-1]["started_at"]] if gts else None,
        "spend_usd_by_business_function": {
            b: round(sum(g["spend_usd"] for g in gts if g["business_function"] == b), 2) for b, _ in bf.most_common()},
        "spend_usd_total": round(sum(g["spend_usd"] for g in gts), 2),
        "session_share_by_business_function": {k: round(v / n, 3) for k, v in bf.most_common()},
        "sessions_by_initiative": dict(ini.most_common()),
        "complexity": dict(Counter(g["complexity"] for g in gts)),
        "models": dict(Counter(g["model"] for g in gts)),
        "waste_patterns": {k: pat[k] for k in ("redundant_read", "cache_miss", "runaway_loop", "model_overkill")},
        "clean_sessions": sum(1 for g in gts if not g["waste_patterns"]),
        "ambiguous_prompts": sum(1 for g in gts if g["ambiguous"]),
        "repeated_discoveries": [{"initiative_id": i, "statement": s, "sessions": c,
                                  "share": round(c / ini[i], 3)} for (i, s), c in sorted(disc.items())],
        "one_off_discoveries": sum(1 for g in gts for d in g["discoveries"] if d["kind"] == "one_off"),
        "common_path_share": {i: {r: round(c / ini[i], 3) for r, c in rs.most_common()} for i, rs in sorted(usual.items())},
    }
