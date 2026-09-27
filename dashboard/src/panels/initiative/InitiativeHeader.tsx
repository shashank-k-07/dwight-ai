"use client";
// Panel: Initiative header. Owner: 06. GET /api/initiatives/{id}
import Link from "next/link";
import { Money } from "@/components/Money";
import { useApi } from "@/lib/api";
import type { Initiative } from "@/lib/contract";

export default function InitiativeHeader({ initiativeId }: { initiativeId: string }) {
  const { data, error } = useApi<Initiative>(`/api/initiatives/${initiativeId}`);
  if (error) return <p className="panel-error">{error}</p>;
  if (!data) return <h1>…</h1>;
  return (
    <div className="page-head">
      <p className="muted small"><Link href="/initiatives">Initiatives</Link> / {data.initiative_id}</p>
      <h1>
        {data.name} {data.source === "fixture" && <span className="badge badge-fixture">fixture data</span>}
      </h1>
      {data.description && <p className="muted">{data.description}</p>}
      <p>
        {data.business_function ?? "—"} · {data.session_count.toLocaleString()} Sessions · Spend{" "}
        <Money value={data.spend} />
      </p>
    </div>
  );
}
