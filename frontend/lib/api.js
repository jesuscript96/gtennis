const rawBase = (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api").replace(/\/$/, "");
const BASE = rawBase.endsWith("/api") ? rawBase : `${rawBase}/api`;

export function getToken() {
  return typeof window !== "undefined" ? localStorage.getItem("gt_token") : null;
}
export function getUser() {
  try {
    return JSON.parse(localStorage.getItem("gt_user"));
  } catch {
    return null;
  }
}
function setAuth(data) {
  localStorage.setItem("gt_token", data.token);
  localStorage.setItem("gt_user", JSON.stringify(data));
}
export function logout() {
  localStorage.removeItem("gt_token");
  localStorage.removeItem("gt_user");
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// Reintenta ante errores transitorios (p.ej. la máquina del backend arrancando
// en frío en Fly tras estar en reposo): así el 500/502 no llega al usuario.
const RETRY_DELAYS = [1000, 2500];

async function req(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const t = getToken();
  if (t) headers["Authorization"] = `Token ${t}`;
  const safe = (opts.method || "GET").toUpperCase() === "GET";

  let res;
  for (let attempt = 0; ; attempt++) {
    try {
      res = await fetch(`${BASE}${path}`, { ...opts, headers, cache: "no-store" });
    } catch (e) {
      if (attempt < RETRY_DELAYS.length) { await sleep(RETRY_DELAYS[attempt]); continue; }
      throw new Error("No se pudo conectar con el servidor. Reinténtalo en unos segundos.");
    }
    const transient = res.status >= 502 || (safe && res.status >= 500);
    if (transient && attempt < RETRY_DELAYS.length) { await sleep(RETRY_DELAYS[attempt]); continue; }
    break;
  }

  if (res.status === 401 && typeof window !== "undefined") {
    logout();
    if (!path.startsWith("/auth/")) window.location.href = "/login";
  }
  if (!res.ok) {
    let detail;
    const txt = await res.text();
    try {
      detail = JSON.parse(txt);
      if (typeof detail === "object" && detail !== null) {
        detail = detail.detail || detail.error || detail.message || JSON.stringify(detail);
      }
    } catch {
      if (txt.trim().startsWith("<") || txt.includes("<!doctype")) {
        detail = `Error (${res.status}): No se pudo completar la petición al backend (${res.statusText || "Respuesta HTML no válida"}).`;
      } else {
        detail = txt;
      }
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return null;
  return res.json();
}

export async function login(username, password) {
  const data = await req("/auth/token/", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  setAuth(data);
  return data;
}

function rows(data) {
  return data && data.results ? data.results : data || [];
}

export function resource(name) {
  return {
    list: async (q = "") => rows(await req(`/${name}/${q}`)),
    create: (body) => req(`/${name}/`, { method: "POST", body: JSON.stringify(body) }),
    update: (id, body) =>
      req(`/${name}/${id}/`, { method: "PATCH", body: JSON.stringify(body) }),
    remove: (id) => req(`/${name}/${id}/`, { method: "DELETE" }),
    action: (id, verb, body) =>
      req(`/${name}/${id}/${verb}/`, { method: "POST", body: JSON.stringify(body || {}) }),
  };
}

export const getLatestSemana = async () => {
  const r = rows(await req("/semanas/?limit=1"));
  return r[0] || null;
};
export const getCuadrante = (id, dia) => req(`/semanas/${id}/cuadrante/?dia=${dia}`);
export const generarSemana = (id) =>
  req(`/semanas/${id}/generar/`, { method: "POST", body: "{}" });
export const regenerarTarde = (id, dia) =>
  req(`/semanas/${id}/regenerar_tarde/`, { method: "POST", body: JSON.stringify({ dia }) });
export const publicarSemana = (id) =>
  req(`/semanas/${id}/publicar/`, { method: "POST", body: "{}" });

export const getConfig = () => req("/configuracion/");
export const saveConfig = (body) =>
  req("/configuracion/", { method: "PATCH", body: JSON.stringify(body) });

export const getAhora = () => req("/ahora/");
export const getTabla = (id) => req(`/semanas/${id}/tabla/`);
export const getPanel = (id, dia) => req(`/semanas/${id}/panel/?dia=${dia}`);
export const swapAsignacion = (a, b, campo) =>
  req("/asignaciones/swap/", { method: "POST", body: JSON.stringify({ a, b, campo }) });
export const manualAssign = (body) =>
  req("/asignaciones/manual_assign/", { method: "POST", body: JSON.stringify(body) });
export const setCoach = (body) =>
  req("/asignaciones/set_coach/", { method: "POST", body: JSON.stringify(body) });
export const removeAsignacion = (id) =>
  req(`/asignaciones/${id}/`, { method: "DELETE" });

// --- Avisos in-app (perfil) ---
export const getAvisos = async () => rows(await req("/avisos/"));
export const marcarAvisoLeido = (id) =>
  req(`/avisos/${id}/leer/`, { method: "POST", body: "{}" });

// --- Invitados (aprobación del Director Deportivo) ---
export const getInvitados = async () => rows(await req("/invitados/"));
export const crearInvitado = (body) =>
  req("/invitados/", { method: "POST", body: JSON.stringify(body) });
export const aprobarInvitado = (id) =>
  req(`/invitados/${id}/aprobar/`, { method: "POST", body: "{}" });
export const rechazarInvitado = (id, motivo = "") =>
  req(`/invitados/${id}/rechazar/`, { method: "POST", body: JSON.stringify({ motivo }) });

// --- Agenda del entrenador (lo suyo, no el general de la app) -------------
// `de` = id de entrenador; solo dirección puede pasarlo, para mirar la agenda
// de otro desde el selector.
const q = (de) => (de ? `?entrenador=${de}` : "");
export const getMiAgenda = (de) => req(`/mi-agenda/${q(de)}`);
export const getMiDia = (de) => req(`/mi-agenda/dia/${q(de)}`);
// Sus pistas de un día: turno, hora, número y quién le toca.
export const getMisSesiones = (de, fecha) => {
  const p = new URLSearchParams();
  if (de) p.set("entrenador", de);
  if (fecha) p.set("fecha", fecha);
  const s = p.toString();
  return req(`/mi-agenda/sesiones/${s ? `?${s}` : ""}`);
};
export const saveMiSemana = (semana, de) =>
  req(`/mi-agenda/semana/${q(de)}`, { method: "PATCH", body: JSON.stringify({ semana }) });
export const getMisAusencias = (de) => req(`/mi-agenda/ausencias/${q(de)}`);
export const addMiAusencia = (body, de) =>
  req(`/mi-agenda/ausencias/${q(de)}`, { method: "POST", body: JSON.stringify(body) });
export const delMiAusencia = (id, de) =>
  req(`/mi-agenda/ausencias/${id}/${q(de)}`, { method: "DELETE" });
export const getEntrenadoresAgenda = () => req("/mi-agenda/entrenadores/");

// --- Agenda del propio alumno (lo que ve su entrenador) --------------------
// Lo que tiene hoy y lo que tiene esta semana: pista, hora, entrenador y con
// quién. Si la semana aún no está generada devuelve lo previsto por su horario.
export const getAgendaJugador = (id, fecha) =>
  req(`/jugadores/${id}/agenda/${fecha ? `?fecha=${fecha}` : ""}`);

// --- Grupos de entrenamiento (entrenador ↔ alumnos) ------------------------
export const getGrupos = () => req("/grupos/");
export const grupoAnadir = (jugador, entrenador) =>
  req("/grupos/anadir/", { method: "POST", body: JSON.stringify({ jugador, entrenador }) });
export const grupoQuitar = (jugador, entrenador) =>
  req("/grupos/quitar/", { method: "POST", body: JSON.stringify({ jugador, entrenador }) });
// Mover = este entrenador pasa a responder por el alumno.
export const grupoMover = (jugador, entrenador) =>
  req("/grupos/mover/", { method: "POST", body: JSON.stringify({ jugador, entrenador }) });
// Mover un entrenador de bloque: se lleva a sus alumnos con él.
export const grupoMoverEntrenador = (entrenador, coach) =>
  req("/grupos/mover_entrenador/", {
    method: "POST", body: JSON.stringify({ entrenador, coach }),
  });

// --- Ausencias de jugador por rango de fechas ------------------------------
export const getAusenciasFechas = async (jugador) =>
  rows(await req(`/ausencias-fechas/${jugador ? `?jugador=${jugador}` : ""}`));
export const addAusenciaFechas = (body) =>
  req("/ausencias-fechas/", { method: "POST", body: JSON.stringify(body) });
export const delAusenciaFechas = (id) =>
  req(`/ausencias-fechas/${id}/`, { method: "DELETE" });
