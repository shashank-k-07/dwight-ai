"use client";
// Panel: Draft viewer + download. Owner: 12.
// GET /api/initiatives/{id}/drafts, /api/drafts/{id}/download, and the Initiative's Recommendations
// (for the Estimated Saving of the Recommendation each Draft is attached to).
// Each Draft's element id is `draft-<draft_id>`: the Recommendations panel links to it.
import { useState, type CSSProperties, type ReactNode } from "react";
import { Money } from "@/components/Money";
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import type { Draft, DraftList, RecommendationList } from "@/lib/contract";

// ---- Minimal markdown renderer (React nodes, no HTML injection) ----------------
// Headings, paragraphs, "- " lists, tables, fenced code, **bold**, `code`, [links](target).
// Draft links point at source docs (e.g. company-docs/x.md), which live in the Customer's
// tenant, so they render as labelled text with the target as a tooltip.

function inline(text: string, key: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g).map((part, i) => {
    const k = `${key}-${i}`;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={k}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return <code key={k}>{part.slice(1, -1)}</code>;
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part);
    if (link) return <span key={k} className="draft-link" title={link[2]} style={{ textDecoration: "underline dotted" }}>{link[1]}</span>;
    return part;
  });
}

const isRow = (l: string) => /^\s*\|.*\|\s*$/.test(l);
const isSep = (l: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
const cells = (l: string) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const out: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const k = `b${i}`;
    if (!line.trim()) { i++; continue; }
    if (line.trim().startsWith("```")) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) body.push(lines[i++]);
      i++;
      out.push(<pre key={k} className="markdown" style={{ maxHeight: "none" }}>{body.join("\n")}</pre>);
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      const level = Math.min(h[1].length + 2, 6); // the panel owns h2; the doc's # becomes h3
      const Tag = `h${level}` as "h3" | "h4" | "h5" | "h6";
      out.push(<Tag key={k} style={{ margin: "14px 0 6px" }}>{inline(h[2], k)}</Tag>);
      i++;
      continue;
    }
    if (isRow(line) && i + 1 < lines.length && isSep(lines[i + 1])) {
      const head = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && isRow(lines[i])) rows.push(cells(lines[i++]));
      out.push(
        <table key={k} className="table compact" style={{ margin: "6px 0 10px", fontSize: 12.5 }}>
          <thead><tr>{head.map((c, j) => <th key={j}>{inline(c, `${k}h${j}`)}</th>)}</tr></thead>
          <tbody>{rows.map((r, ri) => <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, `${k}r${ri}c${j}`)}</td>)}</tr>)}</tbody>
        </table>,
      );
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ""));
      const List = ordered ? "ol" : "ul";
      out.push(<List key={k} style={{ margin: "4px 0 8px" }}>{items.map((it, j) => <li key={j}>{inline(it, `${k}-${j}`)}</li>)}</List>);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|\s*([-*]|\d+\.)\s+)/.test(lines[i]) && !isRow(lines[i])) para.push(lines[i++]);
    if (!para.length) para.push(lines[i++]); // a stray table row without a header
    out.push(<p key={k} style={{ margin: "6px 0" }}>{inline(para.join(" "), k)}</p>);
  }
  return <>{out}</>;
}

// ---- Panel ------------------------------------------------------------------------

const docBox: CSSProperties = {
  background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 8,
  padding: "4px 14px 10px", maxHeight: 520, overflow: "auto", fontSize: 13.5,
};

const TYPE_LABEL: Record<Draft["type"], string> = { initiative_doc: "Initiative doc", memory: "Memory file" };

function DraftCard({ d, recs }: { d: Draft; recs: RecommendationList | null }) {
  const [raw, setRaw] = useState(false);
  const rec = recs?.items.find((r) => r.draft_id === d.draft_id || r.recommendation_id === d.recommendation_id);
  const entries = d.type === "memory" ? d.content.split("\n").filter((l) => /^\s*-\s+/.test(l)).length : 0;
  const share = d.source_tokens ? Math.round((d.tokens / d.source_tokens) * 100) : null;
  return (
    <div id={`draft-${d.draft_id}`} className="draft">
      <div className="rec-head">
        <h3>
          {d.title} <span className="chip">{TYPE_LABEL[d.type]}</span>
        </h3>
        <span>
          <button className="button" type="button" onClick={() => setRaw((v) => !v)}
            style={{ background: "transparent", color: "var(--accent)", border: "1px solid var(--border)", marginRight: 8 }}>
            {raw ? "Rendered" : "Markdown"}
          </button>
          <a className="button" href={`/api/drafts/${d.draft_id}/download`} download={d.filename}>Download {d.filename}</a>
        </span>
      </div>
      <p className="small muted">
        {d.tokens.toLocaleString()} tokens
        {d.source_tokens ? `, ${share}% of the ${d.source_tokens.toLocaleString()} tokens of source docs it replaces` : ""}
        {d.type === "memory" ? `, ${entries} ${entries === 1 ? "entry" : "entries"}, one per repeated Discovery` : ""}
        {d.source_resource_ids.length > 0 && <> · Sources: {d.source_resource_ids.map((s) => <code key={s} style={{ marginRight: 6 }}>{s}</code>)}</>}
      </p>
      {rec && (
        <p className="small">
          Attached to <strong>{rec.title}</strong> ({rec.practice.title}) · <Money value={rec.saving} size="sm" /> per month
        </p>
      )}
      {raw ? <pre className="markdown">{d.content}</pre> : <div style={docBox}><Markdown source={d.content} /></div>}
    </div>
  );
}

export default function DraftViewer({ initiativeId }: { initiativeId: string }) {
  const { data, error, loading } = useApi<DraftList>(`/api/initiatives/${initiativeId}/drafts`);
  const recs = useApi<RecommendationList>(`/api/initiatives/${initiativeId}/recommendations`);
  if (data && data.items.length === 0) return null;
  return (
    <Panel title="Drafts" source={data?.source} loading={loading} error={error}>
      <p className="small muted">
        Written by Dwight for this Initiative. Put them in place yourself: load the initiative doc and the memory file
        into the Agents&apos; context. Savings are Estimated until a before/after run exists.
      </p>
      {data?.items.map((d) => <DraftCard key={d.draft_id} d={d} recs={recs.data} />)}
    </Panel>
  );
}
