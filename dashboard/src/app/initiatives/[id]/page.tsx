"use client";
// Initiative detail screen. Composition only: one file per panel in src/panels/initiative/.
import { useParams } from "next/navigation";
import BeforeAfter from "@/panels/initiative/BeforeAfter";
import DraftViewer from "@/panels/initiative/DraftViewer";
import InitiativeHeader from "@/panels/initiative/InitiativeHeader";
import Recommendations from "@/panels/initiative/Recommendations";
import RecurringDiscoveryPanel from "@/panels/initiative/RecurringDiscoveryPanel";
import SessionsList from "@/panels/initiative/SessionsList";
import WasteBreakdown from "@/panels/initiative/WasteBreakdown";

export default function InitiativeDetailPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <>
      <InitiativeHeader initiativeId={id} />
      <div className="grid2">
        <WasteBreakdown initiativeId={id} />
        <RecurringDiscoveryPanel initiativeId={id} />
      </div>
      <Recommendations initiativeId={id} />
      <DraftViewer initiativeId={id} />
      <BeforeAfter initiativeId={id} />
      <SessionsList initiativeId={id} />
    </>
  );
}
