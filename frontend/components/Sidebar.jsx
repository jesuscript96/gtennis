"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { getUser, logout } from "../lib/api";
import SettingsMenu from "./SettingsMenu";

const NAV = [
  ["/", "Inicio"],
  ["/cuadrante", "Cuadrante (día)"],
  ["/semana", "Semana"],
  ["/ausencias", "Ausencias y estados"],
  ["/semanas", "Semanas"],
  ["/jugadores", "Jugadores"],
  ["/entrenadores", "Entrenadores"],
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
        {NAV.map(([href, label]) => (
          <Link key={href} href={href} className={pathname === href ? "active" : ""}>
            {label}
          </Link>
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
