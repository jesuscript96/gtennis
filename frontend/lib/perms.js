"use client";

import { getUser } from "./api";
import { dondeEsta, esAdministracion, esPreparador, esEntrenador, perfil } from "./menu";

// Perfiles (10/11/2026): dirección, head coach, entrenador, preparador físico y
// administración. Lo fino (tocar el cuadrante, aprobar invitados, validar…)
// son funciones que dirección asigna desde Club; el servidor las manda ya
// resueltas en /auth/me/ y aquí solo se leen.

// Rango para lo que aún compara niveles: dirección (3) > head coach (2) > resto (1).
export function roleRank(user) {
  const p = perfil(user);
  if (p === "direccion") return 3;
  if (p === "head_coach") return 2;
  return 1;
}

export function navRole(user = getUser()) {
  return perfil(user);
}

/** ¿Tiene el usuario este permiso? (toca_cuadrante, aprueba_invitados, valida_informes…) */
export function puede(flag, user = getUser()) {
  return Boolean(user?.[flag]);
}

/** A dónde va cada uno al entrar o si pide una ruta que no le toca. */
export function inicio(user = getUser()) {
  if (esPreparador(user)) return "/evaluaciones";
  if (esAdministracion(user)) return "/jugadores";
  if (esEntrenador(user)) return "/mi-agenda";
  return "/";
}

// Quién puede ESCRIBIR cada recurso genérico (ResourceCrud). Refleja el servidor.
const WRITE = {
  sedes: "direccion", pistas: "direccion", turnos: "direccion",
  divisiones: "direccion", escuelas: "direccion", coaches: "direccion",
  entrenadores: "head_coach", responsables: "direccion", vacaciones: "head_coach",
  contratos: "head_coach", rencillas: "head_coach", torneos: "head_coach",
  "disponibilidades-entrenador": "direccion",
  // Crear sí (config.crear); cambiar y borrar, dirección.
  mantenimiento: "direccion", feedback: "direccion",
};
const NEED = { direccion: 3, head_coach: 2 };

export function canWrite(endpoint, user = getUser()) {
  if (endpoint === "jugadores") return roleRank(user) >= 3 || esAdministracion(user);
  const need = NEED[WRITE[endpoint]] || 1;
  return roleRank(user) >= need;
}

// Rutas de detalle que cuelgan de una pestaña (las cubre `dondeEsta`):
// /torneos/123, /evaluaciones/45, /informes/9…
export function canVisit(path, user = getUser()) {
  return Boolean(dondeEsta(path, user));
}

// En torneos, además de head coaches y dirección, el entrenador apunta a sus
// jugadores a torneos que ya existen; queda pendiente de confirmar (03/11/2026).
export function apuntaATorneos(user = getUser()) {
  return roleRank(user) >= 2 || Boolean(user?.entrenador_id);
}
