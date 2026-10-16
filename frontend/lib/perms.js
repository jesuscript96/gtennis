"use client";

import { getUser } from "./api";

// Rango de rol: dirección (3) > coach (2) > entrenador (1).
export function roleRank(user) {
  if (user?.is_superadmin) return 3;
  if (user?.is_coach) return 2;
  return 1; // entrenador o cualquier autenticado
}

export function navRole(user = getUser()) {
  return user?.is_superadmin ? "direccion" : user?.is_coach ? "coach" : "entrenador";
}

const NEED = { direccion: 3, coach: 2, entrenador: 1 };

// Quién puede ESCRIBIR cada recurso (por endpoint de la API). Refleja la
// matriz de permisos del backend. Lo que no aparece: cualquiera autenticado
// (el backend aplica el alcance por filas).
const WRITE = {
  sedes: "direccion", pistas: "direccion", turnos: "direccion",
  divisiones: "direccion", escuelas: "direccion", coaches: "direccion",
  entrenadores: "coach", responsables: "coach", vacaciones: "coach",
  contratos: "coach", rencillas: "coach", torneos: "coach",
};

export function canWrite(endpoint, user = getUser()) {
  const need = NEED[WRITE[endpoint] || "entrenador"];
  return roleRank(user) >= need;
}

// Rol mínimo para VER una ruta del panel (las que no aparecen: todos).
const PATH_MIN = {
  // Rutas del panel general que el entrenador no necesita ver.
  "/": "coach", "/cuadrante": "coach", "/semana": "coach", "/semanas": "coach",
  // El entrenador declara su propia disponibilidad de la semana: el backend ya
  // le deja ver y editar solo sus filas, así que esconderle la página solo le
  // impedía hacer lo único que se le pide.
  "/vacaciones": "coach",
  "/preferencias-superficie": "coach", "/invitados": "coach",
  "/mantenimiento": "coach", "/feedback": "coach",
  "/sedes": "direccion", "/pistas": "direccion", "/divisiones": "direccion",
  "/escuelas": "direccion", "/turnos": "direccion", "/coaches": "direccion",
  "/mis-jugadores": "direccion",
  "/configuracion": "direccion",
  "/entrenadores": "coach",
  // El calendario de torneos lo ve todo el mundo; dar de alta, solo los head
  // coaches y dirección (las subrutas heredan de la más larga que encaje).
  "/torneos/nuevo": "coach",
};

export function canVisit(path, user = getUser()) {
  // La ruta exacta o la más larga de la que cuelga (/torneos/123 → /torneos).
  const clave = Object.keys(PATH_MIN)
    .filter((k) => path === k || (k !== "/" && path.startsWith(k + "/")))
    .sort((a, b) => b.length - a.length)[0];
  const need = NEED[PATH_MIN[clave] || "entrenador"];
  return roleRank(user) >= need;
}
