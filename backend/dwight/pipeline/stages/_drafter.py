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


# ---------------------------------------------------------------- tables and the columns rules depend on
#
# A lookup table often carries a column that a rule in ANOTHER section or doc depends on:
# the tiering policy's small-objects override reads the dashboard's "Avg object" column,
# the runbook's scope rule reads its "Policy compliant" column. A section is condensed
# from its own doc alone, so the model can't see that dependency and may drop the column
# (Draft v1 did, and the after runs then mispriced the small-object bucket). Code finds
# these columns from the docs' prose, tells the model to keep them, and puts back any
# the model still drops (repair_tables), with the source's values for the rows it kept.

ABBREVIATIONS = {"avg": "average", "no": "number", "num": "number", "pct": "percent", "min": "minimum",
                 "max": "maximum", "qty": "quantity", "req": "required", "env": "environment"}
_HEADER_NOISE = {"the", "a", "an", "of", "per", "in", "usd", "tb", "gb", "mb", "kb", "eur", "days", "day"}


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]
    section: str          # the `##` section it sits in ("" before the first one)
    start: int            # line index of the header row
    end: int              # line index after the last row


def _cells(line: str) -> list[str]:
    s = line.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") else s
    return [c.strip() for c in s.split("|")]


def _is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?", line.strip()))


def parse_tables(text: str) -> list[Table]:
    """Every markdown table (header row + separator + rows) in `text`."""
    lines = text.splitlines()
    tables, section, i = [], "", 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^##\s", line):
            section = line.lstrip("#").strip()
        if line.strip().startswith("|") and i + 1 < len(lines) and _is_separator(lines[i + 1]):
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            tables.append(Table(_cells(line), [_cells(r) for r in lines[i + 2:j]], section, i, j))
            i = j
            continue
        i += 1
    return tables


def _plain(s: str) -> str:
    return re.sub(r"[*`_\"]", "", s).strip()


def _words(s: str) -> list[str]:
    return [ABBREVIATIONS.get(w, w) for w in re.findall(r"[a-z0-9]+", _plain(s).lower())]


def _content_words(header: str) -> list[str]:
    return [w for w in _words(header) if w not in _HEADER_NOISE]


def _prose_by_section(text: str) -> list[tuple[str, str]]:
    """(section, prose) pairs: each `##` section's text with its tables removed."""
    out, section, buf = [], "", []
    for line in text.splitlines():
        if re.match(r"^##\s", line):
            out.append((section, "\n".join(buf)))
            section, buf = line.lstrip("#").strip(), []
        elif not line.strip().startswith("|"):
            buf.append(line)
    out.append((section, "\n".join(buf)))
    return out


def _sentences(prose: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n(?=\s*[-*#>\d])|\n\s*\n", prose) if s.strip()]


def _mentions(sentence: str, header: str) -> bool:
    """Does this sentence refer to the column `header`? A multi-word header counts when its
    content words appear in order with at most one word between them ("Avg object" ~
    "average object size"); a one-word header only when quoted ("Objects", `Objects`)."""
    want = _content_words(header)
    if not want:
        return False
    if len(want) == 1:
        h = re.escape(_plain(header))
        return bool(re.search(rf"[\"`]\**{h}\**[\"`]", sentence, re.I))
    got = _words(sentence)
    for start, w in enumerate(got):
        if w != want[0]:
            continue
        pos, ok = start, True
        for nxt in want[1:]:
            window = got[pos + 1:pos + 3]
            if nxt not in window:
                ok = False
                break
            pos = pos + 1 + window.index(nxt)
        if ok:
            return True
    return False


@dataclass(frozen=True)
class ColumnNeed:
    column: str
    evidence: str         # the sentence that depends on it
    evidence_doc: str     # resource_id of the doc that sentence is in


def required_columns(docs: list["SourceDoc"]) -> dict[str, list[tuple[Table, list[ColumnNeed]]]]:
    """{resource_id: [(table, [columns a rule elsewhere depends on])]} over all source docs.
    A sentence in the table's own `##` section (its caption, its notes) doesn't count: that
    describes the table rather than using it."""
    prose = [(doc.resource_id, sec, s) for doc in docs for sec, p in _prose_by_section(doc.text)
             for s in _sentences(p)]
    out: dict[str, list[tuple[Table, list[ColumnNeed]]]] = {}
    for doc in docs:
        for t in parse_tables(doc.text):
            if not t.rows:
                continue
            needs = []
            for col in t.header:
                hit = next(((rid, s) for rid, sec, s in prose
                            if not (rid == doc.resource_id and sec == t.section) and _mentions(s, col)), None)
                if hit:
                    needs.append(ColumnNeed(col, hit[1][:240], hit[0]))
            if needs:
                out.setdefault(doc.resource_id, []).append((t, needs))
    return out


def _norm_cell(s: str) -> str:
    return " ".join(_plain(s).lower().split())


def _match_source(out_table: Table, sources: list[Table]) -> Table | None:
    """The source table an output table was condensed from: most shared column names (at
    least two, and at least half of the output's columns)."""
    have = {_norm_cell(h) for h in out_table.header}
    best, best_n = None, 0
    for t in sources:
        n = len(have & {_norm_cell(h) for h in t.header})
        if n > best_n:
            best, best_n = t, n
    if best is None or best_n < 2 or best_n * 2 < len(have):
        return None
    return best


def _row_line(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def repair_tables(section: str, needs: list[tuple[Table, list[ColumnNeed]]]) -> tuple[str, list[str]]:
    """Put back required columns the model dropped from a table it kept. Values come from the
    source row whose key (the output's first column) matches; a row that can't be matched gets
    `(see source)`. Returns (section, one note per column put back)."""
    if not needs:
        return section, []
    lines, notes = section.splitlines(), []
    sources = [t for t, _ in needs]
    need_by_table = {id(t): [n.column for n in ns] for t, ns in needs}
    for out in reversed(parse_tables(section)):          # bottom-up keeps earlier line numbers valid
        src = _match_source(out, sources)
        if src is None:
            continue
        have = [_norm_cell(h) for h in out.header]
        missing = [c for c in need_by_table[id(src)] if _norm_cell(c) not in have]
        if not missing:
            continue
        src_cols = [_norm_cell(h) for h in src.header]
        key_out = have[0]
        key_src = src_cols.index(key_out) if key_out in src_cols else 0
        by_key = {_norm_cell(r[key_src]): r for r in src.rows if len(r) > key_src}
        header, rows = list(out.header), [list(r) for r in out.rows]
        for col in missing:
            ci = src_cols.index(_norm_cell(col))
            # insert after the nearest earlier source column the output kept, else at the end
            pos = len(header)
            for prev in reversed(src_cols[:ci]):
                if prev in [_norm_cell(h) for h in header]:
                    pos = [_norm_cell(h) for h in header].index(prev) + 1
                    break
            header.insert(pos, col)
            for r in rows:
                s = by_key.get(_norm_cell(r[0])) if r else None
                r.insert(pos, s[ci] if s and len(s) > ci else "(see source)")
            notes.append(f"put back column {col!r}")
        sep = _row_line(["---"] * len(header))
        lines[out.start:out.end] = [_row_line(header), sep] + [_row_line(r) for r in rows]
    return "\n".join(lines), notes


def needs_prompt(needs: list[tuple[Table, list[ColumnNeed]]]) -> str:
    """The instruction listing, per table in this doc, the columns other rules depend on."""
    if not needs:
        return ""
    parts = []
    for t, ns in needs:
        cols = "; ".join(f"`{n.column}` (used by: \"{n.evidence}\")" for n in ns)
        parts.append(f"- Table with columns {' | '.join(t.header)}: keep {cols}")
    return ("Columns that rules, overrides or scoping criteria in these docs depend on. If you keep one of "
            "these tables, keep these columns, with their exact values for every row you keep:\n"
            + "\n".join(parts) + "\n\n")


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
    # {resource_id: [(table, columns other rules depend on)]}, from required_columns()
    column_needs: dict = field(default_factory=dict)


def header(ctx: DocContext, docs: list[SourceDoc]) -> str:
    links = ", ".join(f"[{d.title}]({d.resource_id})" for d in docs)
    return (f"# {ctx.name}: initiative doc\n\n"
            f"Written by Dwight for Agents working on {ctx.name}. {ctx.readers} of {ctx.analysed} Sessions "
            f"read the same {len(docs)} docs to get started (about {ctx.path_tokens:,} tokens each time). "
            f"**This doc replaces those {len(docs)} source docs for {ctx.name} work.** It keeps every rule, "
            f"table and value those Sessions needed, copied exactly from the sources. Work from this doc; "
            f"open a source doc only if a value you need is missing here.\n\n"
            f"Sources (for provenance): {links}\n")


def section_heading(doc: SourceDoc) -> str:
    return f"## {doc.title}\n\nSource: [{doc.resource_id}]({doc.resource_id})\n\n"


def section_budgets(docs: list[SourceDoc], target_tokens: int, fixed_tokens: int) -> list[int]:
    """Split what's left of the target (after the header and section headings) across
    the docs in proportion to their size."""
    room = max(int(target_tokens * AIM) - fixed_tokens, 50 * len(docs))
    total = sum(d.tokens for d in docs) or 1
    return [max(int(room * d.tokens / total), 50) for d in docs]


SYSTEM = """You are Dwight's Drafter. You condense a company's internal docs into one consolidated initiative doc that coding Agents load into their context before they start a task for one Initiative. The doc replaces the source docs: the Agents work from it and open a source only if a value they need is missing, so every rule and value they need must be written out exactly. They pay for every token, so everything else must go.

Rules:
- Keep only what the Sessions described below actually needed to do their work.
- Copy exact values verbatim, character for character: numbers, prices, thresholds, day counts, sizes with units, storage classes, bucket/service/team names, rule id formats, command syntax and flags, exception/override codes and their precedence, owners and their @handles.
- Keep lookup tables the Sessions would consult (schedules, price sheets, inventories, owner lists), condensed: drop only rows that are clearly irrelevant to this work, and only columns that no rule, override, scoping criterion or calculation depends on. A column another doc's rule reads (for example a per-row size, reader or status that decides whether an override applies) must stay, with its values.
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
            f"{needs_prompt(ctx.column_needs.get(doc.resource_id, []))}"
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
            f"and @handles, table rows, table columns that a rule or override depends on? Put them back. Remove anything the Sessions didn't need. The section is "
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
    text, notes = repair_tables(text, ctx.column_needs.get(doc.resource_id, []))
    ctx.log.extend(f"{doc.resource_id}: {n}" for n in notes)
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
    (the caller checks and reports). Sections are written in parallel. Table columns that a
    rule in any of the docs depends on are kept (prompt) and put back if dropped (code)."""
    if not ctx.column_needs:
        ctx.column_needs = required_columns(docs)
    fixed =count_tokens(header(ctx, docs)) + sum(count_tokens(section_heading(d)) for d in docs)
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
