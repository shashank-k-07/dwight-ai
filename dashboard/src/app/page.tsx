// Overview screen. Composition only: each panel is its own file in src/panels/overview/.
import ClosingNumbers from "@/panels/overview/ClosingNumbers";
import SimulationImpact from "@/panels/overview/SimulationImpact";
import SpendByBusinessFunction from "@/panels/overview/SpendByBusinessFunction";
import SpendByInitiative from "@/panels/overview/SpendByInitiative";
import SpendTotals from "@/panels/overview/SpendTotals";

export default function OverviewPage() {
  return (
    <>
      <h1>Overview</h1>
      <SpendTotals />
      <SimulationImpact />
      <SpendByBusinessFunction />
      <SpendByInitiative />
      <ClosingNumbers />
    </>
  );
}
