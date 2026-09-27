// Initiatives screen. Composition only. Both panels read the Business Function from ?bf=, so they
// sit inside Suspense (useSearchParams).
import { Suspense } from "react";
import InitiativesTable from "@/panels/initiatives/InitiativesTable";
import InitiativesTreemap from "@/panels/initiatives/InitiativesTreemap";

export default function InitiativesPage() {
  return (
    <>
      <h1>Initiatives</h1>
      <Suspense>
        <InitiativesTreemap />
        <InitiativesTable />
      </Suspense>
    </>
  );
}
