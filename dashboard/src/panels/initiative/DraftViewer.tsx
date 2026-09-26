"use client";
// Panel: Draft viewer + download. Owner: 12. GET /api/initiatives/{id}/drafts, /api/drafts/{id}/download
import { Panel } from "@/components/Panel";
import { useApi } from "@/lib/api";
import type { DraftList } from "@/lib/contract";

export default function DraftViewer({ initiativeId }: { initiativeId: string }) {
  const { data, error, loading } = useApi<DraftList>(`/api/initiatives/${initiativeId}/drafts`);
  if (data && data.items.length === 0) return null;
  return (
    <Panel title="Drafts" source={data?.source} loading={loading} error={error}>
      {data?.items.map((d) => (
        <div key={d.draft_id} id={`draft-${d.draft_id}`} className="draft">
          <div className="rec-head">
            <h3>{d.title}</h3>
            <a className="button" href={`/api/drafts/${d.draft_id}/download`} download={d.filename}>Download {d.filename}</a>
          </div>
          <p className="small muted">{d.tokens.toLocaleString()} tokens{d.source_tokens ? ` (replaces ${d.source_tokens.toLocaleString()} tokens of source docs)` : ""}</p>
          <pre className="markdown">{d.content}</pre>
        </div>
      ))}
    </Panel>
  );
}
