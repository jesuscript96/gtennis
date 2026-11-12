"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { getUser } from "../lib/api";
import { dondeEsta } from "../lib/menu";

// Las pestañas de la entrada del menú en la que se está (p. ej. Club: Sedes,
// Pistas, Divisiones…). Con una sola pestaña no sale nada.
export default function SectionTabs() {
  const pathname = usePathname();
  const donde = dondeEsta(pathname, getUser());
  if (!donde || donde.entrada.tabs.length < 2) return null;
  return (
    <nav className="section-tabs" aria-label={donde.entrada.label}>
      {donde.entrada.tabs.map((t) => (
        <Link key={t.href} href={t.href} className={t.href === donde.tab.href ? "on" : ""}
              aria-current={t.href === donde.tab.href ? "page" : undefined}>
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
