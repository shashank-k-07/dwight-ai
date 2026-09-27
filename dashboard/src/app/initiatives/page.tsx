// Initiatives screen. Composition only.
import InitiativesTable from "@/panels/initiatives/InitiativesTable";
import InitiativesTreemap from "@/panels/initiatives/InitiativesTreemap";

export default function InitiativesPage() {
  return (
    <>
      <h1>Initiatives</h1>
      <InitiativesTreemap />
      <InitiativesTable />
    </>
  );
}
