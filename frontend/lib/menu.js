"use client";

// Menú de la aplicación (orden del 10/11/2026): 13 entradas, y dentro de cada
// una sus pestañas. Cada perfil ve solo lo suyo: lo que alguien no puede usar
// no le sale. Las reglas vienen del servidor (/auth/me/): perfil y funciones.
//
// Una ruta pertenece a la entrada en la que aparece como pestaña visible para
// ese usuario (p. ej. /mi-agenda es «Hoy» para el entrenador y una pestaña de
// «Entrenadores» para dirección).

export const perfil = (u) => u?.perfil
  || (u?.is_superadmin ? "direccion" : u?.is_coach ? "head_coach"
    : u?.is_preparador ? "preparador" : "entrenador");

export const esDireccion = (u) => perfil(u) === "direccion";
export const esHeadCoach = (u) => perfil(u) === "head_coach";
export const esEntrenador = (u) => perfil(u) === "entrenador";
export const esAdministracion = (u) => perfil(u) === "administracion";
export const esPreparador = (u) => perfil(u) === "preparador";
const club = (u) => esDireccion(u) || esHeadCoach(u);
const deportivo = (u) => club(u) || esEntrenador(u);
const todos = () => true;

export const MENU = [
  { key: "hoy", label: "Hoy", ve: deportivo, tabs: [
    { href: "/", label: "Todo el club", ve: club },
    { href: "/mi-agenda", label: "Mi día", ve: esEntrenador },
  ] },
  { key: "cuadrante", label: "Cuadrante", ve: club, tabs: [
    { href: "/cuadrante", label: "Cuadrante" },
    { href: "/semanas", label: "Todas las semanas" },
  ] },
  { key: "faltas", label: "Faltas", ve: deportivo, tabs: [
    { href: "/faltas", label: "Faltas" },
  ] },
  { key: "avisos", label: "Avisos", ve: todos, tabs: [
    { href: "/avisos", label: "Avisos" },
  ] },
  { key: "jugadores", label: "Jugadores", ve: (u) => deportivo(u) || esAdministracion(u), tabs: [
    { href: "/jugadores", label: (u) => (esDireccion(u) || esAdministracion(u) ? "Fichas" : "Jugadores") },
    { href: "/mis-jugadores", label: "Día a día", ve: esDireccion },
    { href: "/jugador-turnos", label: "Horario habitual", ve: club },
    { href: "/rencillas", label: "Rencillas", ve: (u) => Boolean(u?.ve_reglas_jugador) },
    { href: "/contratos", label: "Contratos de patrocinio", ve: (u) => Boolean(u?.ve_reglas_jugador) },
    // La lista de todas a la vez (antes «Pref. superficie»), 11/11/2026.
    { href: "/preferencias-superficie", label: "Superficie", ve: (u) => Boolean(u?.ve_reglas_jugador) },
  ], ocultas: [{ href: "/jugador-responsables", ve: club }] },
  { key: "grupos", label: "Grupos", ve: deportivo, tabs: [
    { href: "/grupos", label: "Grupos" },
  ] },
  { key: "entrenadores", label: "Entrenadores", ve: deportivo, tabs: [
    { href: "/entrenadores", label: (u) => (esEntrenador(u) ? "Mi ficha" : "Entrenadores") },
    { href: "/mi-agenda", label: "Agenda", ve: club },
    { href: "/coaches", label: "Head coaches", ve: esDireccion },
  ] },
  { key: "torneos", label: "Torneos", ve: deportivo, tabs: [
    { href: "/torneos", label: "Calendario" },
    { href: "/torneos/jugadores", label: "Por jugador" },
    { href: "/torneos/nuevo", label: "Nuevo torneo", ve: club },
  ] },
  { key: "invitados", label: "Invitados", ve: (u) => Boolean(u?.aprueba_invitados), tabs: [
    { href: "/invitados", label: "Invitados" },
  ] },
  { key: "rendimiento", label: "Rendimiento", ve: (u) => deportivo(u) || esPreparador(u) || Boolean(u?.ve_informes), tabs: [
    { href: "/evaluaciones", label: (u) => (esPreparador(u) ? "Evaluaciones físicas" : "Evaluaciones"), ve: (u) => deportivo(u) || esPreparador(u) },
    { href: "/informes", label: "Informes", ve: (u) => Boolean(u?.ve_informes) },
    { href: "/tardes", label: "Competición de tardes", ve: (u) => Boolean(u?.coordina_informes) },
  ] },
  { key: "club", label: "Club", ve: esDireccion, tabs: [
    { href: "/sedes", label: "Sedes" },
    { href: "/pistas", label: "Pistas" },
    { href: "/divisiones-club", label: "Divisiones" },
    { href: "/escuelas", label: "Escuelas" },
    { href: "/configuracion", label: "Criterios del motor" },
    { href: "/funciones", label: "Personas y funciones" },
  ] },
  { key: "mantenimiento", label: "Mantenimiento e incidencias", ve: deportivo, tabs: [
    { href: "/mantenimiento", label: "Mantenimiento" },
    { href: "/feedback", label: "Peticiones de la app", ve: club },
  ] },
  { key: "cuenta", label: "Mi cuenta", ve: todos, tabs: [
    { href: "/mi-cuenta", label: "Mi cuenta" },
  ] },
];

// Pantallas que se juntaron con otra (10/11/2026): quien llegue por un enlace
// viejo va a la nueva.
export const RUTAS_VIEJAS = {
  "/ausencias": "/faltas",
  "/ausencias-fechas": "/faltas",
  "/vacaciones": "/mi-agenda",
  "/disponibilidad-entrenador": "/mi-agenda",
  "/responsables": "/jugadores",
  "/semana": "/cuadrante?vista=semana",
  "/divisiones": "/grupos?vista=division",
  "/ahora": "/",
};

const etiqueta = (x, u) => (typeof x === "function" ? x(u) : x);

/** Las entradas que ve el usuario, cada una con sus pestañas visibles. */
export function menuDe(u) {
  return MENU.filter((e) => e.ve(u))
    .map((e) => ({
      ...e,
      tabs: e.tabs.filter((t) => !t.ve || t.ve(u)).map((t) => ({ ...t, label: etiqueta(t.label, u) })),
    }))
    .filter((e) => e.tabs.length > 0)
    .map((e) => ({ ...e, href: e.tabs[0].href }));
}

const encaja = (path, href) => path === href || (href !== "/" && path.startsWith(href + "/"));

/** La entrada y la pestaña a las que pertenece una ruta (la pestaña más larga que encaje). */
export function dondeEsta(path, u) {
  // Una pestaña que existe pero no es para este usuario no se cuela por
  // prefijo (p. ej. /torneos/nuevo para el entrenador por estar en /torneos).
  const oculta = MENU.flatMap((e) => [...e.tabs, ...(e.ocultas || [])].map((t) => ({ e, t })))
    .filter(({ e, t }) => encaja(path, t.href) && !(e.ve(u) && (!t.ve || t.ve(u))))
    .reduce((m, { t }) => Math.max(m, t.href.length), -1);
  let mejor = null;
  for (const e of menuDe(u)) {
    const ocultas = (MENU.find((m) => m.key === e.key).ocultas || [])
      .filter((t) => !t.ve || t.ve(u)).map((t) => ({ ...t, oculta: true }));
    for (const t of [...e.tabs, ...ocultas]) {
      if (encaja(path, t.href) && (!mejor || t.href.length > mejor.largo)) {
        mejor = { entrada: e, tab: t.oculta ? e.tabs[0] : t, largo: t.href.length };
      }
    }
  }
  return mejor && mejor.largo >= oculta ? mejor : null;
}
