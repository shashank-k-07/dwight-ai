"""Drafter internals (ticket 12, build-spec §4.6.3). Used by stages/draft.py.

Two kinds of Draft:
  * initiative doc: one consolidated doc for an Initiative's common path. The
    source docs are re-fetched fresh from company-docs/ by resource_id (ADR 0008),
    never from stored prompts. The model condenses each source doc into one section,
    in parallel, under a token budget that code sets and checks. Code writes the
    header and the source links.
  * memory file: one instruction-style line per repeated Discovery, one file per
    Initiative. The model only rewords the stored statement; code keeps the
    statement as written if the rewrite drops a literal (an env var, a flag, a code).

The model never sees a dollar figure and never writes one (ADRs 0006, 0007).

Token counter: count_tokens() = len(text) // 4, the same deterministic chars/4
rule that ingest (ingest/otlp.py) uses for tool results without a
dwight.tool.result_tokens attribute and that the fixtures use.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from dwight import company, config, glm

CHARS_PER_TOKEN = 4
MAX_SUMMARIES = 30
MAX_DISCOVERIES = 60
# Aim a little under the hard budget: the model's own sense of length is loose.
AIM = 0.9
SECTION_SLACK = 1.1       # a section may run 10% over its share before we ask for a cut
MAX_REVISIONS = 2
REVIEW_PASSES = 1         # self-review turns per section (put back exact values the first pass dropped)


def count_tokens(text: str) -> int:
    """Deterministic token count: len(text) // 4 (chars/4, as ingest does)."""
    return len(text) // CHARS_PER_TOKEN


# ---------------------------------------------------------------- source docs

@dataclass(frozen=True)
class SourceDoc:
    resource_id: str
    title: str
    text: str

    @property
    def tokens(self) -> int:
        return count_tokens(self.text)


def fetch_source_doc(resource_id: str) -> SourceDoc | None:
    """Re-fetch one common-path resource from where it lives (company-docs/ for the
    demo). None for anything that isn't a company doc on disk (repo files, Perch pages)."""
    if not resource_id.startswith("company-docs/"):
        return None
    path = company.company_doc_path(resource_id).resolve()
    root = config.COMPANY_DOCS_DIR.resolve()
    if root not in path.parents or not path.is_file():
        return None
    text = path.read_text()
    return SourceDoc(resource_id, doc_title(text, resource_id), text)


def fetch_source_docs(resource_ids: list[str]) -> tuple[list[SourceDoc], list[str]]:
    """(fetched docs, resource ids that couldn't be fetched)."""
    docs, skipped = [], []
    for rid in resource_ids:
        d = fetch_source_doc(rid)
        (docs.append(d) if d else skipped.append(rid))
    return docs, skipped


def doc_title(text: str, resource_id: str) -> str:
    m = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    return m.group(1) if m else Path(resource_id).stem.replace("-", " ").capitalize()


# ---------------------------------------------------------------- initiative doc

@dataclass
class DocContext:
    """What the model is told about the Initiative. Only derived data: the Initiative's
    name and description, Session summaries and Discoveries (never raw prompts)."""
    initiative_id: str
    name: str
    description: str | None
    summaries: list[str]
    discoveries: list[str]
    readers: int                  # Sessions that read the whole common path
    analysed: int                 # Sessions analysed for the Initiative
    path_tokens: int              # tokens of one read of the common path
    tier: str | None = None
    workers: int = 4
    log: list[str] = field(default_factory=list)


def header(ctx: DocContext, docs: list[SourceDoc]) -> str:
    links = ", ".join(f"[{d.title}]({d.resource_id})" for d in docs)
    return (f"# {ctx.name}: initiative doc\n\n"
            f"Written by Dwight for Agents working on {ctx.name}. {ctx.readers} of {ctx.analysed} Sessions "
            f"read the same {len(docs)} docs to get started (about {ctx.path_tokens:,} tokens each time). "
            f"This doc keeps only what those Sessions needed, with exact values copied from the sources. "
            f"For anything not covered here, open the linked source.\n\nSources: {links}\n")


def section_heading(doc: SourceDoc) -> str:
    return f"## {doc.title}\n\nSource: [{doc.resource_id}]({doc.resource_id})\n\n"


def section_budgets(docs: list[SourceDoc], target_tokens: int, fixed_tokens: int) -> list[int]:
    """Split what's left of the target (after the header and section headings) across
    the docs in proportion to their size."""
    room = max(int(target_tokens * AIM) - fixed_tokens, 50 * len(docs))
    total = sum(d.tokens for d in docs) or 1
    return [max(int(room * d.tokens / total), 50) for d in docs]


SYSTEM = """You are Dwight's Drafter. You condense a company's internal docs into one consolidated initiative doc that coding Agents load into their context before they start a task for one Initiative. The Agents can't ask follow-up questions, so every value they need must be written out exactly. They pay for every token, so everything else must go.

Rules:
- Keep only what the Sessions described below actually needed to do their work.
- Copy exact values verbatim, character for character: numbers, prices, thresholds, day counts, sizes with units, storage classes, bucket/service/team names, rule id formats, command syntax and flags, exception/override codes and their precedence, owners and their @handles.
- Keep lookup tables the Sessions would consult (schedules, price sheets, inventories, owner lists), condensed: drop only columns and rows that are clearly irrelevant to this work.
- Drop history, background, rationale, incident stories, comms templates, revision history, FAQs that repeat the body, and processes these Sessions never touched.
- Terse markdown: `###` subheadings, bullets and compact tables. No introduction, no conclusion, no filler.
- End each `###` subheading with the source section it came from, like `### Override codes (§5.3)`.
- The Sessions' Discoveries are listed only to show what they needed. Do not restate them: facts that aren't in this doc go in a separate memory file. The one exception: if a Discovery directly contradicts a statement in THIS doc, add one line starting with `Note:` right after that statement, saying what the Sessions found instead.
- Always finish the section: never stop mid-table or mid-sentence. If space is short, drop whole low-value parts instead.
- Never write dollar estimates of your own. Prices and costs that appear in the doc are values to copy, not to compute."""


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {s}" for s in items) if items else "- (none recorded)"


def section_messages(ctx: DocContext, doc: SourceDoc, budget: int) -> list[dict]:
    user = (f"Initiative: {ctx.name} (id {ctx.initiative_id})\n"
            f"Description: {ctx.description or 'none'}\n\n"
            f"What the Sessions did (one-line summaries):\n{_bullets(ctx.summaries)}\n\n"
            f"What the Sessions found out along the way (Discoveries):\n{_bullets(ctx.discoveries)}\n\n"
            f"Source doc `{doc.resource_id}` (\"{doc.title}\", about {doc.tokens:,} tokens):\n"
            f"<<<DOC\n{doc.text}\nDOC>>>\n\n"
            f"Write this doc's section of the consolidated initiative doc. Output only the section body, "
            f"starting at the first `###` subheading (no `#` or `##` heading, no source line: Dwight adds those). "
            f"Hard limit: {budget:,} tokens, about {budget * CHARS_PER_TOKEN:,} characters. "
            f"Use the room for exact values the Sessions needed, not for prose.")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def clean_section(text: str) -> str:
    """Strip a wrapping code fence and any leading #/## headings or Source: line."""
    t = text.strip()
    fence = re.match(r"^```(?:markdown|md)?\s*\n(.*?)\n```$", t, re.S)
    if fence:
        t = fence.group(1).strip()
    lines = t.splitlines()
    while lines and (re.match(r"^#{1,2}\s", lines[0]) or lines[0].lower().startswith("source:") or not lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines).strip()


def looks_truncated(text: str) -> bool:
    """A reply cut off by the output limit: an open code fence, or a last line that is a
    half-written table row."""
    if text.count("```") % 2:
        return True
    last = text.rstrip().splitlines()[-1].strip() if text.strip() else ""
    return last.startswith("|") and not last.endswith("|")


def drop_dangling(text: str) -> str:
    """Last resort for a truncated section: drop the half-written last line."""
    lines = text.rstrip().splitlines()
    if lines and looks_truncated(text) and not text.count("```") % 2:
        lines.pop()
    return "\n".join(lines)


def review_prompt(budget: int, used: int) -> str:
    return (f"Now check that section against the source doc, line by line. Which exact values would an Agent "
            f"doing these Sessions' work need that the section leaves out: prices or rates used in calculations, "
            f"thresholds, day counts, sizes, codes and their precedence, command syntax and flags, names, owners "
            f"and @handles, table rows? Put them back. Remove anything the Sessions didn't need. The section is "
            f"{used:,} tokens and may use up to {budget:,} tokens (about {budget * CHARS_PER_TOKEN:,} characters). "
            f"Reply with the complete revised section only.")


def write_section(ctx: DocContext, doc: SourceDoc, budget: int) -> str:
    """One section: a first pass, then REVIEW_PASSES self-review turns that put back exact
    values the first pass dropped. Each turn is held to the budget (with revisions); a
    review that can't be brought under budget falls back to the previous version."""
    msgs = section_messages(ctx, doc, budget)
    text, raw, msgs, ok = _fit(ctx, doc, msgs, budget)
    for _ in range(REVIEW_PASSES if ok else 0):
        msgs2 = msgs + [{"role": "assistant", "content": raw},
                        {"role": "user", "content": review_prompt(budget, count_tokens(text))}]
        text2, raw2, msgs2, ok2 = _fit(ctx, doc, msgs2, budget)
        if not ok2:
            ctx.log.append(f"{doc.resource_id}: review over budget, kept the first pass")
            break
        text, raw, msgs = text2, raw2, msgs2
    return text


def _fit(ctx: DocContext, doc: SourceDoc, msgs: list[dict], budget: int) -> tuple[str, str, list[dict], bool]:
    """Ask, then revise until the reply is complete and within budget.
    Returns (section, raw reply, messages before that reply, ok)."""
    text = raw = ""
    for attempt in range(MAX_REVISIONS + 1):
        raw = glm.chat(msgs, tier=ctx.tier, temperature=0.2, max_tokens=max(4 * budget + 2048, 4096))
        text = clean_section(raw)
        n = count_tokens(text)
        cut = bool(text) and looks_truncated(text)
        if text and not cut and n <= budget * SECTION_SLACK:
            return text, raw, msgs, True
        if attempt == MAX_REVISIONS:
            break
        if not text:
            fix = "That reply was empty. Write the section now."
        elif cut:
            fix = (f"That section was cut off before the end. Write the whole section again, complete, in under "
                   f"{budget:,} tokens (about {budget * CHARS_PER_TOKEN:,} characters).")
        else:
            fix = (f"That section is {n:,} tokens; the hard limit is {budget:,} tokens "
                   f"(about {budget * CHARS_PER_TOKEN:,} characters). Rewrite it under the limit. Cut prose, "
                   f"background and rows the Sessions didn't need first; keep every exact value they did need.")
        ctx.log.append(f"{doc.resource_id}: revision {attempt + 1} ({n} tokens, budget {budget})")
        msgs = msgs + [{"role": "assistant", "content": raw}, {"role": "user", "content": fix}]
    return drop_dangling(text), raw, msgs, False


def assemble(ctx: DocContext, docs: list[SourceDoc], sections: list[str]) -> str:
    parts = [header(ctx, docs)]
    for d, s in zip(docs, sections):
        parts.append(section_heading(d) + s.strip() + "\n")
    return "\n".join(parts)


def build_initiative_doc(ctx: DocContext, docs: list[SourceDoc], target_tokens: int) -> str:
    """The consolidated initiative doc, at most `target_tokens` if the model can manage it
    (the caller checks and reports). Sections are written in parallel."""
    fixed = count_tokens(header(ctx, docs)) + sum(count_tokens(section_heading(d)) for d in docs)
    budgets = section_budgets(docs, target_tokens, fixed)
    with ThreadPoolExecutor(max_workers=max(1, min(ctx.workers, len(docs)))) as pool:
        sections = list(pool.map(lambda db_: write_section(ctx, *db_), zip(docs, budgets)))
    content = assemble(ctx, docs, sections)
    # Whole doc still over target: one more cut on the sections furthest over their share.
    over = count_tokens(content) - target_tokens
    if over > 0:
        order = sorted(range(len(docs)), key=lambda i: count_tokens(sections[i]) - budgets[i], reverse=True)
        for i in order:
            if over <= 0:
                break
            tighter = max(int((count_tokens(sections[i]) - over) * AIM), 50)
            ctx.log.append(f"{docs[i].resource_id}: whole doc {over} tokens over, re-cut to {tighter}")
            sections[i] = write_section(ctx, docs[i], tighter)
            content = assemble(ctx, docs, sections)
            over = count_tokens(content) - target_tokens
    return content


# ---------------------------------------------------------------- memory file

class MemoryLine(BaseModel):
    id: int
    line: str


class MemoryLines(BaseModel):
    lines: list[MemoryLine]


MEMORY_SYSTEM = """You turn facts that coding Agents had to find out by trial and error into memory-file entries. Each entry is ONE line, written as an instruction an Agent can act on directly ("Set X before running Y", "Pass A, not B"). Keep every literal exactly as given: env vars and their values, commands, flags, codes, names. Add nothing that isn't in the fact. No dollar figures."""


def _literals(statement: str) -> set[str]:
    """Literals a rewrite must keep: KEY=value pairs, UPPER_SNAKE names, --flags, `code`."""
    lits = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*=[^\s,;.)]+", statement))
    lits |= set(re.findall(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b", statement))
    lits |= set(re.findall(r"(?<!\w)--[a-z][a-z0-9-]*", statement))
    lits |= set(re.findall(r"`([^`]+)`", statement))
    return lits


def one_line(text: str) -> str:
    t = " ".join((text or "").split())
    return re.sub(r"^[-*]\s+", "", t).strip()


def memory_lines(statements: list[str], *, use_glm: bool = True, tier: str | None = None,
                 log: list[str] | None = None) -> list[str]:
    """One instruction-style line per repeated Discovery statement, same order.
    Falls back to the stored statement (already a single line, per ticket 11) when the
    model is off, fails, or drops a literal."""
    base = [one_line(s) for s in statements]
    if not use_glm or not statements:
        return base
    listing = "\n".join(f"{i}. {s}" for i, s in enumerate(base))
    try:
        out = glm.chat_json([{"role": "system", "content": MEMORY_SYSTEM},
                             {"role": "user", "content": f"Facts:\n{listing}\n\nReturn one entry per fact, "
                                                         f"with the fact's number as `id`."}],
                            schema=MemoryLines, tier=tier)
    except Exception as e:  # noqa: BLE001 - the stored statement is a fine memory line on its own
        if log is not None:
            log.append(f"memory rewrite failed ({type(e).__name__}); kept the statements")
        return base
    by_id = {m.id: one_line(m.line) for m in out.lines}
    lines = []
    for i, s in enumerate(base):
        new = by_id.get(i, "")
        keep = new and all(lit in new for lit in _literals(s)) and "$" not in new
        lines.append(new if keep else s)
    return lines


def memory_file(name: str, lines: list[str]) -> str:
    body = "\n".join(f"- {line}" for line in lines)
    return (f"# {name}: memory file\n\n"
            f"Load this into the Agent's context for {name} work. Each line is something earlier "
            f"Sessions each had to find out by trial and error.\n\n{body}\n")
