// Policy screen. Composition only.
import { Suspense } from "react";
import PolicyEditor from "@/panels/policy/PolicyEditor";

export default function PolicyPage() {
  return (
    <>
      <h1>Policy</h1>
      <Suspense>
        <PolicyEditor />
      </Suspense>
    </>
  );
}
