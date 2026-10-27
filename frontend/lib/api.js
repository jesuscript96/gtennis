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
// El usuario guardado al entrar puede ser de antes de un permiso nuevo: se
// pide otra vez al servidor y se guarda lo que diga.
export async function refrescarUsuario() {
  const me = await req("/auth/me/");
  const nuevo = { ...(getUser() || {}), ...me };
  localStorage.setItem("gt_user", JSON.stringify(nuevo));
  return nuevo;
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
      // Solo se reintenta lo que no cambia nada. Reintentar un POST que se
      // cortó a medias relanzaba el trabajo en el servidor —generar una semana
      // se disparaba varias veces a la vez— y cada intento moría igual.
      if (safe && attempt < RETRY_DELAYS.length) { await sleep(RETRY_DELAYS[attempt]); continue; }
      throw new Error(safe
        ? "No se pudo conectar con el servidor. Reinténtalo en unos segundos."
        : "Se cortó la conexión con el servidor. Si era una operación larga (rehacer la semana), puede haber terminado igualmente: recarga antes de repetirla.");
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
    let cuerpo = null;
    const txt = await res.text();
    try {
      detail = JSON.parse(txt);
      cuerpo = detail;
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
    const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    err.status = res.status;
    err.cuerpo = cuerpo;
    throw err;
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
    get: (id) => req(`/${name}/${id}/`),
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
// Antes de rehacer, el servidor contesta 409 si hay algo que preguntar: que
// hay cambios hechos a mano (mantenerlos o rehacer todo, 15/10/2026) o que el
// día ya está cerrado (pasado su corte de las 19:00).
async function conConfirmacion(path, body) {
  try {
    return await req(path, { method: "POST", body: JSON.stringify(body) });
  } catch (e) {
    if (e.status !== 409 || !(e.cuerpo?.cerrado || e.cuerpo?.pregunta_manual)) throw e;
    const c = e.cuerpo;
    if (!c.pregunta_manual) {
      if (!window.confirm(`${e.message} Rehacerlo puede mover a quien no está puesto a mano.\n\n¿Rehacerlo igualmente?`)) return null;
      return req(path, { method: "POST", body: JSON.stringify({ ...body, confirmar: true }) });
    }
    const { preguntar } = await import("./preguntar");
    const n = c.manuales;
    const manual = await preguntar({
      titulo: `Hay ${n} cambio${n === 1 ? "" : "s"} hecho${n === 1 ? "" : "s"} a mano`,
      texto: (c.cerrado ? `${c.error} ` : "") +
        "¿Los mantengo y rehago el resto, o lo rehago todo desde cero? " +
        "En los dos casos se puede deshacer después.",
      lista: c.detalle.concat(n > c.detalle.length ? [`… y ${n - c.detalle.length} más`] : []),
      opciones: [
        { valor: "mantener", texto: "Mantenerlos y rehacer el resto" },
        { valor: "rehacer", texto: "Rehacer todo desde cero", tipo: "ghost" },
        { valor: null, texto: "Cancelar", tipo: "ghost" },
      ],
    });
    if (!manual) return null;
    return req(path, { method: "POST", body: JSON.stringify({ ...body, manual }) });
  }
}
export const generarSemana = (id, opts = {}) =>
  conConfirmacion(`/semanas/${id}/generar/`, opts);
export const regenerarTarde = (id, dia) =>
  conConfirmacion(`/semanas/${id}/regenerar_tarde/`, { dia });
export const publicarSemana = (id) =>
  req(`/semanas/${id}/publicar/`, { method: "POST", body: "{}" });
export const despublicarSemana = (id) =>
  req(`/semanas/${id}/despublicar/`, { method: "POST", body: "{}" });

// Deja de estar fijado a mano: el motor vuelve a decidir sobre él al rehacer.
export const soltarAsignacion = (id) =>
  req(`/asignaciones/${id}/soltar/`, { method: "POST", body: "{}" });
export const deshacerSemana = (id) =>
  req(`/semanas/${id}/deshacer/`, { method: "POST", body: "{}" });
export const getCambios = (id) => req(`/semanas/${id}/cambios/`);

export const cambiarPassword = (actual, nueva) =>
  req("/auth/password/", { method: "POST", body: JSON.stringify({ actual, nueva }) })
    .then((r) => {
      // El token viejo deja de valer: guardamos el nuevo para no perder la sesión.
      if (r?.token) try { localStorage.setItem("gt_token", r.token); } catch {}
      return r;
    });

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
export const moverAsignacion = (body) =>
  req("/asignaciones/mover/", { method: "POST", body: JSON.stringify(body) });
export const moverPista = (body) =>
  req("/asignaciones/mover_pista/", { method: "POST", body: JSON.stringify(body) });
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
export const editarInvitado = (id, body) =>
  req(`/invitados/${id}/`, { method: "PATCH", body: JSON.stringify(body) });
// Volver a invitarle: solo días, sin tocar la ficha.
export const anadirDiasInvitado = (id, fechas) =>
  req(`/invitados/${id}/dias/`, { method: "POST", body: JSON.stringify({ fechas }) });
export const borrarInvitado = (id) => req(`/invitados/${id}/`, { method: "DELETE" });
// Cada día que viene un invitado (el calendario).
export const editarVisita = (id, body) =>
  req(`/visitas-invitado/${id}/`, { method: "PATCH", body: JSON.stringify(body) });
export const quitarVisita = (id) => req(`/visitas-invitado/${id}/`, { method: "DELETE" });
export const aprobarVisita = (id) =>
  req(`/visitas-invitado/${id}/aprobar/`, { method: "POST", body: "{}" });
export const rechazarVisita = (id) =>
  req(`/visitas-invitado/${id}/rechazar/`, { method: "POST", body: "{}" });
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
// «Viene además»: ese día, en esa franja, aunque su horario no lo diga.
export const jugadorExtra = (id, body) =>
  req(`/jugadores/${id}/extra/`, { method: "POST", body: JSON.stringify(body) });
export const quitarExtra = (id, { fecha, turno }) =>
  req(`/jugadores/${id}/extra/?fecha=${fecha}&turno=${turno}`, { method: "DELETE" });

export const getEntrenadoresJugador = (jugadorId, responsable) =>
  req(`/jugadores/${jugadorId}/entrenadores/${responsable ? `?responsable=${responsable}` : ""}`);
export const guardarEntrenadoresJugador = (jugadorId, body) =>
  req(`/jugadores/${jugadorId}/entrenadores/`, { method: "POST", body: JSON.stringify(body) });

// --- Grupos de entrenamiento (entrenador ↔ alumnos) ------------------------
export const getGrupos = () => req("/grupos/");
export const getGruposDivisiones = () => req("/grupos/divisiones/");
// Divisiones: ¿puede mover alumnos? y moverlos (division null = sin división).
export const getPermisosDivisiones = () => req("/divisiones/permisos/");
export const moverDeDivision = (jugador, division) =>
  req("/divisiones/mover/", { method: "POST", body: JSON.stringify({ jugador, division }) });
// Ranking dentro de una división (27/10/2026): los alumnos, del mejor al último.
export const ordenarDivision = (division, orden) =>
  req("/divisiones/ordenar/", { method: "POST", body: JSON.stringify({ division, orden }) });
export const grupoAnadir = (jugador, entrenador) =>
  req("/grupos/anadir/", { method: "POST", body: JSON.stringify({ jugador, entrenador }) });
export const grupoQuitar = (jugador, entrenador) =>
  req("/grupos/quitar/", { method: "POST", body: JSON.stringify({ jugador, entrenador }) });
// Mover = este entrenador pasa a responder por el alumno.
export const grupoMover = (jugador, entrenador) =>
  req("/grupos/mover/", { method: "POST", body: JSON.stringify({ jugador, entrenador }) });
// Mover un entrenador de bloque: se lleva a sus alumnos con él. `desde` es el
// bloque en el que se le veía (los de Sergio e Iván no los pierde).
export const grupoMoverEntrenador = (entrenador, coach, desde) =>
  req("/grupos/mover_entrenador/", {
    method: "POST", body: JSON.stringify({ entrenador, coach, desde }),
  });
// Ordenar las columnas de un bloque, de izquierda a derecha.
export const grupoOrdenar = (coach, orden) =>
  req("/grupos/ordenar/", { method: "POST", body: JSON.stringify({ coach, orden }) });

// --- Ausencias de jugador por rango de fechas ------------------------------
export const getAusenciasFechas = async (jugador) =>
  rows(await req(`/ausencias-fechas/${jugador ? `?jugador=${jugador}` : ""}`));
export const addAusenciaFechas = (body) =>
  req("/ausencias-fechas/", { method: "POST", body: JSON.stringify(body) });
export const delAusenciaFechas = (id) =>
  req(`/ausencias-fechas/${id}/`, { method: "DELETE" });
// Quitar solo unos días («ha vuelto el miércoles»); sin `hasta`, hasta el final.
export const quitarDiasAusencia = (id, desde, hasta) =>
  req(`/ausencias-fechas/${id}/quitar_dias/`, {
    method: "POST", body: JSON.stringify({ desde, ...(hasta ? { hasta } : {}) }),
  });

// --- Superficie por fechas («del 5 al 9, resina») ----------------------------
export const getPreferenciasSuperficie = async (jugador) =>
  rows(await req(`/preferencias-superficie/${jugador ? `?jugador=${jugador}` : ""}`));
export const addPreferenciaSuperficie = (body) =>
  req("/preferencias-superficie/", { method: "POST", body: JSON.stringify(body) });
export const delPreferenciaSuperficie = (id) =>
  req(`/preferencias-superficie/${id}/`, { method: "DELETE" });
export const quitarDiasSuperficie = (id, desde, hasta) =>
  req(`/preferencias-superficie/${id}/quitar_dias/`, {
    method: "POST", body: JSON.stringify({ desde, ...(hasta ? { hasta } : {}) }),
  });

// --- Torneos (módulo aparte: comparte jugadores y entrenadores) -----------
export const getTorneos = async (params = {}) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
  const s = p.toString();
  return rows(await req(`/torneos/${s ? `?${s}` : ""}`));
};
export const getTorneo = (id) => req(`/torneos/${id}/`);
export const crearTorneo = (body) => req("/torneos/", { method: "POST", body: JSON.stringify(body) });
export const guardarTorneo = (id, body) =>
  req(`/torneos/${id}/`, { method: "PATCH", body: JSON.stringify(body) });
export const borrarTorneo = (id) => req(`/torneos/${id}/`, { method: "DELETE" });
export const getTorneosResumen = () => req("/torneos/resumen/");
export const getTorneosPorJugador = () => req("/torneos/por_jugador/");
export const addParticipante = (body) =>
  req("/torneos-participantes/", { method: "POST", body: JSON.stringify(body) });
export const updParticipante = (id, body) =>
  req(`/torneos-participantes/${id}/`, { method: "PATCH", body: JSON.stringify(body) });
export const delParticipante = (id) => req(`/torneos-participantes/${id}/`, { method: "DELETE" });
// Entrenadores activos con sus vacaciones en el tramo: para el desplegable de «acompaña».
export const getTorneosEntrenadores = (desde, hasta) =>
  req(`/torneos/entrenadores/?${new URLSearchParams({ ...(desde && { desde }), ...(hasta && { hasta }) })}`);
// Dos filas que son el mismo torneo: `con` se vuelca en `id` y desaparece.
export const fusionarTorneo = (id, con) =>
  req(`/torneos/${id}/fusionar/`, { method: "POST", body: JSON.stringify({ con }) });
// Deshacer en torneos: los últimos cambios de quien pregunta y deshacer el último.
export const getCambiosTorneos = () => req("/torneos-cambios/");
export const deshacerTorneos = () =>
  req("/torneos-cambios/deshacer/", { method: "POST", body: "{}" });

// --- Evaluaciones (Informe de Rendimiento) ---------------------------------
export const getCatalogoEvaluacion = () => req("/evaluaciones/catalogo/");
export const getEvaluaciones = async (params = {}) => {
  const s = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
  return rows(await req(`/evaluaciones/${s ? `?${s}` : ""}`));
};
export const getEvaluacion = (id) => req(`/evaluaciones/${id}/`);
// Jugadores que puede evaluar de tenis quien pregunta (incluye Competición de tardes si le toca).
export const getJugadoresTenis = () => req("/evaluaciones/jugadores/");
export const crearEvaluacion = (body) => req("/evaluaciones/", { method: "POST", body: JSON.stringify(body) });
export const guardarEvaluacion = (id, body) =>
  req(`/evaluaciones/${id}/`, { method: "PATCH", body: JSON.stringify(body) });
export const borrarEvaluacion = (id) => req(`/evaluaciones/${id}/`, { method: "DELETE" });
// Claude pule el comentario del bloque y lo deja guardado ({comentario, aviso}).
export const pulirComentario = (id, bloque, texto) =>
  req(`/evaluaciones/${id}/pulir/`, { method: "POST", body: JSON.stringify({ bloque, texto }) });
export const terminarEvaluacion = (id, rehacerResumen = false) =>
  req(`/evaluaciones/${id}/terminar/`, { method: "POST", body: JSON.stringify({ rehacer_resumen: rehacerResumen }) });
export const getFicheroEvaluacion = (id) => req(`/evaluaciones/${id}/fichero/`);
// Sube (o reescribe) el informe terminado en la carpeta del jugador en Drive ({…evaluación, aviso}).
export const guardarEvaluacionEnDrive = (id) =>
  req(`/evaluaciones/${id}/drive/`, { method: "POST", body: "{}" });
// El informe en PDF como fichero (no es JSON: va aparte de req()).
export async function descargarPdfEvaluacion(id) {
  const res = await fetch(`${BASE}/evaluaciones/${id}/pdf/`, {
    headers: { Authorization: `Token ${getToken()}` }, cache: "no-store",
  });
  if (!res.ok) throw new Error(`No se ha podido generar el PDF (${res.status}).`);
  const disp = res.headers.get("Content-Disposition") || "";
  const m = disp.match(/filename\*=utf-8''([^;]+)/i) || disp.match(/filename="?([^";]+)"?/i);
  return { blob: await res.blob(), nombre: m ? decodeURIComponent(m[1]) : `informe-${id}.pdf` };
}

// --- Informes de Competición de tardes (tenis + físico, validación) -------
export const getPanelInformes = () => req("/informes/panel/");
export const getInformes = async (params = {}) => {
  const s = new URLSearchParams(params).toString();
  return rows(await req(`/informes/${s ? `?${s}` : ""}`));
};
export const getInforme = (id) => req(`/informes/${id}/`);
export const aprobarInforme = (id, destinatarios) =>
  req(`/informes/${id}/aprobar/`, { method: "POST", body: JSON.stringify({ destinatarios }) });
export const devolverInforme = (id, partes, nota) =>
  req(`/informes/${id}/devolver/`, { method: "POST", body: JSON.stringify({ partes, nota }) });
export const guardarInformeEnDrive = (id) => req(`/informes/${id}/guardar-drive/`, { method: "POST", body: "{}" });
async function fichero(path, porDefecto) {
  const res = await fetch(`${BASE}${path}`, { headers: { Authorization: `Token ${getToken()}` }, cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`No se ha podido descargar (${res.status}).`);
  const disp = res.headers.get("Content-Disposition") || "";
  const m = disp.match(/filename\*=utf-8''([^;]+)/i) || disp.match(/filename="?([^";]+)"?/i);
  return { blob: await res.blob(), nombre: m ? decodeURIComponent(m[1]) : porDefecto };
}
export const descargarPdfInforme = (id) => fichero(`/informes/${id}/pdf/`, `informe-${id}.pdf`);
// La foto del jugador para el informe (null si no tiene).
export const getFotoJugador = (jugadorId) => fichero(`/informes/foto/${jugadorId}/`, "foto.jpg");
export async function subirFotoJugador(jugadorId, file) {
  const datos = new FormData();
  datos.append("foto", file);
  const res = await fetch(`${BASE}/informes/foto/${jugadorId}/`, {
    method: "POST", body: datos, headers: { Authorization: `Token ${getToken()}` },
  });
  if (!res.ok) {
    let msg = `No se ha podido subir la foto (${res.status}).`;
    try { const j = await res.json(); msg = j.foto || j.detail || msg; } catch { /* sin cuerpo */ }
    throw new Error(Array.isArray(msg) ? msg.join(" ") : msg);
  }
  return res.json();
}

// --- Evaluaciones físicas (preparador físico y gestión deportiva) ----------
export const getCatalogoFisico = () => req("/evaluaciones-fisicas/catalogo/");
export const getJugadoresFisico = () => req("/evaluaciones-fisicas/jugadores/");
export const getEvaluacionesFisicas = async () => rows(await req("/evaluaciones-fisicas/"));
export const getEvaluacionFisica = (id) => req(`/evaluaciones-fisicas/${id}/`);
export const crearEvaluacionFisica = (body) =>
  req("/evaluaciones-fisicas/", { method: "POST", body: JSON.stringify(body) });
export const guardarEvaluacionFisica = (id, body) =>
  req(`/evaluaciones-fisicas/${id}/`, { method: "PATCH", body: JSON.stringify(body) });
export const borrarEvaluacionFisica = (id) => req(`/evaluaciones-fisicas/${id}/`, { method: "DELETE" });
export const terminarEvaluacionFisica = (id) =>
  req(`/evaluaciones-fisicas/${id}/terminar/`, { method: "POST", body: "{}" });
