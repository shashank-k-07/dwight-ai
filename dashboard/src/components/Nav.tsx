"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/initiatives", label: "Initiatives" },
  { href: "/policy", label: "Policy" },
];

export function Nav() {
  const path = usePathname();
  return (
    <nav className="nav">
      <span className="brand">Dwight</span>
      {LINKS.map((l) => {
        const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
        return (
          <Link key={l.href} href={l.href} className={active ? "active" : ""}>
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}
