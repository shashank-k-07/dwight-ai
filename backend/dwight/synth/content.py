"""GLM-written content library for the synthetic layer (ticket 07).

The generator composes 3-5K Sessions from this library deterministically, so
GLM is called a bounded number of times, not once per Session:

    jobs = Initiatives x (task_batches + 2)      # 15 x 4 = 60 with the default params

Each job asks GLM (through dwight.glm, i.e. the Sciforium pool, NOT the model
names that end up in the synthetic telemetry) for one JSON object, runs at most
`content.max_concurrency` (default 4) at a time, and is retried. Finished jobs
are saved to data/synthetic/content_library.json after each one, so a re-run
resumes and only fills what is missing (`--refresh` redoes everything).

Per Initiative the library holds:
  tasks[]        Member requests with complexity low|med|high and an `ambiguous`
                 flag (prompts that don't name the Initiative and could belong to a
                 neighbouring one), plus the Agent's opening plan and closing summary
  resources{}    excerpt text for each usual resource (what a read tool returns)
  extra[]        other docs/files some Sessions read (long tail, below the common path)
  work_steps[]   routine successful tool steps (tool, args, result)
  failing_steps[] steps that keep failing the same way (Runaway Loop material)
  discoveries[]  one trial-and-error script per org.yaml repeated Discovery
  one_offs[]     scripts for rare, one-off Discoveries

storage-cost-reduction's usual resources are the real company-docs/ files and its
two Discovery scripts use bin/blobctl's real error strings, so they are written
here in code, not by GLM.

The library is keyed by Initiative, so it is label-bearing: the classifier and
other pipeline stages must never read it.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from dwight import company, config
from dwight.synth.params import CONTENT_PATH

LIBRARY_VERSION = 1


# --- GLM output schemas --------------------------------------------------------
class Task(BaseModel):
    prompt: str = Field(description="What the Member typed to the Agent")
    complexity: Literal["low", "med", "high"]
    ambiguous: bool = Field(description="True if the prompt does not make the Initiative obvious")
    plan: str = Field(description="The Agent's first reply: 1-2 sentences on how it will start")
    summary: str = Field(description="The Agent's closing message: 1-3 sentences on what it did")


class TaskBatch(BaseModel):
    tasks: list[Task]


class ResourceText(BaseModel):
    resource_id: str
    excerpt: str = Field(description="The first ~600-1200 characters of the doc/file, as the read tool returns it")


class ResourceBatch(BaseModel):
    usual: list[ResourceText]
    extra: list[ResourceText]


class ToolStep(BaseModel):
    tool: str
    args: dict[str, Any]
    result: str


class DiscoveryScript(BaseModel):
    statement: str = Field(description="The fact, one sentence")
    failed_step: ToolStep
    fixed_step: ToolStep
    note: str = Field(description="The Agent's remark right after the fix worked, 1 sentence")


class StepBatch(BaseModel):
    work_steps: list[ToolStep]
    failing_steps: list[ToolStep]
    discoveries: list[DiscoveryScript]
    one_offs: list[DiscoveryScript]


# --- prompts -----------------------------------------------------------------------
def _org_context(org: dict, ini: dict, agent: str, params: dict) -> str:
    bfs = {b["id"]: b["name"] for b in org["business_functions"]}
    teams = {t["id"]: t["name"] for t in org["teams"]}
    neighbours = [f"{i['name']} ({i['description'].strip()})" for i in org["initiatives"]
                  if i["business_function"] == ini["business_function"] and i["id"] != ini["id"]]
    return (
        f"Company: {org['company']['name']}. {org['company']['blurb'].strip()} Internal wiki: Perch "
        f"(page ids look like ENG/some-slug); code lives in GitHub Enterprise repos kestrel/<repo>.\n"
        f"Business Function: {bfs[ini['business_function']]}. Teams working on it: "
        f"{', '.join(teams[t] for t in ini['primary_teams'])}.\n"
        f"Initiative: \"{ini['name']}\": {ini['description'].strip()}\n"
        f"Usual resources: {', '.join(r['id'] for r in ini['usual_resources'])}.\n"
        f"Agent: {agent}. Its work tools: {', '.join(params['agents']['work_tools'][agent])}. "
        f"Read tools: perch.get_page (args page_id), code.read_file (args repo, path).\n"
        f"Other Initiatives in the same Business Function: {'; '.join(neighbours) or 'none'}."
    )


_PHASES = ["early-phase work: investigating, planning, first changes, questions about how things work",
           "later-phase work: rollout, follow-up fixes, reviews, small chores, reporting on progress",
           "mid-phase work: the bulk of the changes, debugging, edge cases",
           "wrap-up work: cleanup, docs, handover, retrospective notes"]


def _tasks_prompt(ctx: str, n: int, batch: int) -> str:
    low, high = round(n * 0.3), round(n * 0.25)
    amb = max(2, round(n * 0.15))
    return (
        f"{ctx}\n\nWrite {n} realistic, varied requests that different Members of these Teams typed to the Agent "
        f"while working on this Initiative. Focus on {_PHASES[batch % len(_PHASES)]}.\n"
        f"- Exactly {low} have complexity \"low\" (trivial: fix a typo, rename a field, reformat, bump one config "
        f"value, summarise one short page), {high} are \"high\" (multi-step, multi-file, investigation), the rest \"med\".\n"
        f"- Exactly {amb} are ambiguous=true: they never name the Initiative or its project, and could plausibly "
        f"belong to one of the other Initiatives listed. The rest make the goal reasonably clear, but most should NOT "
        f"quote the Initiative name verbatim; mention concrete services, files, pages, tickets, customers or numbers.\n"
        f"- Vary the style: terse one-liners, detailed paragraphs, pasted error lines, ticket ids like KST-1234.\n"
        f"- plan: the Agent's first reply (1-2 sentences). summary: its closing message (1-3 sentences, what it did).\n"
        f"Return JSON {{\"tasks\": [...]}} with {n} items.")


def _resources_prompt(ctx: str, ini: dict, n_extra: int, skip_usual: bool) -> str:
    usual = "" if skip_usual else (
        "usual: for EACH usual resource id listed above (same ids, same order), write an excerpt of 600-1200 "
        "characters that reads like the real start of that page or file (headings, code, tables as fits).\n")
    return (
        f"{ctx}\n\n{usual}"
        f"extra: invent {n_extra} OTHER resources that only some Sessions of this Initiative read (related code "
        f"files, wiki pages, READMEs). Ids must look like perch:<SPACE>/<slug> or repo:kestrel/<repo>/<path>. Each "
        f"gets a 400-900 character excerpt.\n"
        f"Do not state any of these facts anywhere: {'; '.join(d['statement'] for d in ini['repeated_discoveries']) or 'n/a'}.\n"
        f"Return JSON {{\"usual\": [{{resource_id, excerpt}}...], \"extra\": [...]}}"
        + (" with usual = []." if skip_usual else "."))


def _steps_prompt(ctx: str, ini: dict, params: dict, agent: str) -> str:
    c = params["content"]
    stmts = [d["statement"] for d in ini["repeated_discoveries"]]
    disc = ("discoveries: one script per fact below, in this order. failed_step is what an Agent that doesn't know "
            "the fact tries first, with a realistic error result that does NOT state the fact outright; fixed_step "
            "applies the fact and succeeds; note is the Agent's one-sentence remark stating what it learned.\n"
            + "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(stmts)) + "\n") if stmts else "discoveries: [].\n"
    return (
        f"{ctx}\n\nWrite tool steps this Agent performs in Sessions for this Initiative. Tools must be from its "
        f"work tools listed above (never perch.get_page or code.read_file here); args is a JSON object of arguments; results are realistic tool output (5-25 lines, no ellipses).\n"
        f"work_steps: {c['work_steps']} routine steps that succeed (commands, writes, lookups, searches). Each result "
        f"must be distinct.\n"
        f"failing_steps: {c['failing_steps']} steps that fail the same way every time they are retried (a flaky or "
        f"broken test, a query that keeps timing out, a lookup that keeps returning an error).\n"
        f"{disc}"
        f"one_offs: {c['one_offs']} scripts for OTHER small, plausible facts an Agent might work out once (same shape "
        f"as discoveries, statement = the fact).\n"
        f"None of work_steps or failing_steps may reveal these facts: {'; '.join(stmts) or 'n/a'}.\n"
        f"Return JSON {{\"work_steps\": [...], \"failing_steps\": [...], \"discoveries\": [...], \"one_offs\": [...]}}.")


# --- hand-written parts (storage-cost-reduction uses real docs and real blobctl) --
def _real_doc_excerpt(resource_id: str, chars: int = 1500) -> str:
    return company.company_doc_path(resource_id).read_text()[:chars]


STORAGE_DISCOVERIES = [
    {"statement": "blobctl needs STORAGE_ENV=staging set, prod is refused",
     "failed_step": {"tool": "run_command",
                     "args": {"cmd": "bin/blobctl plan --bucket {bucket} --rule-id {rule} --transition 30:STANDARD_IA"},
                     "result": "blobctl: error: E_NOENV: target environment not resolved (STORAGE_ENV is empty)\nexit status 2"},
     "fixed_step": {"tool": "run_command",
                    "args": {"cmd": "STORAGE_ENV=staging bin/blobctl plan --bucket {bucket} --rule-id {rule} --transition 30:STANDARD_IA"},
                    "result": "plan {rule} recorded for {bucket} [staging]\n  day    30 -> STANDARD_IA\n  expire: never\n"
                              "next: blobctl apply --rule-id {rule} --change <CHG-id> --approver <@handle>"},
     "note": "blobctl only runs with STORAGE_ENV=staging; the production value is refused for agent credentials."},
    {"statement": "blobctl --bucket takes the bare bucket name, not an s3:// URI",
     "failed_step": {"tool": "run_command",
                     "args": {"cmd": "STORAGE_ENV=staging bin/blobctl plan --bucket s3://{bucket} --rule-id {rule} --transition 90:GLACIER_IR"},
                     "result": "blobctl: error: E_BADREF: invalid bucket reference 's3://{bucket}'\nexit status 2"},
     "fixed_step": {"tool": "run_command",
                    "args": {"cmd": "STORAGE_ENV=staging bin/blobctl plan --bucket {bucket} --rule-id {rule} --transition 90:GLACIER_IR"},
                    "result": "plan {rule} recorded for {bucket} [staging]\n  day    90 -> GLACIER_IR\n  expire: never\n"
                              "next: blobctl apply --rule-id {rule} --change <CHG-id> --approver <@handle>"},
     "note": "--bucket wants the bare kst-... name; the s3:// form in the runbook examples is rejected."},
]
STORAGE_BUCKETS = ["kst-telemetry-raw-prod", "kst-telemetry-raw-eu", "kst-pod-images", "kst-app-logs",
                   "kst-ml-snapshots", "kst-support-attachments", "kst-replay-archive", "kst-web-assets",
                   "kst-audit-logs", "kst-ml-features"]


# --- orchestration -------------------------------------------------------------------
def agent_for(ini: dict, org: dict, params: dict) -> str:
    bf_name = {b["id"]: b["name"] for b in org["business_functions"]}[ini["business_function"]]
    return params["agents"]["by_business_function"][bf_name]


def plan_jobs(org: dict, params: dict) -> list[tuple[str, str, Any]]:
    """[(initiative_id, job_key, spec)] for every job the library needs."""
    jobs = []
    for ini in org["initiatives"]:
        for b in range(params["content"]["task_batches"]):
            jobs.append((ini["id"], f"tasks-{b}", b))
        jobs.append((ini["id"], "resources", None))
        jobs.append((ini["id"], "steps", None))
    return jobs


def _run_job(glm_mod, org: dict, params: dict, ini: dict, key: str, spec: Any) -> dict:
    agent = agent_for(ini, org, params)
    ctx = _org_context(org, ini, agent, params)
    c = params["content"]
    msgs = lambda text: [{"role": "system", "content": "You write realistic synthetic workplace data for a "  # noqa: E731
                          "fictional logistics company. Output JSON only."}, {"role": "user", "content": text}]
    if key.startswith("tasks-"):
        out = glm_mod.chat_json(msgs(_tasks_prompt(ctx, c["tasks_per_batch"], spec)), schema=TaskBatch,
                                temperature=0.9, max_tokens=8000)
        return {"tasks": [t.model_dump() for t in out.tasks]}
    if key == "resources":
        real = ini["id"] == "storage-cost-reduction"
        out = glm_mod.chat_json(msgs(_resources_prompt(ctx, ini, c["extra_resources"], real)), schema=ResourceBatch,
                                temperature=0.7, max_tokens=8000)
        usual_ids = [r["id"] for r in ini["usual_resources"]]
        if real:
            usual = {rid: _real_doc_excerpt(rid) for rid in usual_ids}
        else:
            got = {r.resource_id: r.excerpt for r in out.usual}
            # Map by position when GLM renamed an id; fall back to a stub excerpt.
            usual = {rid: got.get(rid) or (out.usual[i].excerpt if i < len(out.usual) else f"# {rid}\n")
                     for i, rid in enumerate(usual_ids)}
        extra = [r.model_dump() for r in out.extra if r.resource_id not in usual_ids
                 and (r.resource_id.startswith("perch:") or r.resource_id.startswith("repo:"))]
        return {"resources": usual, "extra": extra}
    if key == "steps":
        out = glm_mod.chat_json(msgs(_steps_prompt(ctx, ini, params, agent)), schema=StepBatch,
                                temperature=0.7, max_tokens=10000)
        d = out.model_dump()
        allowed = set(params["agents"]["work_tools"][agent])
        for k in ("work_steps", "failing_steps"):  # reads come from `resources`, so drop any read steps here
            d[k] = [st for st in d[k] if st["tool"] in allowed]
        if len(d["work_steps"]) < 4 or not d["failing_steps"]:
            raise ValueError(f"too few usable steps: {len(d['work_steps'])} work, {len(d['failing_steps'])} failing")
        stmts = [x["statement"] for x in ini["repeated_discoveries"]]
        if ini["id"] == "storage-cost-reduction":
            d["discoveries"] = STORAGE_DISCOVERIES
        else:
            if len(d["discoveries"]) < len(stmts):
                raise ValueError(f"expected {len(stmts)} discovery scripts, got {len(d['discoveries'])}")
            d["discoveries"] = d["discoveries"][:len(stmts)]
            for script, s in zip(d["discoveries"], stmts):
                script["statement"] = s  # keep the org.yaml wording as the ground-truth statement
        return d
    raise KeyError(key)


def _empty_library() -> dict:
    return {"version": LIBRARY_VERSION, "initiatives": {}, "jobs": {}}


def load_library(path: Path = CONTENT_PATH) -> dict:
    return json.loads(path.read_text()) if path.exists() else _empty_library()


def assemble(library: dict) -> dict:
    """Merge finished jobs into library['initiatives'][id] = {tasks, resources, extra, ...}."""
    inis: dict[str, dict] = {}
    for job_id, part in sorted(library["jobs"].items()):
        ini_id, key = job_id.split("/", 1)
        d = inis.setdefault(ini_id, {"tasks": [], "resources": {}, "extra": [], "work_steps": [],
                                     "failing_steps": [], "discoveries": [], "one_offs": []})
        for k, v in part.items():
            if isinstance(v, list):
                d[k] = d[k] + v
            else:
                d[k] = {**d[k], **v}
    library["initiatives"] = inis
    return library


def build(params: dict, *, org: dict | None = None, path: Path = CONTENT_PATH, refresh: bool = False,
          glm_mod=None, log: Callable[[str], None] = lambda m: print(m, file=sys.stderr)) -> dict:
    """Fill every missing job with GLM (bounded concurrency, retries), saving after each."""
    if glm_mod is None:
        from dwight import glm as glm_mod  # noqa: PLC0415
    org = org or company.org()
    library = _empty_library() if refresh else load_library(path)
    todo = [j for j in plan_jobs(org, params) if f"{j[0]}/{j[1]}" not in library["jobs"]]
    inis = {i["id"]: i for i in org["initiatives"]}
    c = params["content"]
    lock = threading.Lock()
    stats = {"calls": 0, "failed": 0}
    t0 = time.time()

    def work(job):
        ini_id, key, spec = job
        for attempt in range(c["retries"]):
            try:
                with lock:
                    stats["calls"] += 1
                return job, _run_job(glm_mod, org, params, inis[ini_id], key, spec)
            except Exception as e:  # noqa: BLE001  (API errors, bad JSON, short output)
                log(f"  {ini_id}/{key} attempt {attempt + 1} failed: {type(e).__name__}: {str(e)[:160]}")
                time.sleep(min(2 ** attempt, 8))
        return job, None

    log(f"content library: {len(todo)} jobs to run (max {c['max_concurrency']} concurrent)")
    with ThreadPoolExecutor(max_workers=c["max_concurrency"]) as pool:
        for fut in as_completed([pool.submit(work, j) for j in todo]):
            (ini_id, key, _), part = fut.result()
            with lock:
                if part is None:
                    stats["failed"] += 1
                    continue
                library["jobs"][f"{ini_id}/{key}"] = part
                library["generated_at"] = datetime.now(timezone.utc).isoformat()
                library["generated_with"] = sorted(set(config.GLM_MODEL_POOL) or {config.GLM_DEFAULT_TIER})
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(assemble(library), indent=1, ensure_ascii=False))
                log(f"  done {ini_id}/{key}")
    library = assemble(library)
    if todo:  # keep the stats of the build that actually ran jobs
        library["last_build"] = {"jobs_run": len(todo), "job_attempts": stats["calls"], "failed_jobs": stats["failed"],
                                 "seconds": round(time.time() - t0, 1)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(library, indent=1, ensure_ascii=False))
    if stats["failed"]:
        log(f"WARNING: {stats['failed']} jobs failed; re-run `content` to fill them")
    return library
