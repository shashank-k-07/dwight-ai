"use client";
// Initiative detail screen. Composition only: one file per panel in src/panels/initiative/.
// Recommendations come first (demo feedback: they are the point of the page). ?team=<Team>
// (from the Overview's Initiative x Team chart) highlights that Team.
import { Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";
import BeforeAfter from "@/panels/initiative/BeforeAfter";
import DraftViewer from "@/panels/initiative/DraftViewer";
import InitiativeHeader from "@/panels/initiative/InitiativeHeader";
import Recommendations from "@/panels/initiative/Recommendations";
import RecurringDiscoveryPanel from "@/panels/initiative/RecurringDiscoveryPanel";
import SessionsList from "@/panels/initiative/SessionsList";
import TeamFocus from "@/panels/initiative/TeamFocus";
import WasteBreakdown from "@/panels/initiative/WasteBreakdown";

function InitiativeDetail() {
  const { id } = useParams<{ id: string }>();
  const team = useSearchParams().get("team");
  return (
    <>
      <InitiativeHeader initiativeId={id} />
      {team && <TeamFocus initiativeId={id} team={team} />}
      <Recommendations initiativeId={id} team={team} />
      <div className="grid2">
        <WasteBreakdown initiativeId={id} />
        <RecurringDiscoveryPanel initiativeId={id} />
      </div>
      <DraftViewer initiativeId={id} />
      <BeforeAfter initiativeId={id} />
      <SessionsList initiativeId={id} team={team} />
    </>
  );
}

export default function InitiativeDetailPage() {
  return (
    <Suspense>
      <InitiativeDetail />
    </Suspense>
  );
}
