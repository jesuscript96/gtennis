"use client";
import { Fragment, useEffect, useState } from "react";
import {
  getInvitados, crearInvitado, editarInvitado, aprobarInvitado, rechazarInvitado,
  anadirDiasInvitado, borrarInvitado, editarVisita, quitarVisita, aprobarVisita,
  rechazarVisita, getUser, refrescarUsuario, resource,
} from "../../../lib/api";

/**
 * Invitados (14/10/2026): se proponen como un jugador nuevo. Lo que importa es
 * su ficha deportiva, pero va también todo lo que mira el motor —con quién
 * juega y con quién no, superficie, entrenador— y, sobre todo, las fechas y
 * los días en que viene. Al aprobarlo, dirección crea el jugador con todo eso
 * y el motor solo lo pone esos días.
 *
 * Desde el 14/10/2026 el invitado es una persona con una sola ficha, y los
 * días que viene son sus visitas: el calendario dice quién viene cada día, y
 * volver a invitar a uno conocido es añadirle días. Dirección aprueba la ficha
 * y cada día. Siempre es el mismo jugador, con su historial.
 */

const ESTADO_CLASS = { PENDIENTE: "pend", APROBADO: "ok", RECHAZADO: "no" };
const SEMANA = ["L", "M", "X", "J", "V", "S", "D"];
// El club no abre el miércoles ni el sábado por la tarde (lunes = 0).
const TARDE_CERRADA = new Set([2, 5]);
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const deIso = (s) => new Date(`${s}T12:00`);
const diaSemana = (d) => (d.getDay() + 6) % 7; // lunes = 0
const VECINDAD = [
  ["CLUB", "La del club (la horquilla general)"],
  ["SOLO", "Solo su división"],
  ["ARRIBA", "Su división y la de encima (D−1)"],
  ["ABAJO", "Su división y la de debajo (D+1)"],
  ["AMBAS", "Su división y las dos vecinas (±1)"],
];
const PAREJA = [
  ["", "— le da igual —"],
  ["ARRIBA", "Hacia arriba · con la división mejor (D−1)"],
  ["ABAJO", "Hacia abajo · con la división de debajo (D+1)"],
];
const VACIO = {
  nombre: "", entrenador_solicitante: "", nota: "", edad: "", sexo: "",
  fechas: {},
  division: "", vecindad: "CLUB", pareja_division: "", escuela: "",
  sin_prioridad: false, sesiones_dia_max: "",
  superficie_pref: "", superficie_estricta: true,
  jugar_con: "", pareja_estricta: true, no_coincidir_con: [],
  entrena_con: "", entrena_con_estricto: false, no_entrena_con: [],
};

const fecha = (f) => (f ? new Date(`${f}T12:00`).toLocaleDateString("es-ES",
  { day: "numeric", month: "short" }) : "—");

const ESTADO_VISITA = { PENDIENTE: "Pendiente", APROBADA: "Aprobada", RECHAZADA: "Rechazada" };
const CLASE_VISITA = { PENDIENTE: "pend", APROBADA: "ok", RECHAZADA: "no" };

// "M2", "mañana", "M1+T1"… de una visita.
function franjaTexto(v) {
  const b = [];
  if (v.manana != null) b.push(v.manana || "mañana");
  if (v.tarde != null) b.push(v.tarde || "tarde");
  return b.join("+");
}

export default function InvitadosPage() {
  const [items, setItems] = useState(null);
  const [cat, setCat] = useState({ jugadores: [], entrenadores: [], divisiones: [], escuelas: [], turnos: [] });
  const [error, setError] = useState(null);
  const [pestana, setPestana] = useState("calendario");
  const [user, setUser] = useState(getUser);
  // Dirección, y también Dani e Iván: lo que meten queda aprobado (21/10/2026).
  const esAdmin = !!(user?.aprueba_invitados ?? user?.is_superadmin);

  async function load() {
    try { setItems(await getInvitados()); } catch (e) { setError(String(e.message || e)); }
  }
  useEffect(() => {
    load();
    refrescarUsuario().then(setUser).catch(() => {});
    const lista = (r) => resource(r).list().catch(() => []);
    Promise.all([lista("jugadores"), lista("entrenadores"), lista("divisiones"),
      lista("escuelas"), lista("turnos")])
      .then(([jugadores, entrenadores, divisiones, escuelas, turnos]) => setCat({
        jugadores: jugadores.filter((j) => j.activo !== false),
        entrenadores: entrenadores.filter((e) => e.activo !== false),
        divisiones, escuelas, turnos,
      }));
  }, []);

  // Lo que se hace con un botón: si falla, se avisa; y siempre se recarga.
  const accion = async (fn) => {
    try { await fn(); } catch (e) { alert(String(e.message || e)); }
    await load();
  };

  if (error && !items) return <p className="err">{error}</p>;
  if (!items) return <p className="msg">Cargando invitados…</p>;

  const franjas = (bloque) => cat.turnos
    .filter((t) => (bloque === "manana" ? ["M1", "M2"] : ["T1", "T2"]).includes(t.codigo))
    .sort((a, b) => a.codigo.localeCompare(b.codigo));
  const divNombre = (id) => {
    const d = cat.divisiones.find((x) => x.id === id);
    return d ? `D${d.nivel}` : "—";
  };
  const comun = { items, cat, esAdmin, user, accion, franjas, divNombre, recargar: load };
  const pendientes = items.reduce((n, i) => n + i.visitas.filter((v) => v.estado === "PENDIENTE").length, 0);

  return (
    <div className="page invitados">
      <div className="page-head"><h1>Invitados</h1></div>
      <p className="help">
        Cada invitado tiene una ficha —la deportiva y lo que mira el motor— que se
        rellena una vez. Los días que viene se añaden en el calendario, y para
        volver a invitar a uno conocido basta con añadirle días. Dirección
        aprueba la ficha y cada día; lo que mete dirección (y Dani o Iván) queda
        aprobado al momento.
      </p>
      {esAdmin && pendientes > 0 && (
        <p className="help" style={{ borderLeftColor: "var(--accent)" }}>
          Hay <b>{pendientes}</b> día(s) de invitados pendientes de aprobar.
        </p>
      )}
      <div className="tabs-inv" role="tablist">
        {[["calendario", "Calendario"], ["lista", `Invitados (${items.length})`]].map(([k, t]) => (
          <button key={k} type="button" role="tab" aria-selected={pestana === k}
            className={pestana === k ? "chip on" : "chip"} onClick={() => setPestana(k)}>{t}</button>
        ))}
      </div>
      {pestana === "calendario" ? <CalendarioInvitados {...comun} /> : <ListaInvitados {...comun} />}
    </div>
  );
}

/**
 * El calendario de invitados: el mes con quién viene cada día y, al tocar un
 * día, quién viene, añadir a uno conocido o dar de alta a uno nuevo.
 */
function CalendarioInvitados({ items, cat, esAdmin, user, accion, franjas, divNombre, recargar }) {
  const hoy = iso(new Date());
  const [mes, setMes] = useState(() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1); });
  const [dia, setDia] = useState(hoy);
  const [nuevo, setNuevo] = useState(false);
  const [conocido, setConocido] = useState({ invitado: "", manana: "", tarde: "no" });

  const porDia = {};
  for (const i of items) {
    for (const v of i.visitas) (porDia[v.fecha] ||= []).push({ ...v, inv: i });
  }
  const celdas = [];
  for (let k = 0; k < diaSemana(mes); k++) celdas.push(null);
  const fin = new Date(mes.getFullYear(), mes.getMonth() + 1, 0).getDate();
  for (let d = 1; d <= fin; d++) celdas.push(new Date(mes.getFullYear(), mes.getMonth(), d));

  const delDia = (porDia[dia] || []).sort((a, b) => a.inv.nombre.localeCompare(b.inv.nombre));
  const dDia = deIso(dia);
  const domingo = diaSemana(dDia) === 6;
  const tardeCerrada = TARDE_CERRADA.has(diaSemana(dDia));
  const yaVienen = new Set(delDia.map((v) => v.inv.id));
  const candidatos = items.filter((i) => i.estado !== "RECHAZADO" && !yaVienen.has(i.id))
    .sort((a, b) => a.nombre.localeCompare(b.nombre));
  const puedeTocar = (v) => esAdmin || (v.estado === "PENDIENTE" && v.solicitante === user?.entrenador_id);

  const bloques = (b) => ({
    manana: b.manana === "no" ? undefined : b.manana,
    ...(!tardeCerrada && b.tarde !== "no" ? { tarde: b.tarde } : {}),
  });
  const selector = (bloque, valor, onSel, disabled) => (
    <select value={valor} disabled={disabled} onChange={(e) => onSel(e.target.value)}>
      <option value="no">No viene</option>
      <option value="">Sí · la que encaje</option>
      {franjas(bloque).map((t) => <option key={t.codigo} value={t.codigo}>{t.codigo}</option>)}
    </select>
  );

  return (
    <div className="cal-invitados">
      <div className="card cal-grande">
        <div className="cal-nav">
          <button type="button" className="btn ghost sm"
            onClick={() => setMes(new Date(mes.getFullYear(), mes.getMonth() - 1, 1))}>‹</button>
          <b>{mes.toLocaleDateString("es-ES", { month: "long", year: "numeric" })}</b>
          <button type="button" className="btn ghost sm"
            onClick={() => setMes(new Date(mes.getFullYear(), mes.getMonth() + 1, 1))}>›</button>
        </div>
        <div className="cal-rejilla grande">
          {SEMANA.map((x) => <span key={x} className="cal-cab">{x}</span>)}
          {celdas.map((d, k) => {
            if (!d) return <span key={`v${k}`} />;
            const clave = iso(d);
            const vis = porDia[clave] || [];
            return (
              <button type="button" key={clave} disabled={diaSemana(d) === 6}
                className={["cal-celda", clave === dia ? "sel" : "", clave === hoy ? "hoy" : "",
                  clave < hoy ? "pasado" : ""].filter(Boolean).join(" ")}
                onClick={() => { setDia(clave); setNuevo(false); }}>
                <span className="num">{d.getDate()}</span>
                {vis.slice(0, 3).map((v) => (
                  <span key={v.id} className={`mini ${CLASE_VISITA[v.estado]}`}>
                    {v.inv.nombre.split(" ")[0]}
                  </span>
                ))}
                {vis.length > 3 && <span className="mini mas">+{vis.length - 3}</span>}
              </button>
            );
          })}
        </div>
      </div>

      <div className="card dia-invitados">
        <h3>{dDia.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" })}</h3>
        {domingo ? <p className="msg">El domingo no hay entrenamiento.</p> : (
          <>
            {delDia.length === 0 ? <p className="msg">Ningún invitado este día.</p> : (
              <ul className="lista-dia">
                {delDia.map((v) => (
                  <li key={v.id}>
                    <div className="quien">
                      <b>{v.inv.nombre}</b>
                      <span className="sub-inv">{divNombre(v.inv.division)} · {v.inv.entrenador_nombre}</span>
                    </div>
                    <div className="franjas">
                      {selector("manana", v.manana ?? "no",
                        (x) => accion(() => editarVisita(v.id, { manana: x === "no" ? null : x })),
                        !puedeTocar(v))}
                      {tardeCerrada ? <span className="msg">Tarde cerrada</span>
                        : selector("tarde", v.tarde ?? "no",
                          (x) => accion(() => editarVisita(v.id, { tarde: x === "no" ? null : x })),
                          !puedeTocar(v))}
                    </div>
                    <span className={`pill ${CLASE_VISITA[v.estado]}`}>{ESTADO_VISITA[v.estado]}</span>
                    <div className="row-actions">
                      {esAdmin && v.estado !== "APROBADA" && (
                        <button className="btn sm" onClick={() => accion(() => aprobarVisita(v.id))}>Aprobar</button>
                      )}
                      {esAdmin && v.estado === "PENDIENTE" && (
                        <button className="btn danger sm" onClick={() => accion(() => rechazarVisita(v.id))}>Rechazar</button>
                      )}
                      {puedeTocar(v) && (
                        <button className="btn ghost sm" title="Quitar este día"
                          onClick={() => accion(() => quitarVisita(v.id))}>✕</button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}

            <div className="anadir-conocido">
              <span className="etiqueta">Añadir un invitado conocido</span>
              <div className="fila-form">
                <select value={conocido.invitado} onChange={(e) => setConocido((c) => ({ ...c, invitado: e.target.value }))}>
                  <option value="">Elige invitado…</option>
                  {candidatos.map((i) => (
                    <option key={i.id} value={i.id}>{i.nombre} · {divNombre(i.division)}</option>
                  ))}
                </select>
                <label>Mañana{selector("manana", conocido.manana, (x) => setConocido((c) => ({ ...c, manana: x })))}</label>
                {!tardeCerrada && (
                  <label>Tarde{selector("tarde", conocido.tarde, (x) => setConocido((c) => ({ ...c, tarde: x })))}</label>
                )}
                <button className="btn sm" type="button" disabled={!conocido.invitado}
                  onClick={() => accion(async () => {
                    await anadirDiasInvitado(Number(conocido.invitado), { [dia]: bloques(conocido) });
                    setConocido({ invitado: "", manana: "", tarde: "no" });
                  })}>Añadir</button>
              </div>
            </div>
            {!nuevo ? (
              <button className="btn ghost" type="button" onClick={() => setNuevo(true)}>
                Nuevo invitado este día
              </button>
            ) : (
              <FormInvitado key={dia} cat={cat} esAdmin={esAdmin}
                inicial={{ ...VACIO, fechas: { [dia]: tardeCerrada ? { manana: "" } : { manana: "", tarde: "" } } }}
                onCancelar={() => setNuevo(false)}
                onGuardar={async (datos) => { await crearInvitado(datos); setNuevo(false); await recargar(); }} />
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** Una fila por invitado: su ficha, sus días, y añadirle más. */
function ListaInvitados({ items, cat, esAdmin, user, accion, franjas, divNombre, recargar }) {
  const [busca, setBusca] = useState("");
  const [abierto, setAbierto] = useState(null); // { id, modo: "ficha" | "dias" }
  const [nuevo, setNuevo] = useState(false);
  const hoy = iso(new Date());
  const filas = items
    .filter((i) => !busca.trim() || i.nombre.toLowerCase().includes(busca.trim().toLowerCase()))
    .sort((a, b) => a.nombre.localeCompare(b.nombre));
  const alternar = (id, modo) =>
    setAbierto((a) => (a && a.id === id && a.modo === modo ? null : { id, modo }));

  return (
    <>
      <div className="toolbar">
        <input className="search" placeholder="Buscar invitado…" value={busca}
          onChange={(e) => setBusca(e.target.value)} />
        {!nuevo && <button className="btn" onClick={() => setNuevo(true)}>Nuevo invitado</button>}
      </div>
      {nuevo && (
        <FormInvitado cat={cat} esAdmin={esAdmin} inicial={VACIO}
          onCancelar={() => setNuevo(false)}
          onGuardar={async (datos) => { await crearInvitado(datos); setNuevo(false); await recargar(); }} />
      )}
      <div className="card">
        <table className="data">
          <thead><tr>
            <th>Invitado</th><th>Gestiona</th><th>Próximo día</th><th>Días</th><th>Ficha</th>
            <th style={{ textAlign: "right" }}>Acciones</th>
          </tr></thead>
          <tbody>
            {filas.length === 0 ? (
              <tr><td colSpan={6} className="msg">Sin invitados.</td></tr>
            ) : filas.map((i) => {
              const vigentes = i.visitas.filter((v) => v.estado !== "RECHAZADA");
              const proximo = vigentes.find((v) => v.fecha >= hoy);
              const aprobadas = i.visitas.filter((v) => v.estado === "APROBADA").length;
              const pend = i.visitas.filter((v) => v.estado === "PENDIENTE").length;
              const puedeFicha = esAdmin || (i.estado === "PENDIENTE" && i.entrenador_solicitante === user?.entrenador_id);
              const abiertoAqui = abierto && abierto.id === i.id ? abierto.modo : null;
              return (
                <Fragment key={i.id}>
                  <tr>
                    <td>
                      <b>{i.nombre}</b>
                      <div className="sub-inv">
                        {divNombre(i.division)}{i.edad ? ` · ${i.edad} años` : ""}
                        {i.sexo ? ` · ${i.sexo === "CHICA" ? "chica" : "chico"}` : ""}
                      </div>
                    </td>
                    <td>{i.entrenador_nombre || "—"}</td>
                    <td>{proximo ? `${fecha(proximo.fecha)} · ${franjaTexto(proximo)}` : "—"}</td>
                    <td>
                      {aprobadas} aprobado{aprobadas === 1 ? "" : "s"}
                      {pend > 0 && <div className="sub-inv">{pend} pendiente{pend === 1 ? "" : "s"}</div>}
                    </td>
                    <td><span className={`pill ${ESTADO_CLASS[i.estado]}`}>{i.estado_display}</span></td>
                    <td>
                      <div className="row-actions">
                        <button className="btn ghost sm" onClick={() => alternar(i.id, "ficha")}>Ficha</button>
                        {i.estado !== "RECHAZADO" || esAdmin ? (
                          <button className="btn ghost sm" onClick={() => alternar(i.id, "dias")}>Añadir días</button>
                        ) : null}
                        {esAdmin && (pend > 0 || i.estado === "PENDIENTE") && (
                          <>
                            <button className="btn sm" onClick={() => accion(() => aprobarInvitado(i.id))}
                              title="La ficha y sus días pendientes">Aprobar</button>
                            <button className="btn danger sm" onClick={() => accion(() => rechazarInvitado(i.id))}>Rechazar</button>
                          </>
                        )}
                        {esAdmin && !i.jugador_creado && (
                          <button className="btn ghost sm" title="Borrar invitado"
                            onClick={() => window.confirm(`¿Borrar a ${i.nombre}?`)
                              && accion(() => borrarInvitado(i.id))}>🗑</button>
                        )}
                      </div>
                    </td>
                  </tr>
                  {abiertoAqui && (
                    <tr className="fila-form-inv"><td colSpan={6}>
                      {abiertoAqui === "ficha" ? (
                        <>
                          <FormInvitado cat={cat} esAdmin={esAdmin} existente soloLectura={!puedeFicha}
                            inicial={aFormulario(i)} onCancelar={() => setAbierto(null)}
                            onGuardar={async (datos) => { await editarInvitado(i.id, datos); setAbierto(null); await recargar(); }} />
                          <HistorialVisitas visitas={i.visitas} />
                        </>
                      ) : (
                        <AnadirDias i={i} franjas={franjas} onCancelar={() => setAbierto(null)}
                          onGuardar={async (fechas) => {
                            await anadirDiasInvitado(i.id, fechas); setAbierto(null); await recargar();
                          }} />
                      )}
                    </td></tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function HistorialVisitas({ visitas }) {
  if (!visitas.length) return null;
  return (
    <div className="historial-inv">
      <span className="etiqueta">Días</span>
      <div className="chips">
        {visitas.map((v) => (
          <span key={v.id} className={`chip-visita ${CLASE_VISITA[v.estado]}`}
            title={ESTADO_VISITA[v.estado]}>{fecha(v.fecha)} · {franjaTexto(v)}</span>
        ))}
      </div>
    </div>
  );
}

/** Volver a invitarle: solo días, la ficha no se toca. */
function AnadirDias({ i, franjas, onCancelar, onGuardar }) {
  const [fechas, setFechas] = useState({});
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);
  const marcadas = Object.fromEntries(i.visitas.filter((v) => v.estado !== "RECHAZADA")
    .map((v) => [v.fecha, ESTADO_VISITA[v.estado]]));
  return (
    <div className="inv-form card">
      <h3>Añadir días a {i.nombre}</h3>
      <p className="hint">Su ficha se queda como está. Los días nuevos los aprueba dirección
        {getUser()?.aprueba_invitados ? " (los tuyos quedan aprobados al guardar)" : ""}.</p>
      <Calendario fechas={fechas} onChange={(cambio) => setFechas((x) => cambio(x))}
        franjas={franjas} marcadas={marcadas} />
      {error && <p className="err">{error}</p>}
      <div className="row-actions">
        <button className="btn" disabled={guardando || !Object.keys(fechas).length}
          onClick={async () => {
            setGuardando(true); setError("");
            try { await onGuardar(fechas); } catch (e) { setError(String(e.message || e)); }
            setGuardando(false);
          }}>{guardando ? "Guardando…" : "Añadir días"}</button>
        <button className="btn ghost" onClick={onCancelar}>Cancelar</button>
      </div>
    </div>
  );
}

// Un invitado guardado, en el formato del formulario.
function aFormulario(i) {
  return {
    ...VACIO, ...i,
    edad: i.edad ?? "", division: i.division ?? "", escuela: i.escuela ?? "",
    sesiones_dia_max: i.sesiones_dia_max ?? "", jugar_con: i.jugar_con ?? "",
    entrena_con: i.entrena_con ?? "", pareja_division: i.pareja_division ?? "",
    fechas: {},
  };
}

function FormInvitado({ cat, esAdmin, inicial, existente, soloLectura, onCancelar, onGuardar }) {
  const [f, setF] = useState(inicial);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const set = (k) => (e) => {
    const v = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setF((x) => ({ ...x, [k]: v }));
  };
  const franjas = (bloque) => cat.turnos
    .filter((t) => (bloque === "manana" ? ["M1", "M2"] : ["T1", "T2"]).includes(t.codigo))
    .sort((a, b) => a.codigo.localeCompare(b.codigo));

  // Recibe una función sobre las fechas de ese momento: dos toques seguidos
  // no se pisan.
  const setFechas = (cambio) => setF((x) => ({ ...x, fechas: cambio(x.fechas) }));

  const num = (v) => (v === "" || v == null ? null : Number(v));
  async function enviar(e) {
    e.preventDefault();
    setGuardando(true); setError("");
    try {
      await onGuardar({
        nombre: f.nombre,
        ...(esAdmin && !existente && f.entrenador_solicitante
          ? { entrenador_solicitante: Number(f.entrenador_solicitante) } : {}),
        nota: f.nota, edad: num(f.edad), sexo: f.sexo,
        ...(!existente ? { fechas: f.fechas } : {}),
        division: num(f.division), vecindad: f.vecindad, pareja_division: f.pareja_division,
        escuela: num(f.escuela), sin_prioridad: f.sin_prioridad,
        sesiones_dia_max: num(f.sesiones_dia_max),
        superficie_pref: f.superficie_pref, superficie_estricta: f.superficie_estricta,
        jugar_con: num(f.jugar_con), pareja_estricta: f.pareja_estricta,
        no_coincidir_con: f.no_coincidir_con,
        entrena_con: num(f.entrena_con), entrena_con_estricto: f.entrena_con_estricto,
        no_entrena_con: f.no_entrena_con,
      });
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setGuardando(false);
    }
  }

  return (
    <form className="inv-form card form-invitado" onSubmit={enviar}>
      <h3>{existente ? `Ficha de ${inicial.nombre}` : "Nuevo invitado"}</h3>
      {existente && !soloLectura && inicial.estado === "APROBADO" && (
        <p className="hint">Lo que cambies aquí pasa a su ficha de jugador.</p>
      )}
      <fieldset className="sin-borde" disabled={soloLectura}>

      <fieldset>
        <legend>Quién es</legend>
        <div className="fila-form">
          <label className="crece">Nombre
            <input required value={f.nombre} onChange={set("nombre")} />
          </label>
          {esAdmin && !existente && (
            <label>Entrenador que lo propone
              <select required={!getUser()?.entrenador_id} value={f.entrenador_solicitante} onChange={set("entrenador_solicitante")}>
                <option value="">{getUser()?.entrenador_id ? "Yo" : "—"}</option>
                {cat.entrenadores.map((en) => <option key={en.id} value={en.id}>{en.nombre}</option>)}
              </select>
            </label>
          )}
          <label>Edad
            <input type="number" min="5" max="99" value={f.edad} onChange={set("edad")} style={{ width: "5rem" }} />
          </label>
          <label>Sexo
            <select value={f.sexo} onChange={set("sexo")}>
              <option value="">—</option><option value="CHICO">Chico</option><option value="CHICA">Chica</option>
            </select>
          </label>
        </div>
      </fieldset>

      {!existente && (
        <fieldset>
          <legend>Qué días viene</legend>
          <Calendario fechas={f.fechas} onChange={setFechas} franjas={franjas} />
        </fieldset>
      )}

      <fieldset>
        <legend>Ficha deportiva</legend>
        <div className="fila-form">
          <label>División
            <select required value={f.division} onChange={set("division")}>
              <option value="">—</option>
              {cat.divisiones.map((d) => <option key={d.id} value={d.id}>{d.nombre || `División ${d.nivel}`}</option>)}
            </select>
          </label>
          <label>Con qué divisiones entrena
            <select value={f.vecindad} onChange={set("vecindad")}>
              {VECINDAD.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
            </select>
          </label>
          <label>Se empareja preferentemente
            <select value={f.pareja_division} onChange={set("pareja_division")}>
              {PAREJA.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
            </select>
          </label>
          <label>Escuela
            <select value={f.escuela} onChange={set("escuela")}>
              <option value="">La del entrenador que lo propone</option>
              {cat.escuelas.map((x) => <option key={x.id} value={x.id}>{x.nombre}</option>)}
            </select>
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Lo que tiene en cuenta el motor</legend>
        <div className="fila-form">
          <label>Superficie
            <select value={f.superficie_pref} onChange={set("superficie_pref")}>
              <option value="">Indiferente</option>
              <option value="TIERRA">Tierra batida</option>
              <option value="RESINA">Resina (rápida)</option>
            </select>
          </label>
          {f.superficie_pref && (
            <label className="inv-check"><span>
              <input type="checkbox" checked={f.superficie_estricta} onChange={set("superficie_estricta")} />
              {" "}Solo en esa superficie</span>
            </label>
          )}
          <label>Máx. sesiones al día
            <input type="number" min="1" max="3" value={f.sesiones_dia_max}
              onChange={set("sesiones_dia_max")} style={{ width: "5rem" }} />
          </label>
          <label className="inv-check"><span>
            <input type="checkbox" checked={f.sin_prioridad} onChange={set("sin_prioridad")} />
            {" "}Sin prioridad (entra solo si sobra sitio)</span>
          </label>
        </div>
        <div className="fila-form">
          <label className="crece">Juega con
            <select value={f.jugar_con} onChange={set("jugar_con")}>
              <option value="">—</option>
              {cat.jugadores.map((j) => <option key={j.id} value={j.id}>{j.nombre}</option>)}
            </select>
          </label>
          {f.jugar_con && (
            <label className="inv-check"><span>
              <input type="checkbox" checked={f.pareja_estricta} onChange={set("pareja_estricta")} />
              {" "}Misma pista obligatoria</span>
            </label>
          )}
          <label className="crece">Entrena con (entrenador)
            <select value={f.entrena_con} onChange={set("entrena_con")}>
              <option value="">—</option>
              {cat.entrenadores.map((e) => <option key={e.id} value={e.id}>{e.nombre}</option>)}
            </select>
          </label>
          {f.entrena_con && (
            <label className="inv-check"><span>
              <input type="checkbox" checked={f.entrena_con_estricto} onChange={set("entrena_con_estricto")} />
              {" "}Siempre con él</span>
            </label>
          )}
        </div>
        <Multiple titulo="No debe coincidir en pista con" opciones={cat.jugadores}
          valor={f.no_coincidir_con} onChange={(v) => setF((x) => ({ ...x, no_coincidir_con: v }))} />
        <Multiple titulo="No entrena con (entrenadores)" opciones={cat.entrenadores}
          valor={f.no_entrena_con} onChange={(v) => setF((x) => ({ ...x, no_entrena_con: v }))} />
        <div className="fila-form">
          <label className="crece">Nota
            <input value={f.nota} onChange={set("nota")} placeholder="Opcional" />
          </label>
        </div>
      </fieldset>

      </fieldset>
      {error && <p className="err">{error}</p>}
      <div className="row-actions">
        {!soloLectura && (
          <button className="btn" disabled={guardando}>
            {guardando ? "Guardando…" : existente ? "Guardar ficha" : esAdmin ? "Añadir (queda aprobado)" : "Solicitar"}
          </button>
        )}
        <button type="button" className="btn ghost" onClick={onCancelar}>
          {soloLectura ? "Cerrar" : "Cancelar"}</button>
      </div>
    </form>
  );
}

function Multiple({ titulo, opciones, valor, onChange }) {
  const elegidos = opciones.filter((o) => valor.includes(o.id));
  return (
    <div className="multiple-inv">
      <span className="etiqueta">{titulo}</span>
      <div className="chips">
        {elegidos.map((o) => (
          <button type="button" key={o.id} className="chip on" title="Quitar"
            onClick={() => onChange(valor.filter((x) => x !== o.id))}>{o.nombre} ✕</button>
        ))}
        <select value="" onChange={(e) => e.target.value && onChange([...valor, Number(e.target.value)])}>
          <option value="">Añadir…</option>
          {opciones.filter((o) => !valor.includes(o.id)).map((o) => (
            <option key={o.id} value={o.id}>{o.nombre}</option>
          ))}
        </select>
      </div>
    </div>
  );
}

/**
 * Los días que viene, en un calendario: se tocan los días y, debajo, cada uno
 * con su mañana y su tarde (de entrada, las dos y la franja que encaje). El
 * domingo no se entrena y el miércoles y el sábado por la tarde, tampoco.
 */
function Calendario({ fechas, onChange, franjas, marcadas = {} }) {
  const primera = Object.keys(fechas).sort()[0];
  const [mes, setMes] = useState(() => {
    const d = primera ? deIso(primera) : new Date();
    return new Date(d.getFullYear(), d.getMonth(), 1);
  });
  const hoy = iso(new Date());

  const celdas = [];
  for (let i = 0; i < diaSemana(mes); i++) celdas.push(null);
  const fin = new Date(mes.getFullYear(), mes.getMonth() + 1, 0).getDate();
  for (let d = 1; d <= fin; d++) celdas.push(new Date(mes.getFullYear(), mes.getMonth(), d));

  const alternar = (d) => onChange((actuales) => {
    const clave = iso(d);
    const nuevas = { ...actuales };
    if (nuevas[clave]) delete nuevas[clave];
    else nuevas[clave] = TARDE_CERRADA.has(diaSemana(d)) ? { manana: "" } : { manana: "", tarde: "" };
    return nuevas;
  });
  const setBloque = (clave, bloque, valor) => onChange((actuales) => {
    const fila = { ...actuales[clave] };
    if (valor === "no") delete fila[bloque]; else fila[bloque] = valor;
    const nuevas = { ...actuales };
    if (Object.keys(fila).length) nuevas[clave] = fila; else delete nuevas[clave];
    return nuevas;
  });
  // Lo mismo para todos los días marcados (donde se pueda).
  const paraTodos = (bloque, valor) => onChange((actuales) => {
    const nuevas = {};
    for (const [clave, fila] of Object.entries(actuales)) {
      const f2 = { ...fila };
      const cerrado = bloque === "tarde" && TARDE_CERRADA.has(diaSemana(deIso(clave)));
      if (valor === "no" || cerrado) delete f2[bloque]; else f2[bloque] = valor;
      if (Object.keys(f2).length) nuevas[clave] = f2;
    }
    return nuevas;
  });
  const selector = (bloque, valor, onSel, conVacio = false) => (
    <select value={valor} onChange={(e) => onSel(e.target.value)}>
      {conVacio && <option value="-">—</option>}
      <option value="no">No viene</option>
      <option value="">Sí · la que encaje</option>
      {franjas(bloque).map((t) => (
        <option key={t.codigo} value={t.codigo}>
          {t.codigo} · {String(t.hora_inicio || "").slice(0, 5)}
        </option>
      ))}
    </select>
  );
  const elegidas = Object.keys(fechas).sort();

  return (
    <div className="calendario-inv">
      <div className="cal-mes">
        <div className="cal-nav">
          <button type="button" className="btn ghost sm"
            onClick={() => setMes(new Date(mes.getFullYear(), mes.getMonth() - 1, 1))}>‹</button>
          <b>{mes.toLocaleDateString("es-ES", { month: "long", year: "numeric" })}</b>
          <button type="button" className="btn ghost sm"
            onClick={() => setMes(new Date(mes.getFullYear(), mes.getMonth() + 1, 1))}>›</button>
        </div>
        <div className="cal-rejilla">
          {SEMANA.map((x) => <span key={x} className="cal-cab">{x}</span>)}
          {celdas.map((d, i) => {
            if (!d) return <span key={`v${i}`} />;
            const clave = iso(d);
            const domingo = diaSemana(d) === 6;
            return (
              <button type="button" key={clave} disabled={domingo}
                title={marcadas[clave] ? `Ya viene (${marcadas[clave].toLowerCase()})` : undefined}
                className={["cal-dia", fechas[clave] ? "on" : "", clave === hoy ? "hoy" : "",
                  clave < hoy ? "pasado" : "", marcadas[clave] ? "ya" : ""].filter(Boolean).join(" ")}
                onClick={() => alternar(d)}>{d.getDate()}</button>
            );
          })}
        </div>
      </div>
      <div className="cal-elegidas">
        {elegidas.length === 0 ? (
          <p className="hint">Toca en el calendario los días que viene.</p>
        ) : (
          <table className="data dias-invitado">
            <thead><tr><th>Día</th><th>Mañana</th><th>Tarde</th><th /></tr></thead>
            <tbody>
              {elegidas.length > 1 && (
                <tr className="para-todos">
                  <td>Todos</td>
                  <td>{selector("manana", "-", (v) => v !== "-" && paraTodos("manana", v), true)}</td>
                  <td>{selector("tarde", "-", (v) => v !== "-" && paraTodos("tarde", v), true)}</td>
                  <td />
                </tr>
              )}
              {elegidas.map((clave) => {
                const d = deIso(clave);
                const fila = fechas[clave];
                return (
                  <tr key={clave}>
                    <td>{d.toLocaleDateString("es-ES", { weekday: "short", day: "numeric", month: "short" })}</td>
                    <td>{selector("manana", fila.manana ?? "no", (v) => setBloque(clave, "manana", v))}</td>
                    <td>{TARDE_CERRADA.has(diaSemana(d)) ? <span className="msg">Cerrado</span>
                      : selector("tarde", fila.tarde ?? "no", (v) => setBloque(clave, "tarde", v))}</td>
                    <td><button type="button" className="btn ghost sm" title="Quitar este día"
                      onClick={() => alternar(d)}>✕</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
