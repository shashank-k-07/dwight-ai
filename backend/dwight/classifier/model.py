"""The one model call per Session: transcript -> summary, Initiative, complexity,
Discoveries (build-spec §4.3 step 1).

The classifier picks from the Customer's known Initiatives (cut list #6: no
clustering). The candidates are the org.yaml Initiative ids, names and
descriptions only; the generator inputs (`usual_resources`,
`repeated_discoveries`, `weight`, `primary_teams`) are ground truth-adjacent and
are never shown to the model. Nothing here reads data/ground-truth/.

Output is redacted twice: the prompt asks for it, and `redact()` scrubs emails,
secrets and long tokens from whatever comes back before it is stored.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, create_model

from dwight import company, glm

PROMPT_VERSION = "classify-v3"
MAX_DISCOVERIES = 3


@dataclass(frozen=True)
class Candidate:
    initiative_id: str
    name: str
    description: str
    business_function: str | None = None   # display name; stored, and shown to the model (classify-v3+)


def display_name(name: str) -> str:
    """org.yaml names are lower-case ("storage cost reduction"); show sentence case."""
    return name[:1].upper() + name[1:] if name else name


def candidates(org: dict | None = None) -> list[Candidate]:
    org = org if org is not None else company.org()
    if not org:
        return []
    bf_names = {b["id"]: b["name"] for b in org.get("business_functions", [])}
    return [Candidate(i["id"], display_name(i["name"]), " ".join(str(i.get("description", "")).split()),
                      bf_names.get(i.get("business_function"), i.get("business_function")))
            for i in org.get("initiatives", [])]


class Discovery(BaseModel):
    statement: str = Field(description="One redacted, generalisable sentence stating the fact.")
    call_seq: int = Field(description="The [call N] number where the Agent first acted on or stated the fact.")


class Classification(BaseModel):
    """What the classifier stores for a Session (after validation and redaction)."""
    summary: str
    initiative_id: str
    complexity: Literal["low", "med", "high"]
    discoveries: list[Discovery] = Field(default_factory=list)


def _schema(ids: list[str]) -> type[BaseModel]:
    """The response schema, with initiative_id constrained to the known ids so an
    unknown id fails validation and glm.chat_json asks again."""
    return create_model(
        "SessionClassification",
        summary=(str, Field(description="One redacted line (max ~20 words) saying what the Session did.")),
        initiative_id=(Literal[tuple(ids)], Field(description="The id of the Initiative this Session served.")),
        complexity=(Literal["low", "med", "high"], Field(description="How much judgement the work needed.")),
        discoveries=(list[Discovery], Field(default_factory=list, max_length=MAX_DISCOVERIES + 2)),
    )


SYSTEM = """You classify one AI Agent Session from a company's telemetry. A Session is one continuous run of an Agent by one Member toward one goal. You read its transcript and return four things.

1. summary: one line, at most 20 words, saying what the Session did. Redact it: no personal names, emails, member ids, credentials, hostnames, bucket names, ticket numbers or file contents. Describe the work generically ("Prepared a lifecycle rule for one storage bucket", "Fixed a typo in a postmortem").

2. initiative_id: the business goal this Session served, chosen from the Initiatives listed below (each is shown with the Business Function that owns it). You must pick one of the listed ids. Decide from the evidence, in this order:
   a. The work actually done: which docs, pages, repos, tickets and systems the Agent opened, and what it changed or produced. Resources that belong to one Initiative's area are the strongest evidence.
   b. The goal the Member stated in the request.
   c. The Session context: the Member's Team and Business Function. Teams mostly work on the Initiatives of their own Business Function and area, so an Initiative owned by a different Business Function, or clearly outside the Team's area, needs clear evidence from (a) or (b).
   Requests are often worded loosely: they borrow another Initiative's vocabulary, mention another area's system in passing, or are a quick lookup or question with little detail. Do not match on a keyword or an incidental tool. When the request alone could fit several Initiatives, choose the one that both the resources read and the Team's area point to. Two Initiatives in the same Business Function are told apart by the deliverable and the resources, not by shared words.

3. complexity: judge the TASK (how much the work needed), not how smoothly this Agent did it or whether it succeeded.
   - low: trivial or mechanical work a small model could do: a typo or wording fix, a one-line change, a lookup, a short summary or reformat.
   - med: ordinary multi-step work in one area: a normal bug fix or failing test, a feature slice, a config or plan that combines facts from several docs or files.
   - high: work needing real judgement: cross-service design, hard debugging with unclear cause, a large refactor, analysis across many sources.

4. discoveries: facts the Agent WORKED OUT during this Session that it did not have at the start. Only two signs count:
   (a) an attempt failed and a later attempt succeeded because the Agent changed something: record what the working attempt needed, including the exact working value (flag, env var value, argument form) that made it succeed;
   (b) after searching or probing, an answer finally turned up in a tool result that the task and docs did not state up front.
   Each Discovery is ONE sentence, generalisable and reusable by a future Agent on the same work, redacted (no secrets or personal data), stated as a fact about the system, e.g. "The migration script needs STORAGE_ENV=staging set." Not "I ran it and it worked".
   call_seq is the [call N] number of the Call where the Agent first acted on the fact (usually the Call right after the failing result).
   Do NOT record: what the task asked for; facts the Agent simply read in the docs or files it opened on purpose; the Agent's own plan or result; a failure that was never resolved; guesses. Most Sessions have NO Discoveries: return an empty list unless sign (a) or (b) is clearly in the transcript. At most """ + str(MAX_DISCOVERIES) + """.

Never output dollar figures."""


def _user_prompt(transcript: str, cands: list[Candidate], context: dict | None) -> str:
    lines = ["Initiatives (id: name [owning Business Function] — description):"]
    lines += [f"- {c.initiative_id}: {c.name}" + (f" [{c.business_function}]" if c.business_function else "")
              + f" — {c.description}" for c in cands]
    if context:
        ctx = ", ".join(f"{k}={v}" for k, v in context.items() if v)
        if ctx:
            lines += ["", f"Session context: {ctx}"]
    lines += ["", "Transcript ([call N] = the Call it belongs to; long tool results are truncated):", transcript]
    return "\n".join(lines)


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_SECRET = re.compile(r"\b(?:sk|pk|rk|ghp|gho|xox[abp])[-_][A-Za-z0-9_-]{12,}\b|\bAKIA[0-9A-Z]{16}\b"
                     r"|\b(?:eyJ[\w-]{10,}\.){2}[\w-]{10,}\b")
_KEYVAL = re.compile(r"\b((?:api[_-]?key|token|secret|password|passwd|pwd)\s*[=:]\s*)\S+", re.I)
# 32+ chars of hex/base64 with both letters and digits (hyphenated slugs such as
# rule ids don't match, since '-' is not in the class).
_LONG_TOKEN = re.compile(r"\b(?=[A-Za-z0-9+/=]*\d)(?=[A-Za-z0-9+/=]*[A-Za-z])[A-Za-z0-9+/=]{32,}")


def redact(text: str) -> str:
    """Scrub emails, credentials and long opaque tokens. Env-var names and values
    like STORAGE_ENV=staging are kept: they are the point of a Discovery."""
    t = " ".join(str(text).split())
    t = _EMAIL.sub("[email]", t)
    t = _SECRET.sub("[secret]", t)
    t = _KEYVAL.sub(lambda m: m.group(1) + "[secret]", t)
    t = _LONG_TOKEN.sub("[redacted]", t)
    return t


def _clean(raw: BaseModel, max_seq: int | None) -> Classification:
    discoveries, seen = [], set()
    for d in raw.discoveries[:MAX_DISCOVERIES]:
        statement = redact(d.statement).strip()
        if not statement or statement.lower() in seen:
            continue
        seen.add(statement.lower())
        seq = max(0, d.call_seq)
        if max_seq is not None:
            seq = min(seq, max_seq)
        discoveries.append(Discovery(statement=statement[:300], call_seq=seq))
    summary = redact(raw.summary).strip()
    return Classification(summary=summary[:240], initiative_id=raw.initiative_id, complexity=raw.complexity,
                          discoveries=discoveries)


def classify_transcript(transcript: str, cands: list[Candidate] | None = None, *, context: dict | None = None,
                        max_seq: int | None = None, tier: str | None = None,
                        thinking: bool | None = None) -> Classification:
    """Classify one Session from its rendered transcript. One model call (chat_json
    re-asks up to twice on invalid JSON or an unknown Initiative id).

    This is the function the accuracy eval (ticket 08) can call directly.
    `context` is non-content Session telemetry shown to the model (team,
    business function). `max_seq` clamps Discovery call_seq to the Session."""
    cands = cands if cands is not None else candidates()
    if not cands:
        raise ValueError("no candidate Initiatives (data/company/org.yaml missing?)")
    schema = _schema([c.initiative_id for c in cands])
    raw = glm.chat_json([{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": _user_prompt(transcript, cands, context)}],
                        schema=schema, tier=tier, temperature=0.0, max_tokens=1500,
                        **({} if thinking is None else {"thinking": thinking}))
    return _clean(raw, max_seq)
