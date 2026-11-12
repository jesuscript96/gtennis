"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { getAvisos, getUser, logout } from "../lib/api";
import { dondeEsta, menuDe, perfil } from "../lib/menu";

const NOMBRE_PERFIL = {
  direccion: "Dirección",
  head_coach: "Head coach",
  entrenador: "Entrenador",
  preparador: "Preparador físico",
  administracion: "Administración",
};

// El menú: una entrada por cosa (13 como mucho) y, dentro, sus pestañas
// (`SectionTabs`). Cada perfil ve solo lo que puede usar.
export default function Sidebar({ onNavigate }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState(getUser);
  // El layout vuelve a pedir los permisos al navegar y avisa con este evento:
  // un cambio de perfil o de funciones se nota sin cerrar sesión.
  useEffect(() => {
    const onUser = () => setUser(getUser());
    window.addEventListener("gt-user", onUser);
    return () => window.removeEventListener("gt-user", onUser);
  }, []);
  const entradas = menuDe(user);
  const actual = dondeEsta(pathname, user)?.entrada.key;
  // Avisos sin leer: se miran al cambiar de página, sin sondear.
  const [sinLeer, setSinLeer] = useState(0);
  useEffect(() => {
    getAvisos().then((a) => setSinLeer(a.filter((x) => !x.leido).length)).catch(() => {});
  }, [pathname]);

  function onLogout() {
    logout();
    router.push("/login");
  }

  return (
    <aside className="sidebar">
      <div className="brand">G<span>Tennis</span></div>
      <nav>
        <div className="nav-section">
          {entradas.map((e) => (
            <Link key={e.key} href={e.href} className={actual === e.key ? "active" : ""} onClick={onNavigate}>
              {e.label}
              {e.key === "avisos" && sinLeer > 0 && <span className="nav-badge">{sinLeer}</span>}
            </Link>
          ))}
        </div>
      </nav>
      <div className="user">
        <div className="user-row">
          <div className="user-id">
            <div className="name">{user?.nombre || user?.username || "—"}</div>
            <div className="role">{NOMBRE_PERFIL[perfil(user)] || ""}</div>
          </div>
        </div>
        <button onClick={onLogout}>Cerrar sesión</button>
      </div>
    </aside>
  );
}
