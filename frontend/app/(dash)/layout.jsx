"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getToken, getUser, refrescarUsuario } from "../../lib/api";
import { canVisit, inicio } from "../../lib/perms";
import { RUTAS_VIEJAS } from "../../lib/menu";
import Sidebar from "../../components/Sidebar";
import SectionTabs from "../../components/SectionTabs";

// Cada cuánto, como mucho, se vuelven a pedir los permisos al navegar.
const REFRESCO_MS = 30 * 1000;

export default function DashLayout({ children }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ok, setOk] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const ultimo = useRef(0);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    if (RUTAS_VIEJAS[pathname]) {
      router.replace(RUTAS_VIEJAS[pathname]);
      return;
    }
    // Si la ruta no le toca, a su inicio.
    if (!canVisit(pathname)) {
      router.replace(inicio(getUser()));
      return;
    }
    setOk(true);
    // Los permisos se vuelven a pedir al navegar: si dirección le cambia el
    // perfil o una función, lo nota sin cerrar sesión.
    if (Date.now() - ultimo.current > REFRESCO_MS) {
      ultimo.current = Date.now();
      refrescarUsuario().then((u) => {
        window.dispatchEvent(new Event("gt-user"));
        if (!canVisit(pathname, u)) router.replace(inicio(u));
      }).catch(() => {});
    }
  }, [router, pathname]);

  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

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
      </header>

      <div className="nav-scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />

      <Sidebar onNavigate={() => setNavOpen(false)} />

      <main className="content">
        <SectionTabs />
        {children}
      </main>
    </div>
  );
}
