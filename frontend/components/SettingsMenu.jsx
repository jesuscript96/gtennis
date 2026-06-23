"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

// Administración: lo que antes colgaba del final del sidebar.
const SETTINGS = [
  ["/sedes", "Sedes"],
  ["/pistas", "Pistas"],
  ["/divisiones", "Divisiones"],
  ["/rencillas", "Rencillas"],
  ["/contratos", "Contratos"],
  ["/configuracion", "Criterios del motor"],
];

function GearIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 15.5a3.5 3.5 0 100-7 3.5 3.5 0 000 7z"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M19.4 13a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09a1.65 1.65 0 00-1.08-1.51 1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09a1.65 1.65 0 001.51-1.08 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H8a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// align: "left" | "right" (lado de apertura del popover)
// up: abre hacia arriba (para el pie del sidebar)
export default function SettingsMenu({ align = "right", up = false }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const pathname = usePathname();
  const activeHere = SETTINGS.some(([h]) => h === pathname);

  useEffect(() => {
    function onDoc(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    function onEsc(e) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onEsc);
    };
  }, []);

  useEffect(() => setOpen(false), [pathname]);

  return (
    <div className="settings-menu" ref={ref}>
      <button
        type="button"
        className={`gear ${activeHere ? "active" : ""}`}
        onClick={() => setOpen((v) => !v)}
        title="Administración"
        aria-label="Administración"
        aria-expanded={open}
      >
        <GearIcon />
      </button>
      {open && (
        <div className={`settings-pop ${align} ${up ? "up" : "down"}`}>
          <div className="settings-pop-title">Administración</div>
          {SETTINGS.map(([href, label]) => (
            <Link key={href} href={href} className={pathname === href ? "active" : ""}>
              {label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
