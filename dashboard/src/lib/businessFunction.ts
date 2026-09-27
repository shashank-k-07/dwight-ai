"use client";
// The Initiatives screen's Business Function choice, kept in the URL (?bf=Engineering, ?bf=all)
// so the treemap and the table follow one control and the view survives reload / sharing.
// Components using this must sit inside a <Suspense> boundary (useSearchParams).
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

export const ALL = "all";

export function useBusinessFunction(fallback: string | null): [string | null, (bf: string) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const set = useCallback((bf: string) => {
    const q = new URLSearchParams(params.toString());
    q.set("bf", bf);
    router.replace(`${path}?${q.toString()}`, { scroll: false });
  }, [params, router, path]);
  return [params.get("bf") ?? fallback, set];
}
