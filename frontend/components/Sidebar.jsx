"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { getUser, logout } from "../lib/api";
import SettingsMenu from "./SettingsMenu";

// Menú por secciones para reducir el ruido de tantas entradas.
const SECTIONS = [
  { items: [
    ["/", "Inicio"],
    ["/cuadrante", "Cuadrante (día)"],
    ["/semana", "Semana"],
    ["/semanas", "Semanas"],
  ] },
  { title: "Disponibilidad", items: [
    ["/ausencias", "Ausencias y estados"],
    ["/disponibilidad-entrenador", "Disp. entrenadores"],
    ["/vacaciones", "Vacaciones"],
  ] },
  { title: "Datos", items: [
    ["/jugadores", "Jugadores"],
    ["/entrenadores", "Entrenadores"],
    ["/responsables", "Responsables"],
  ] },
  { title: "Gestión", items: [
    ["/invitados", "Invitados"],
    ["/mantenimiento", "Mantenimiento"],
    ["/avisos", "Avisos"],
    ["/feedback", "Feedback"],
  ] },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const user = getUser();

  function onLogout() {
    logout();
    router.push("/login");
  }

  return (
    <aside className="sidebar">
      <div className="brand">G<span>Tennis</span></div>
      <nav>
        {SECTIONS.map((section, i) => (
          <div key={i} className="nav-section">
            {section.title && <div className="nav-section-title">{section.title}</div>}
            {section.items.map(([href, label]) => (
              <Link key={href} href={href} className={pathname === href ? "active" : ""}>
                {label}
              </Link>
            ))}
          </div>
        ))}
      </nav>
      <div className="user">
        <div className="user-row">
          <div className="user-id">
            <div className="name">{user?.nombre || user?.username || "—"}</div>
            <div className="role">{user?.is_superadmin ? "Super Admin" : "Entrenador"}</div>
          </div>
          <SettingsMenu align="left" up />
        </div>
        <button onClick={onLogout}>Cerrar sesión</button>
      </div>
    </aside>
  );
}
