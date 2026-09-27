"use client";
// Card wrapper every panel uses: title, loading/error state, and a visible
// "fixture" badge when the endpoint is still serving fixture JSON.
import type { ReactNode } from "react";
import { Info } from "@/components/Money";
import type { Source } from "@/lib/contract";

export function Panel({
  title,
  source,
  loading,
  error,
  children,
  actions,
  info,
  id,
}: {
  title: string;
  info?: string;
  id?: string;
  source?: Source;
  loading?: boolean;
  error?: string | null;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className="panel" id={id}>
      <header className="panel-head">
        <h2>{title}{info && <Info>{info}</Info>}</h2>
        <div className="panel-actions">
          {source === "fixture" && <span className="badge badge-fixture" title="This panel is showing committed fixture data, not the store">fixture data</span>}
          {actions}
        </div>
      </header>
      {error ? <p className="panel-error">Couldn&apos;t load: {error}</p> : loading ? <p className="muted">Loading…</p> : children}
    </section>
  );
}

export function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{children}</div>
    </div>
  );
}
