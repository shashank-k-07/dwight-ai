"""Regenerates the committed fixtures (ticket 01). Run from backend/:

    .venv/bin/python fixtures/generate.py

Writes three fixture sets (see docs/dev.md):
  fixtures/otlp/fixture_sessions.json  OTLP Sessions with prompt content, one per Waste Pattern,
                                       clean ones, and the storage-cost-reduction Sessions
                                       (before/after experiment runs, trial-and-error env-var fact)
  fixtures/store/derived.json          what the later stages would derive for those Sessions
                                       (summaries, Initiatives, Trails, Discoveries, WasteFindings,
                                       RecurringDiscoveries, Recommendations, Drafts, a Policy)
                                       -> loaded by `python -m dwight.pipeline run seed_fixtures`
  fixtures/api/*.json                  one response body per API endpoint, demo-scale numbers
                                       (hand-picked, NOT computed from the two sets above)

The store fixture's WasteFindings / RecurringDiscoveries are computed here with a simplified
reading of build-spec §4.2 / §4.6; the real detector (05) and analyses (10, 11) are the
authority. tracer_session.json is hand-written and not produced by this script.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dwight import config, pricing  # noqa: E402
from dwight.ingest.builder import SessionBuilder  # noqa: E402

OUT = Path(__file__).resolve().parent
T0 = 1_788_300_000_000_000_000  # 2026-09-02T22:00Z, Sessions spread over following days
DAY = 86_400_000_000_000
READ_TOOLS = {"read_doc", "read_file", "fetch_url"}
SYS = [{"type": "text", "content": "You are Kestrel's internal coding agent. Use the tools to read docs and files, run commands in the workspace, and write results."}]


def doc_text(doc_id: str) -> str:
    p = config.COMPANY_DOCS_DIR / f"{doc_id}.md"
    return p.read_text()[:1500] if p.exists() else f"# {doc_id}\n(placeholder: company-docs not written yet)"


def resource_id(tool: str, args: dict) -> str:
    if tool == "read_doc":
        return f"company-docs/{args['doc_id']}.md"
    if tool == "read_file":
        return args["path"].lstrip("./")
    return args.get("url", "")


# ---------------------------------------------------------------------------------------
# Session simulation: context grows by each tool result and output; caching serves the
# previous Call's input unless cache=False (Cache Miss).
# ---------------------------------------------------------------------------------------
SESSIONS: list[dict] = []   # meta for derived data


def simulate(sid, *, member, team, bf, model, prompt, steps, day=0, cache=True, prefix_tokens=1500,
             prefix_hash="sys-harness-v1", experiment=None, task_id=None, task_success=None, extra_system=None):
    b = SessionBuilder(sid, member_id=member, team=team, business_function=bf, agent="dwight-harness",
                       dataset="fixture", experiment=experiment, task_id=task_id, task_success=task_success,
                       start_ns=T0 + day * DAY + (sum(map(ord, sid)) % 600) * 60_000_000_000)
    sys_parts = SYS + ([{"type": "text", "content": extra_system}] if extra_system else [])
    ctx = prefix_tokens + 250
    prev_input = 0
    new_msgs = [{"role": "user", "parts": [{"type": "text", "content": prompt}]}]
    calls = []
    for i, st in enumerate(steps):
        tools = st.get("tools", [])
        out_tokens = st.get("out", 150)
        parts = [{"type": "tool_call", "id": f"{sid}-tc{i}-{j}", "name": t[0], "arguments": t[1]}
                 for j, t in enumerate(tools)]
        if st.get("text"):
            parts.insert(0, {"type": "text", "content": st["text"]})
        cr = (prev_input // 128) * 128 if (cache and i > 0) else 0
        span = b.call(model=model, input_tokens=ctx, output_tokens=out_tokens, cache_read_tokens=cr,
                      prefix_hash=prefix_hash, prefix_tokens=prefix_tokens,
                      system_instructions=sys_parts if i == 0 else None, input_messages=new_msgs,
                      output_messages=[{"role": "assistant", "parts": parts,
                                        "finish_reason": "tool_call" if tools else "stop"}])
        spend = pricing.call_spend(model, ctx, out_tokens, cr, 0)
        calls.append({"seq": i, "input": ctx, "cache_read": cr, "output": out_tokens, "spend": spend,
                      "tools": tools, "model": model})
        new_msgs = []
        prev_input = ctx
        ctx += out_tokens
        for j, (name, args, result, rtok) in enumerate(tools):
            b.tool(span, name, args, result, result_tokens=rtok)
            new_msgs.append({"role": "tool", "parts": [{"type": "tool_call_response", "id": f"{sid}-tc{i}-{j}",
                                                        "response": result}]})
            ctx += rtok
    SESSIONS.append({"session_id": sid, "team": team, "bf": bf, "model": model, "calls": calls,
                     "experiment": experiment, "prefix_tokens": prefix_tokens, "cache": cache})
    return b.otlp()


def read_doc(doc_id, tok):
    return ("read_doc", {"doc_id": doc_id}, doc_text(doc_id), tok)


def read_file(path, text, tok):
    return ("read_file", {"path": path}, text, tok)


def run(cmd, result, tok=60):
    return ("run_command", {"cmd": cmd}, result, tok)


def write(path, tok=10):
    return ("write_file", {"path": path, "content": "..."}, f"ok: wrote {path}", tok)


DOCS = [("storage-tiering-policy", 5200), ("storage-cost-dashboard", 4800),
        ("storage-service-ownership", 4100), ("blobctl-migration-runbook", 5600)]
ENV_FAIL = ("error: STORAGE_ENV is not set. blobctl refuses to plan or apply against an unknown "
            "environment. exit status 2")
PLAN_OK = "plan written to .blobctl/plans/{rule}.json (dry run, 3 transitions)"
BUCKETS = ["kst-telemetry-raw-prod", "kst-replay-archive", "kst-pod-images", "kst-ml-features",
           "kst-audit-logs", "kst-web-assets", "kst-billing-exports", "kst-support-attachments"]


def storage_prompt(n, bucket):
    return (f"Project Tidewater task {n:02d}: prepare the lifecycle rule for s3://{bucket} using the company "
            f"storage docs, record it as a blobctl plan (dry run), and write out/t{n:02d}.json with the bucket, "
            f"rule_id and monthly cost before/after.")


payloads = []

# --- tracer-like clean Sessions and one per Waste Pattern ----------------------------------
payloads.append(simulate(
    "fx-rr-01", member="m-014", team="Platform", bf="Engineering", model="glm-4.7", day=1,
    prompt="Migrate auth/session.py from the legacy token store to the new sessions service.",
    steps=[{"tools": [read_file("auth/session.py", "class SessionStore: ...  # 240 lines", 2400)]},
           {"tools": [read_file("auth/session.py", "class SessionStore: ...  # 240 lines", 2400)]},
           {"tools": [read_file("auth/tokens.py", "def issue_token(user): ...", 1800)]},
           {"tools": [read_file("auth/session.py", "class SessionStore: ...  # 240 lines", 2400)]},
           {"tools": [run("pytest tests/auth", "error: REDIS_URL not set", 80)]},
           {"tools": [run("REDIS_URL=redis://localhost:6379 pytest tests/auth", "12 passed", 40)]},
           {"tools": [write("auth/session.py")], "out": 900},
           {"text": "Migrated SessionStore to the sessions service; tests pass.", "out": 120}]))
payloads.append(simulate(
    "fx-cm-01", member="m-022", team="Platform", bf="Engineering", model="glm-4.7", day=2,
    cache=False, prefix_tokens=3000, prefix_hash="sys-ts-volatile",
    extra_system="Current time: 2026-09-04T09:13:52.114Z",
    prompt="After the Kubernetes 1.31 client bump the integration retry test flakes. Find why and fix it.",
    steps=[{"tools": [read_file("ci/integration.yml", "jobs: ...", 900)]},
           {"tools": [read_file("tests/test_retry.py", "def test_retry_backoff(): ...", 1400)]},
           {"tools": [read_file("lib/retry.py", "def backoff(n): ...", 1100)]},
           {"tools": [write("lib/retry.py")], "out": 600},
           {"text": "Fixed: backoff used wall-clock jitter; seeded it in tests.", "out": 100}]))
payloads.append(simulate(
    "fx-rl-01", member="m-023", team="Platform", bf="Engineering", model="glm-4.7", day=3,
    prompt="Make tests/test_export.py pass again after the Kubernetes 1.31 client upgrade.",
    steps=[{"tools": [read_file("tests/test_export.py", "def test_export_csv(): ...", 1200)]}]
          + [{"tools": [run("pytest tests/test_export.py", "FAILED test_export_csv - AssertionError: 3 != 4", 300)],
              "out": 90} for _ in range(6)]
          + [{"text": "I could not get the test to pass.", "out": 60}]))
payloads.append(simulate(
    "fx-mo-01", member="m-031", team="Routing", bf="Engineering", model="glm-5.1", day=4,
    prompt="Fix the typo 'recieve' in postmortems/2026-08-14-routing-outage.md.",
    steps=[{"tools": [read_file("postmortems/2026-08-14-routing-outage.md", "# Routing outage 2026-08-14\nOn-call did not recieve ...", 700)]},
           {"tools": [write("postmortems/2026-08-14-routing-outage.md")], "out": 80},
           {"text": "Fixed the typo.", "out": 30}]))
payloads.append(simulate(
    "fx-clean-01", member="m-015", team="Platform", bf="Engineering", model="glm-4.7", day=5,
    prompt="Add a /v2/sessions/revoke endpoint to the sessions service.",
    steps=[{"tools": [read_file("services/sessions/api.py", "router = APIRouter() ...", 2100)]},
           {"tools": [read_file("services/sessions/models.py", "class Session(Base): ...", 1300)]},
           {"tools": [write("services/sessions/api.py")], "out": 700},
           {"tools": [run("pytest tests/sessions", "8 passed", 40)]},
           {"text": "Added the revoke endpoint with tests.", "out": 100}]))
payloads.append(simulate(
    "fx-clean-02", member="m-016", team="Platform", bf="Engineering", model="glm-4.5-air", day=6,
    prompt="Update the auth migration checklist in docs/auth-migration.md with the revoke endpoint.",
    steps=[{"tools": [read_file("docs/auth-migration.md", "# Auth migration ...", 900)]},
           {"tools": [write("docs/auth-migration.md")], "out": 300},
           {"text": "Checklist updated.", "out": 40}]))
payloads.append(simulate(
    "fx-mkt-01", member="m-102", team="Growth Marketing", bf="Marketing", model="glm-4.5-air", day=7,
    prompt="Summarise last month's campaign attribution report for peak season campaign planning.",
    steps=[{"tools": [("fetch_url", {"url": "https://perch.kestrel.internal/marketing/q3-attribution"},
                       "Q3 attribution: paid social 31% ...", 2600)]},
           {"text": "Summary: paid social drove 31% of signups ...", "out": 500}]))

# --- storage cost reduction: 6 "before" runs, 2 plain runs, 6 "after" runs -------------------
for n in range(1, 7):
    bucket = BUCKETS[n - 1]
    rule = f"tidewater-{bucket}-v2"
    steps = [{"tools": [read_doc(d, t)]} for d, t in DOCS]
    if n <= 5:  # trial and error: fails without STORAGE_ENV, then works with STORAGE_ENV=staging
        steps += [{"tools": [run(f"bin/blobctl plan --bucket s3://{bucket} --rule {rule}", ENV_FAIL)]},
                  {"tools": [run(f"STORAGE_ENV=staging bin/blobctl plan --bucket s3://{bucket} --rule {rule}",
                                 PLAN_OK.format(rule=rule))], "text": "Retrying with STORAGE_ENV=staging."}]
    else:       # task 06 is report-only and fails its check
        steps += [{"tools": [read_file(".blobctl/ledger.jsonl", '{"action":"plan",...}', 400)]}]
    steps += [{"tools": [write(f"out/t{n:02d}.json")], "out": 400}, {"text": "Done.", "out": 80}]
    payloads.append(simulate(f"fx-scr-b{n:02d}", member=f"m-04{n}", team="Data Infrastructure", bf="Engineering",
                             model="glm-4.7", day=8 + n, prompt=storage_prompt(n, bucket), steps=steps,
                             experiment="before", task_id=f"t{n:02d}", task_success=(n != 6)))
for n, docs in ((7, DOCS), (8, DOCS[:2] + DOCS[3:])):
    bucket = BUCKETS[n - 1]
    rule = f"tidewater-{bucket}-v2"
    steps = [{"tools": [read_doc(d, t)]} for d, t in docs]
    if n == 7:
        steps += [{"tools": [run(f"bin/blobctl plan --bucket s3://{bucket} --rule {rule}", ENV_FAIL)]},
                  {"tools": [run(f"STORAGE_ENV=staging bin/blobctl plan --bucket s3://{bucket} --rule {rule}",
                                 PLAN_OK.format(rule=rule))]}]
    steps += [{"tools": [write(f"out/t{n:02d}.json")], "out": 400}, {"text": "Done.", "out": 80}]
    payloads.append(simulate(f"fx-scr-{n:02d}", member=f"m-05{n}", team="Data Infrastructure", bf="Engineering",
                             model="glm-4.7", day=15 + n, prompt=storage_prompt(n, bucket), steps=steps))
DRAFT_TOKENS = 3000
for n in range(1, 7):
    bucket = BUCKETS[n - 1]
    rule = f"tidewater-{bucket}-v2"
    steps = [{"tools": [read_doc("storage-cost-dashboard", 4800)]},
             {"tools": [run(f"STORAGE_ENV=staging bin/blobctl plan --bucket s3://{bucket} --rule {rule}",
                            PLAN_OK.format(rule=rule))]},
             {"tools": [write(f"out/t{n:02d}.json")], "out": 400}, {"text": "Done.", "out": 80}]
    payloads.append(simulate(f"fx-scr-a{n:02d}", member=f"m-04{n}", team="Data Infrastructure", bf="Engineering",
                             model="glm-4.7", day=20 + n, prompt=storage_prompt(n, bucket), steps=steps,
                             prefix_tokens=1500 + DRAFT_TOKENS, prefix_hash="sys-harness-v1+draft",
                             extra_system="(Draft loaded: storage-cost-reduction initiative doc + memory file)",
                             experiment="after", task_id=f"t{n:02d}", task_success=True))

(OUT / "otlp" / "fixture_sessions.json").write_text(json.dumps(payloads, indent=1))

# ---------------------------------------------------------------------------------------
# Derived store data
# ---------------------------------------------------------------------------------------
INITIATIVE_OF = {"fx-rr-01": "auth-migration", "fx-clean-01": "auth-migration", "fx-clean-02": "auth-migration",
                 "fx-cm-01": "k8s-upgrade", "fx-rl-01": "k8s-upgrade",
                 "fx-mo-01": "incident-postmortems", "fx-mkt-01": "peak-season-campaign"}
SUMMARY = {"fx-rr-01": "Migrated the session store to the sessions service.",
           "fx-cm-01": "Fixed a flaky retry test after the Kubernetes client upgrade.",
           "fx-rl-01": "Tried to fix a failing export test; gave up.",
           "fx-mo-01": "Fixed a typo in a postmortem.",
           "fx-clean-01": "Added a session revoke endpoint.",
           "fx-clean-02": "Updated the auth migration checklist.",
           "fx-mkt-01": "Summarised the Q3 campaign attribution report."}
COMPLEXITY = {"fx-mo-01": "low", "fx-clean-02": "low", "fx-mkt-01": "low", "fx-rl-01": "med"}
INITIATIVES = {
    "storage-cost-reduction": ("Storage cost reduction", "Project Tidewater: move S3 buckets onto the lifecycle schedule their data class allows.", "Engineering"),
    "auth-migration": ("Auth migration", "Move services from the legacy token store to the sessions service.", "Engineering"),
    "k8s-upgrade": ("Kubernetes 1.31 upgrade", "Upgrade clusters and service clients to Kubernetes 1.31.", "Engineering"),
    "incident-postmortems": ("Incident postmortems", "Write and tidy incident postmortems.", "Engineering"),
    "peak-season-campaign": ("Peak season campaign", "Plan and report on the peak season marketing campaign.", "Marketing"),
}

ENV_PHRASES = [  # same Discovery, worded differently per Session (as a classifier would)
    "blobctl plan fails unless STORAGE_ENV is set; STORAGE_ENV=staging works for Tidewater migrations.",
    "The blobctl migration script needs the env var STORAGE_ENV=staging.",
    "Setting STORAGE_ENV=staging is required before running blobctl plan.",
    "blobctl exits with status 2 when STORAGE_ENV is missing; use STORAGE_ENV=staging.",
    "Tidewater blobctl commands only run with STORAGE_ENV=staging in the environment.",
    "Without STORAGE_ENV=staging, blobctl refuses to plan against the bucket.",
]
by_id = {s["session_id"]: s for s in SESSIONS}
sessions_out, trails, discoveries, findings = [], [], [], []
for s in SESSIONS:
    sid = s["session_id"]
    init = INITIATIVE_OF.get(sid, "storage-cost-reduction")
    sessions_out.append({"session_id": sid, "initiative_id": init,
                         "summary": SUMMARY.get(sid, "Prepared a Tidewater lifecycle rule for one bucket."),
                         "complexity": COMPLEXITY.get(sid, "med")})
    pos = 0
    for c in s["calls"]:
        for name, args, _res, rtok in c["tools"]:
            if name in READ_TOOLS:
                trails.append({"session_id": sid, "position": pos, "resource_id": resource_id(name, args),
                               "tokens": rtok, "call_seq": c["seq"]})
                pos += 1
    if sid.startswith("fx-scr") and any("STORAGE_ENV=staging" in (t[1].get("cmd", "")) for c in s["calls"] for t in c["tools"]) \
            and s["experiment"] != "after":
        seq = next(c["seq"] for c in s["calls"] for t in c["tools"] if "STORAGE_ENV=staging" in t[1].get("cmd", ""))
        discoveries.append({"session_id": sid, "idx": 0, "call_seq": seq,
                            "statement": ENV_PHRASES[len(discoveries) % len(ENV_PHRASES)]})
discoveries.append({"session_id": "fx-scr-b02", "idx": 1, "call_seq": 5,
                    "statement": "Tidewater rule ids must end in -v2 when a v1 rule already exists on the bucket."})
discoveries.append({"session_id": "fx-rr-01", "idx": 0, "call_seq": 5,
                    "statement": "The auth test suite needs REDIS_URL pointing at a local Redis instance."})


def rate(model, cached):
    return pricing.input_rate(model, cached)


# WasteFindings (simplified §4.2)
for s in SESSIONS:
    sid, calls = s["session_id"], s["calls"]
    seen = set()
    for c in calls:  # Redundant Read
        for name, args, res, rtok in c["tools"]:
            key = (name, res)
            if name in READ_TOOLS and key in seen:
                later = [x for x in calls if x["seq"] > c["seq"]]
                usd = sum(rtok * rate(x["model"], cached=(i > 0 and s["cache"])) for i, x in enumerate(later))
                findings.append({"session_id": sid, "pattern": "redundant_read", "kind": "measured", "usd": usd,
                                 "evidence": [f"{sid}:{x['seq']}" for x in [c] + later],
                                 "detail": f"duplicate read of {resource_id(name, args)} ({rtok} tokens)"})
            seen.add(key)
    miss = [c for c in calls[1:] if c["cache_read"] < s["prefix_tokens"] * 0.5]  # Cache Miss
    if miss:
        p = pricing.price(s["model"])
        usd = sum((s["prefix_tokens"] - c["cache_read"]) * (p.input - p.cache_read) / 1e6 for c in miss)
        findings.append({"session_id": sid, "pattern": "cache_miss", "kind": "measured", "usd": usd,
                         "evidence": [f"{sid}:{c['seq']}" for c in miss],
                         "detail": "same prompt prefix hash as the previous Call, no cache read"})
    runs = [c for c in calls if c["tools"] and c["tools"][0][0] == "run_command"]  # Runaway Loop
    if len(runs) >= 4 and len({c["tools"][0][1]["cmd"] for c in runs}) == 1:
        after_first = [c for c in calls if c["seq"] > runs[0]["seq"]]
        findings.append({"session_id": sid, "pattern": "runaway_loop", "kind": "measured",
                         "usd": sum(c["spend"] for c in after_first),
                         "evidence": [f"{sid}:{c['seq']}" for c in runs],
                         "detail": f"{len(runs)} identical runs of {runs[0]['tools'][0][1]['cmd']!r}, same result"})
    if COMPLEXITY.get(sid) == "low" and pricing.price(s["model"]).tier == "flagship":  # Model Overkill
        cheap = pricing.cheaper_model(s["model"])
        repriced = sum(pricing.call_spend(cheap, c["input"], c["output"], c["cache_read"]) for c in calls)
        findings.append({"session_id": sid, "pattern": "model_overkill", "kind": "estimated",
                         "usd": sum(c["spend"] for c in calls) - repriced,
                         "evidence": [f"{sid}:{c['seq']}" for c in calls],
                         "detail": f"low-complexity Session on {s['model']}; re-priced at {cheap}"})
for i, f in enumerate(findings):
    f["finding_id"] = f"wf-{i:03d}"

# Initiatives
init_rows = []
for iid, (name, desc, bf) in INITIATIVES.items():
    members = [x["session_id"] for x in sessions_out if x["initiative_id"] == iid]
    init_rows.append({"initiative_id": iid, "name": name, "description": desc, "business_function": bf,
                      "session_count": len(members),
                      "spend_usd": sum(sum(c["spend"] for c in by_id[m]["calls"]) for m in members)})

# RecurringDiscoveries for storage-cost-reduction, over non-"after" Sessions
scr = [x["session_id"] for x in sessions_out
       if x["initiative_id"] == "storage-cost-reduction" and by_id[x["session_id"]]["experiment"] != "after"]
reads = defaultdict(set)
tok = defaultdict(list)
for t in trails:
    if t["session_id"] in scr:
        reads[t["resource_id"]].add(t["session_id"])
        tok[t["resource_id"]].append(t)
common = [r for r, ss in reads.items() if len(ss) / len(scr) >= 0.6 and r.startswith("company-docs/")]
cp_sessions = sorted(set.intersection(*(reads[r] for r in common)))
cp_usd = 0.0
for t in trails:
    if t["session_id"] in scr and t["resource_id"] in common:
        s = by_id[t["session_id"]]
        later = [c for c in s["calls"] if c["seq"] > t["call_seq"]]
        cp_usd += t["tokens"] * rate(s["model"], False) + sum(t["tokens"] * rate(s["model"], True) for c in later[1:])
cp_tokens = sum(sum(x["tokens"] for x in tok[r]) / len(tok[r]) for r in common)
env = [d for d in discoveries if "STORAGE_ENV" in d["statement"]]
rd_usd = sum(sum(c["spend"] for c in by_id[d["session_id"]]["calls"] if c["seq"] <= d["call_seq"]) for d in env)
recurring = [
    {"recurring_discovery_id": "rd-scr-path", "initiative_id": "storage-cost-reduction", "form": "common_path",
     "resource_ids": sorted(common), "statement": None, "tokens": int(cp_tokens),
     "session_count": len(cp_sessions), "session_share": round(len(cp_sessions) / len(scr), 4),
     "spend_usd": cp_usd, "evidence": cp_sessions},
    {"recurring_discovery_id": "rd-scr-env", "initiative_id": "storage-cost-reduction", "form": "repeated_discovery",
     "resource_ids": None, "statement": "blobctl plan/apply needs STORAGE_ENV=staging for Tidewater migrations.",
     "tokens": None, "session_count": len(env), "session_share": round(len(env) / len(scr), 4),
     "spend_usd": rd_usd, "evidence": [d["session_id"] for d in env]},
]

DOC_DRAFT = """# Storage cost reduction (Project Tidewater): what you need to start

_Draft by Dwight from the 4 docs these Sessions read. Sources linked per section._

## 1. Which schedule applies ([tiering policy](company-docs/storage-tiering-policy.md))
- Look up the bucket's data class, then apply that class's schedule (days -> storage class).
- Overrides win over the data-class schedule: Tier-1 reader override first, then small-object override.

## 2. Which buckets and what they cost ([cost dashboard](company-docs/storage-cost-dashboard.md))
- Use the August 2026 snapshot figures on the dashboard page, not the live Looker tiles.
- A bucket with an existing v1 rule needs a v2 rule id.

## 3. Who owns and approves ([service ownership](company-docs/storage-service-ownership.md))
- The bucket owner's team handle and the storage approver come from the ownership page.

## 4. How to plan and apply ([blobctl runbook](company-docs/blobctl-migration-runbook.md))
- `bin/blobctl plan --bucket s3://<bucket> --rule tidewater-<bucket>-v2` (dry run), then `apply` with approver.
"""
MEM_DRAFT = """# Memory: storage-cost-reduction

- Always run blobctl with `STORAGE_ENV=staging` set for Tidewater plans and applies; without it blobctl exits with status 2.
"""
drafts = [
    {"draft_id": "d-scr-doc", "recommendation_id": "r-scr-doc", "initiative_id": "storage-cost-reduction",
     "type": "initiative_doc", "title": "Storage cost reduction: initiative doc",
     "filename": "storage-cost-reduction.md", "content": DOC_DRAFT, "source_resource_ids": sorted(common),
     "tokens": DRAFT_TOKENS, "source_tokens": int(cp_tokens)},
    {"draft_id": "d-scr-mem", "recommendation_id": "r-scr-mem", "initiative_id": "storage-cost-reduction",
     "type": "memory", "title": "Storage cost reduction: memory file", "filename": "storage-cost-reduction.memory.md",
     "content": MEM_DRAFT, "source_resource_ids": [], "tokens": len(MEM_DRAFT) // 4, "source_tokens": None},
]
f_by = defaultdict(float)
for f in findings:
    f_by[(INITIATIVE_OF.get(f["session_id"], "storage-cost-reduction"), f["pattern"])] += f["usd"]
monthly_scr = len(scr)  # fixture: treat the fixture Sessions as one month
recommendations = [
    {"recommendation_id": "r-scr-doc", "target_type": "initiative", "target_id": "storage-cost-reduction",
     "practice_id": "consolidated-initiative-doc", "title": "Give Tidewater Sessions one consolidated initiative doc",
     "body": "Most storage cost reduction Sessions read the same four Perch pages to get started. Publish the attached Draft on the Perch docs MCP server and point the agents at it.",
     "infra_refs": ["perch-docs-mcp", "kestrel/blobctl"],
     "usd": (cp_tokens - DRAFT_TOKENS) * monthly_scr * rate("glm-4.7", False), "kind": "estimated",
     "draft_id": "d-scr-doc", "recurring_discovery_id": "rd-scr-path", "suggested_models": None, "rank": 0},
    {"recommendation_id": "r-scr-mem", "target_type": "initiative", "target_id": "storage-cost-reduction",
     "practice_id": "initiative-memory-file", "title": "Add a Tidewater memory file so agents stop rediscovering STORAGE_ENV",
     "body": "Sessions keep finding out by trial and error that blobctl needs STORAGE_ENV=staging. Load the attached memory file into the harness context.",
     "infra_refs": ["kestrel-devagent", "kestrel/blobctl"], "usd": rd_usd, "kind": "estimated",
     "draft_id": "d-scr-mem", "recurring_discovery_id": "rd-scr-env", "suggested_models": None, "rank": 1},
    {"recommendation_id": "r-ci-loop", "target_type": "initiative", "target_id": "k8s-upgrade",
     "practice_id": "step-budget-loop-breaker", "title": "Add a step budget and loop breaker to CI-fixing agents",
     "body": "Stop an agent after 3 identical test runs with the same result.", "infra_refs": ["kestrel-llm-gateway"],
     "usd": f_by[("k8s-upgrade", "runaway_loop")], "kind": "measured", "draft_id": None,
     "recurring_discovery_id": None, "suggested_models": None, "rank": 0},
    {"recommendation_id": "r-ci-cache", "target_type": "initiative", "target_id": "k8s-upgrade",
     "practice_id": "cache-friendly-prompt-layout", "title": "Move the timestamp out of the system prompt",
     "body": "The volatile timestamp at the top of the prompt defeats prompt caching on every Call.",
     "infra_refs": ["kestrel-llm-gateway"], "usd": f_by[("k8s-upgrade", "cache_miss")],
     "kind": "measured", "draft_id": None, "recurring_discovery_id": None, "suggested_models": None, "rank": 1},
    {"recommendation_id": "r-auth-ctx", "target_type": "initiative", "target_id": "auth-migration",
     "practice_id": "shared-context-file-per-service", "title": "Keep a shared context file for the auth services",
     "body": "Agents re-read auth/session.py several times per Session.", "infra_refs": ["kestrel/identity"],
     "usd": f_by[("auth-migration", "redundant_read")], "kind": "measured", "draft_id": None,
     "recurring_discovery_id": None, "suggested_models": None, "rank": 0},
    {"recommendation_id": "r-pol-devex", "target_type": "policy", "target_id": "Routing",
     "practice_id": "tier-routing-by-complexity", "title": "Limit Routing to standard and light tiers",
     "body": "Trivial edits ran on the flagship tier.", "infra_refs": ["kestrel-llm-gateway"],
     "usd": f_by[("incident-postmortems", "model_overkill")], "kind": "estimated", "draft_id": None,
     "recurring_discovery_id": None, "suggested_models": ["glm-4.7", "glm-4.5-air"], "rank": 0},
]
POLICY_YAML = """# LiteLLM team model allowlist, rendered by Dwight. Enforced by the Customer's gateway (ADR 0002).
teams:
  - team_alias: routing
    models:
      - glm-4.7
      - glm-4.5-air
"""
policies = [{"policy_id": "pol-001", "team": "Routing", "allowed_models": ["glm-4.7", "glm-4.5-air"],
             "rendered_config": POLICY_YAML, "output_path": "out/policies/routing.yaml",
             "applied_at": "2026-09-26T12:00:00Z"}]
eval_runs = [{"eval_id": "ev-fixture", "created_at": "2026-09-26T12:00:00Z", "label": "fixture",
              "accuracy": 0.86, "n_sessions": 50, "details": {"note": "fixture value"}}]

(OUT / "store" / "derived.json").write_text(json.dumps({
    "_note": "Derived data for fixture_sessions.json. Loaded by `python -m dwight.pipeline run seed_fixtures`.",
    "sessions": sessions_out, "trail_entries": trails, "discoveries": discoveries, "initiatives": init_rows,
    "waste_findings": findings, "recurring_discoveries": recurring, "recommendations": recommendations,
    "drafts": drafts, "policies": policies, "eval_runs": eval_runs}, indent=1))

# ---------------------------------------------------------------------------------------
# API fixtures: demo-scale numbers matching the build-spec §1 story. Hand-picked.
# ---------------------------------------------------------------------------------------
def M(usd, kind="measured", note=None):
    d = {"usd": round(usd, 2), "kind": kind}
    if note:
        d["note"] = note
    return d


API = OUT / "api"


def put(name, body):
    (API / f"{name}.json").write_text(json.dumps(body, indent=1))


def keyed(param, items):
    return {"_keyed_by": param, "items": items}


teams = {"Engineering": [("Data Infrastructure", 9120.40, 1210), ("Platform", 7310.10, 980),
                         ("Routing", 4480.75, 610), ("Mobile", 3890.20, 540), ("Billing", 2210.00, 300),
                         ("Integrations", 1650.00, 240), ("Forecasting", 1200.00, 190)],
         "Operations": [("Fleet Operations", 1105.90, 240), ("Warehouse Operations", 520.00, 120)],
         "Customer Experience": [("Customer Care", 610.30, 150)],
         "Marketing": [("Growth Marketing", 1320.50, 260)],
         "Finance": [("Accounting & FP&A", 690.40, 110)]}
put("overview", {
    "period": {"start": "2026-08-27T00:00:00Z", "end": "2026-09-26T00:00:00Z"},
    "session_count": 4520, "spend": M(31258.55), "measured_waste": M(6412.80),
    "estimated_saving": M(2987.35, "estimated"),
    "spend_by_business_function": [
        {"business_function": bf, "spend": M(sum(t[1] for t in ts)), "session_count": sum(t[2] for t in ts),
         "teams": [{"team": t, "spend": M(u), "session_count": n} for t, u, n in ts]}
        for bf, ts in teams.items()]})

INIT_ROWS = [
    ("storage-cost-reduction", "Storage cost reduction", "Engineering", 412, 5210.30, 1480.20, 310.00, "redundant_read"),
    ("auth-migration", "Auth migration", "Engineering", 388, 4105.75, 990.10, 220.40, "redundant_read"),
    ("k8s-upgrade", "Kubernetes 1.31 upgrade", "Engineering", 520, 3890.10, 1320.55, 90.10, "runaway_loop"),
    ("invoicing-v2", "Invoicing v2", "Engineering", 301, 3120.00, 610.00, 410.25, "cache_miss"),
    ("driver-app-offline-sync", "Driver app offline sync", "Engineering", 260, 2210.00, 380.40, 150.00, "cache_miss"),
    ("incident-postmortems", "Incident postmortems", "Engineering", 480, 1450.20, 90.00, 820.60, "model_overkill"),
    ("peak-season-campaign", "Peak season campaign", "Marketing", 260, 1320.50, 120.30, 240.00, "model_overkill"),
    ("support-macro-refresh", "Support macro refresh", "Customer Experience", 240, 1105.90, 95.00, 180.00, None),
]
put("initiatives", {"items": [
    {"initiative_id": i, "name": n, "business_function": bf, "session_count": c, "spend": M(s),
     "measured_waste": M(w), "estimated_saving": M(e, "estimated"), "top_waste_pattern": p}
    for i, n, bf, c, s, w, e, p in INIT_ROWS]})
put("initiative", keyed("initiative_id", {
    i: {"initiative_id": i, "name": n, "business_function": bf, "session_count": c, "spend": M(s),
        "description": INITIATIVES.get(i, (n, f"{n} work.", bf))[1]}
    for i, n, bf, c, s, w, e, p in INIT_ROWS}))
put("initiative_waste", keyed("initiative_id", {
    "storage-cost-reduction": {"initiative_id": "storage-cost-reduction", "measured_total": M(1480.20),
                               "estimated_total": M(310.00, "estimated"), "patterns": [
        {"pattern": "redundant_read", "amount": M(910.40), "finding_count": 188, "session_count": 162},
        {"pattern": "cache_miss", "amount": M(402.30), "finding_count": 74, "session_count": 61},
        {"pattern": "runaway_loop", "amount": M(167.50), "finding_count": 12, "session_count": 12},
        {"pattern": "model_overkill", "amount": M(310.00, "estimated"), "finding_count": 40, "session_count": 40}]},
    "k8s-upgrade": {"initiative_id": "k8s-upgrade", "measured_total": M(1320.55),
                           "estimated_total": M(90.10, "estimated"), "patterns": [
        {"pattern": "runaway_loop", "amount": M(870.00), "finding_count": 96, "session_count": 96},
        {"pattern": "cache_miss", "amount": M(450.55), "finding_count": 130, "session_count": 88},
        {"pattern": "model_overkill", "amount": M(90.10, "estimated"), "finding_count": 14, "session_count": 14}]},
}))
put("initiative_recurring_discoveries", keyed("initiative_id", {
    "storage-cost-reduction": {"initiative_id": "storage-cost-reduction", "initiative_session_count": 40, "items": [
        {"recurring_discovery_id": "rd-scr-path", "form": "common_path",
         "resources": [{"resource_id": f"company-docs/{d}.md", "tokens": t} for d, t in
                       [("storage-tiering-policy", 5200), ("storage-cost-dashboard", 4800),
                        ("storage-service-ownership", 4100), ("blobctl-migration-runbook", 5600)]],
         "tokens": 18000, "session_count": 32, "session_share": 0.8, "cost": M(612.40),
         "evidence": [f"s-scr-{i:03d}" for i in range(32)]},
        {"recurring_discovery_id": "rd-scr-env", "form": "repeated_discovery",
         "statement": "The blobctl migration needs STORAGE_ENV=staging; without it blobctl exits with status 2.",
         "session_count": 14, "session_share": 0.35, "cost": M(288.90, note="conservative upper bound"),
         "evidence": [f"s-scr-{i:03d}" for i in range(3, 17)]}]}}))
REC_SCR = [
    {"recommendation_id": "r-scr-doc", "target_type": "initiative", "target_id": "storage-cost-reduction",
     "practice": {"practice_id": "consolidated-initiative-doc", "title": "Consolidated initiative doc"},
     "title": "Give Tidewater Sessions one consolidated initiative doc",
     "body": "32 of 40 Sessions read the same 4 Perch pages (18K tokens) before starting. Publish the attached 3K-token Draft on the **perch-docs-mcp** MCP server and add it to the harness's default context for the Data Infrastructure team.",
     "infra_refs": ["perch-docs-mcp", "kestrel/blobctl"], "saving": M(540.00, "estimated"),
     "draft_id": "d-scr-doc", "recurring_discovery_id": "rd-scr-path",
     "measured_drop": {"token_drop_pct": 38.2, "spend_drop": M(4.12), "counts": True}, "policy_prefill": None},
    {"recommendation_id": "r-scr-mem", "target_type": "initiative", "target_id": "storage-cost-reduction",
     "practice": {"practice_id": "initiative-memory-file", "title": "Initiative memory file"},
     "title": "Add a Tidewater memory file so agents stop rediscovering STORAGE_ENV",
     "body": "14 Sessions separately worked out that blobctl needs `STORAGE_ENV=staging`. Load the attached memory file into agent context for this Initiative.",
     "infra_refs": ["kestrel-devagent"], "saving": M(288.90, "estimated"),
     "draft_id": "d-scr-mem", "recurring_discovery_id": "rd-scr-env", "measured_drop": None, "policy_prefill": None},
    {"recommendation_id": "r-scr-cache", "target_type": "initiative", "target_id": "storage-cost-reduction",
     "practice": {"practice_id": "cache-friendly-prompt-layout", "title": "Cache-friendly prompt layout"},
     "title": "Keep volatile text out of the prompt prefix",
     "body": "61 Sessions paid full price for a prefix that should have been cached. Move the run timestamp below the stable instructions; prompt caching is enabled on the **kestrel-llm-gateway**.",
     "infra_refs": ["kestrel-llm-gateway"], "saving": M(402.30), "draft_id": None, "recurring_discovery_id": None,
     "measured_drop": None, "policy_prefill": None}]
REC_POLICY = {"recommendation_id": "r-pol-devex", "target_type": "policy", "target_id": "Routing",
              "practice": {"practice_id": "tier-routing-by-complexity", "title": "Tier routing by complexity"},
              "title": "Limit Routing to the standard and light tiers",
              "body": "40 low-complexity Sessions ran on the flagship tier (glm-5.1).", "infra_refs": ["kestrel-llm-gateway"],
              "saving": M(820.60, "estimated"), "draft_id": None, "recurring_discovery_id": None,
              "measured_drop": None,
              "policy_prefill": {"team": "Routing", "allowed_models": ["glm-4.7", "glm-4.5-air"]}}
REC_CI = [{"recommendation_id": "r-ci-loop", "target_type": "initiative", "target_id": "k8s-upgrade",
           "practice": {"practice_id": "step-budget-loop-breaker", "title": "Step budget + loop breaker"},
           "title": "Stop CI-fixing agents after 3 identical failing runs",
           "body": "96 Sessions re-ran the same failing test with no change.", "infra_refs": ["kestrel-llm-gateway"],
           "saving": M(870.00), "draft_id": None, "recurring_discovery_id": None, "measured_drop": None,
           "policy_prefill": None}]
put("initiative_recommendations", keyed("initiative_id", {
    "storage-cost-reduction": {"items": REC_SCR}, "k8s-upgrade": {"items": REC_CI}}))
put("recommendations", {"items": REC_SCR + REC_CI + [REC_POLICY]})
D_DOC = {"draft_id": "d-scr-doc", "recommendation_id": "r-scr-doc", "initiative_id": "storage-cost-reduction",
         "type": "initiative_doc", "title": "Storage cost reduction: initiative doc", "filename": "storage-cost-reduction.md",
         "content": DOC_DRAFT, "source_resource_ids": [f"company-docs/{d}.md" for d, _ in DOCS], "tokens": 3050,
         "source_tokens": 18000}
D_MEM = {"draft_id": "d-scr-mem", "recommendation_id": "r-scr-mem", "initiative_id": "storage-cost-reduction",
         "type": "memory", "title": "Storage cost reduction: memory file",
         "filename": "storage-cost-reduction.memory.md", "content": MEM_DRAFT, "source_resource_ids": [],
         "tokens": len(MEM_DRAFT) // 4, "source_tokens": None}
put("initiative_drafts", keyed("initiative_id", {"storage-cost-reduction": {"items": [D_DOC, D_MEM]}}))
put("draft", keyed("draft_id", {"d-scr-doc": D_DOC, "d-scr-mem": D_MEM}))
put("initiative_before_after", keyed("initiative_id", {
    "storage-cost-reduction": {"initiative_id": "storage-cost-reduction", "has_runs": True,
        "before": {"session_count": 10, "tasks_passed": 9, "tasks_total": 10, "success_rate": 0.9,
                   "total_tokens": 612000, "avg_tokens": 61200, "spend": M(10.78)},
        "after": {"session_count": 10, "tasks_passed": 9, "tasks_total": 10, "success_rate": 0.9,
                  "total_tokens": 378200, "avg_tokens": 37820, "spend": M(6.66)},
        "token_drop_pct": 38.2, "spend_drop": M(4.12), "success_held": True},
    "_no_runs": {"initiative_id": "_no_runs", "has_runs": False}}))
put("initiative_sessions", keyed("initiative_id", {"storage-cost-reduction": {"items": [
    {"session_id": f"s-scr-{i:03d}", "member_id": f"m-04{i % 10}", "team": "Data Infrastructure",
     "business_function": "Engineering", "agent": "dwight-harness", "started_at": f"2026-09-{(i % 25) + 1:02d}T10:00:00Z",
     "ended_at": f"2026-09-{(i % 25) + 1:02d}T10:07:00Z",
     "summary": "Prepared a Tidewater lifecycle rule for one bucket.", "complexity": "med",
     "call_count": 9 + i % 4, "total_tokens": 58000 + 700 * i, "spend": M(1.02 + 0.03 * i),
     "waste_patterns": ["redundant_read"] if i % 3 == 0 else [],
     "experiment": "before" if i < 10 else None, "task_success": (i != 4) if i < 10 else None}
    for i in range(12)]}}))
put("policy_options", {"teams": [{"team": t, "business_function": bf} for bf, ts in teams.items() for t, _, _ in ts],
                       "models": [{"model": m, "tier": v["tier"]} for m, v in pricing.table()["models"].items()]})
put("policy_render", {"team": "Routing", "allowed_models": ["glm-4.7", "glm-4.5-air"],
                      "format": "litellm", "rendered_config": POLICY_YAML})
put("policy_apply", policies[0])
put("policies", {"items": policies})
put("closing_numbers", {"spend_analysed": M(31258.55), "measured_waste": M(6412.80),
                        "measured_waste_real_layer": M(18.40), "estimated_saving": M(2987.35, "estimated"),
                        "draft_token_drop_pct": 38.2, "classifier_accuracy": 0.86, "classifier_eval_sessions": 4520})
print(f"wrote {len(payloads)} OTLP Sessions, {len(findings)} findings, {len(list(API.glob('*.json')))} API fixtures")
