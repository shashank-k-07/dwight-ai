// Initiatives screen. Composition only.
import InitiativesTable from "@/panels/initiatives/InitiativesTable";
import WasteByFunction from "@/panels/initiatives/WasteByFunction";

export default function InitiativesPage() {
  return (
    <>
      <h1>Initiatives</h1>
      <WasteByFunction />
      <InitiativesTable />
    </>
  );
}
