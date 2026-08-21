"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { getUser, logout } from "../lib/api";
import { roleRank } from "../lib/perms";
import SettingsMenu from "./SettingsMenu";

// Menú por secciones. El 3er elemento de cada item es el rol mínimo para verlo
// ("direccion" o "coach"); sin él, lo ve cualquiera.
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
    ["/entrenadores", "Entrenadores", "coach"],
    ["/coaches", "Coaches", "direccion"],
    ["/escuelas", "Escuelas", "direccion"],
    ["/preferencias-superficie", "Pref. superficie"],
  ] },
  { title: "Gestión", items: [
    ["/invitados", "Invitados"],
    ["/mantenimiento", "Mantenimiento"],
    ["/avisos", "Avisos"],
    ["/feedback", "Feedback"],
  ] },
];

const NEED = { direccion: 3, coach: 2 };

export default function Sidebar({ onNavigate }) {
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
            {section.items
              .filter(([, , role]) => !role || roleRank(user) >= NEED[role])
              .map(([href, label]) => (
                <Link key={href} href={href} className={pathname === href ? "active" : ""} onClick={onNavigate}>
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
            <div className="role">{user?.is_superadmin ? "Super Admin" : user?.is_coach ? "Coach" : "Entrenador"}</div>
          </div>
          <SettingsMenu align="left" up />
        </div>
        <button onClick={onLogout}>Cerrar sesión</button>
      </div>
    </aside>
  );
}
