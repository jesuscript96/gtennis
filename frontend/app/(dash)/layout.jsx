"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getToken, getUser } from "../../lib/api";
import { canVisit, roleRank } from "../../lib/perms";
import Sidebar from "../../components/Sidebar";
import SettingsMenu from "../../components/SettingsMenu";

export default function DashLayout({ children }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ok, setOk] = useState(false);
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    // Guard por rol: si la ruta exige más nivel del que tiene, al inicio.
    if (!canVisit(pathname)) {
      // El entrenador no tiene panel general: su inicio es su agenda.
      router.replace(roleRank(getUser()) === 1 ? "/mi-agenda" : "/");
      return;
    }
    setOk(true);
  }, [router, pathname]);

  // Cierra el drawer al cambiar de ruta (navegación en móvil).
  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  // Evita el scroll del fondo cuando el drawer está abierto en móvil.
  useEffect(() => {
    document.body.classList.toggle("nav-locked", navOpen);
    return () => document.body.classList.remove("nav-locked");
  }, [navOpen]);

  if (!ok) return null;

  return (
    <div className={`shell${navOpen ? " nav-open" : ""}`}>
      <header className="mobile-topbar">
        <button
          className="hamburger"
          aria-label={navOpen ? "Cerrar menú" : "Abrir menú"}
          aria-expanded={navOpen}
          onClick={() => setNavOpen((v) => !v)}
        >
          <span /><span /><span />
        </button>
        <div className="mobile-brand">G<span>Tennis</span></div>
        <SettingsMenu align="right" />
      </header>

      <div className="nav-scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />

      <Sidebar onNavigate={() => setNavOpen(false)} />

      <main className="content">
        <div className="topbar">
          <SettingsMenu align="right" />
        </div>
        {children}
      </main>
    </div>
  );
}
