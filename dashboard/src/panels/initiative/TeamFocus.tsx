"use client";
// Panel: the Team highlight on Initiative detail (?team=, from the Overview's Initiative x Team
// chart). GET /api/initiatives/{id} (teams: additive contract field). Switch or clear the Team here;
// the Recommendations and Sessions panels read the same ?team=.
import Link from "next/link";
import { Money } from "@/components/Money";
import { useApi } from "@/lib/api";
import type { Initiative } from "@/lib/contract";
import { shareOf } from "@/lib/simulation";
import { initiativeHref } from "@/panels/overview/SpendByInitiative";

export default function TeamFocus({ initiativeId, team }: { initiativeId: string; team: string }) {
  const { data } = useApi<Initiative>(`/api/initiatives/${initiativeId}`);
  if (!data) return null;
  const t = data.teams?.find((x) => x.team === team);
  return (
    <div className="team-focus">
      <div>
        <span className="stat-label">Team</span> <strong>{team}</strong>
        {t ? (
          <span> · <Money value={t.spend} /> of this Initiative&apos;s <Money value={data.spend} size="sm" /> Spend
            ({shareOf(t.spend, data.spend).toFixed(0)}%) · {t.session_count.toLocaleString()} of {data.session_count.toLocaleString()} Sessions</span>
        ) : <span className="muted"> · no Sessions in this Initiative</span>}
      </div>
      <div className="small">
        {data.teams?.filter((x) => x.team !== team).map((x) => (
          <Link key={x.team} className="chip" href={initiativeHref(initiativeId, x.team)}>{x.team}</Link>
        ))}
        <Link className="chip" href={initiativeHref(initiativeId)}>All Teams</Link>
      </div>
    </div>
  );
}
