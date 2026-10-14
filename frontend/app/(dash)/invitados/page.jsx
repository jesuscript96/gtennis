"use client";
import { useEffect, useState } from "react";
import {
  getInvitados, crearInvitado, editarInvitado, aprobarInvitado, rechazarInvitado,
  getUser, resource,
} from "../../../lib/api";

/**
 * Invitados (14/10/2026): se proponen como un jugador nuevo. Lo que importa es
 * su ficha deportiva, pero va también todo lo que mira el motor —con quién
 * juega y con quién no, superficie, entrenador— y, sobre todo, las fechas y
 * los días en que viene. Al aprobarlo, dirección crea el jugador con todo eso
 * y el motor solo lo pone esos días.
 *
 * Quedan guardados: si vuelve otro mes, «Volver a invitar» abre el formulario
 * con todo lo de la última vez menos las fechas, y al aprobarlo es el mismo
 * jugador (con su historial), no uno nuevo.
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

function resumenDias(fechas) {
  const partes = Object.entries(fechas || {}).sort().map(([f, b]) => {
    const bloques = [];
    if (b.manana != null) bloques.push(b.manana || "mañana");
    if (b.tarde != null) bloques.push(b.tarde || "tarde");
    return `${fecha(f)} ${bloques.join("+")}`;
  });
  return partes.join(" · ") || "—";
}

export default function InvitadosPage() {
  const [items, setItems] = useState(null);
  const [cat, setCat] = useState({ jugadores: [], entrenadores: [], divisiones: [], escuelas: [], turnos: [] });
  const [error, setError] = useState(null);
  const [editando, setEditando] = useState(null); // null | "nuevo" | id
  // Datos con los que se abre el formulario nuevo (vacío, o copiados de la
  // última vez que vino).
  const [base, setBase] = useState(VACIO);
  const [busca, setBusca] = useState("");
  const user = getUser();
  const esAdmin = !!user?.is_superadmin;

  async function load() {
    try { setItems(await getInvitados()); } catch (e) { setError(String(e.message || e)); }
  }
  useEffect(() => {
    load();
    const lista = (r) => resource(r).list().catch(() => []);
    Promise.all([lista("jugadores"), lista("entrenadores"), lista("divisiones"),
      lista("escuelas"), lista("turnos")])
      .then(([jugadores, entrenadores, divisiones, escuelas, turnos]) => setCat({
        jugadores: jugadores.filter((j) => j.activo !== false),
        entrenadores: entrenadores.filter((e) => e.activo !== false),
        divisiones, escuelas, turnos,
      }));
  }, []);

  async function accion(fn) {
    try { await fn(); await load(); } catch (e) { alert(String(e.message || e)); }
  }

  if (error && !items) return <p className="err">{error}</p>;
  if (!items) return <p className="msg">Cargando invitados…</p>;

  const pendientes = items.filter((i) => i.estado === "PENDIENTE");
  const divNombre = (id) => {
    const d = cat.divisiones.find((x) => x.id === id);
    return d ? `D${d.nivel}` : "—";
  };

  return (
    <div className="page invitados">
      <div className="page-head">
        <h1>Invitados</h1>
        {editando !== "nuevo" && (
          <button className="btn" onClick={() => { setBase(VACIO); setEditando("nuevo"); }}>
            Nuevo invitado
          </button>
        )}
      </div>
      <p className="help">
        Un invitado se da de alta como un jugador nuevo: su ficha deportiva, lo
        que el motor tiene en cuenta y las fechas y días en que viene.
        {esAdmin
          ? " Al aprobarlo se crea el jugador y entra en el cuadrante solo esos días."
          : " Dirección deportiva lo aprueba antes de que entre en los entrenamientos."}
      </p>

      {editando === "nuevo" && (
        <FormInvitado key={base.repite_de || "nuevo"} cat={cat} esAdmin={esAdmin} inicial={base}
          onCancelar={() => setEditando(null)}
          onGuardar={async (datos) => { await crearInvitado(datos); setEditando(null); await load(); }} />
      )}

      {esAdmin && pendientes.length > 0 && (
        <p className="help" style={{ borderLeftColor: "var(--accent)" }}>
          Tienes <b>{pendientes.length}</b> invitado(s) pendiente(s) de aprobar.
        </p>
      )}

      <div className="toolbar">
        <input className="search" placeholder="Buscar invitado…" value={busca}
          onChange={(e) => setBusca(e.target.value)} />
      </div>

      <div className="card">
        <table className="data">
          <thead><tr>
            <th>Invitado</th><th>Propone</th><th>Viene</th><th>Días</th><th>Estado</th>
            <th style={{ textAlign: "right" }}>Acciones</th>
          </tr></thead>
          <tbody>
            {items.length === 0 ? (
              <tr><td colSpan={6} className="msg">Sin invitados.</td></tr>
            ) : items.filter((i) => !busca.trim()
                || i.nombre.toLowerCase().includes(busca.trim().toLowerCase())).map((i) => (
              <FilaInvitado key={i.id} i={i} cat={cat} esAdmin={esAdmin}
                divNombre={divNombre} abierto={editando === i.id}
                onEditar={() => setEditando(editando === i.id ? null : i.id)}
                onGuardar={async (datos) => { await editarInvitado(i.id, datos); setEditando(null); await load(); }}
                onRepetir={() => {
                  setBase({
                    ...aFormulario(i), fechas: {},
                    entrenador_solicitante: i.entrenador_solicitante ?? "", repite_de: i.id,
                  });
                  setEditando("nuevo");
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
                onAprobar={() => accion(() => aprobarInvitado(i.id))}
                onRechazar={() => accion(() => rechazarInvitado(i.id))} />
            ))}
          </tbody>
        </table>
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
    fechas: i.fechas || {},
  };
}

function FilaInvitado({ i, cat, esAdmin, divNombre, abierto, onEditar, onGuardar, onRepetir, onAprobar, onRechazar }) {
  const pendiente = i.estado === "PENDIENTE";
  const incompleto = !Object.keys(i.fechas || {}).length;
  return (
    <>
      <tr>
        <td>
          <b>{i.nombre}</b>
          <div className="sub-inv">
            {divNombre(i.division)}{i.edad ? ` · ${i.edad} años` : ""}
            {i.sexo ? ` · ${i.sexo === "CHICA" ? "chica" : "chico"}` : ""}
          </div>
        </td>
        <td>{i.entrenador_nombre || "—"}</td>
        <td>{!i.fecha_desde ? <span className="marca-baja">Sin días</span>
          : i.fecha_desde === i.fecha_hasta ? fecha(i.fecha_desde)
          : `${fecha(i.fecha_desde)} – ${fecha(i.fecha_hasta)}`}</td>
        <td className="dias-inv">{resumenDias(i.fechas)}</td>
        <td><span className={`pill ${ESTADO_CLASS[i.estado]}`}>{i.estado_display}</span></td>
        <td>
          <div className="row-actions">
            {pendiente && (
              <button className="btn ghost sm" onClick={onEditar}>{abierto ? "Cerrar" : "Ver / editar"}</button>
            )}
            {!pendiente && (
              <button className="btn ghost sm" onClick={onRepetir}
                title="Con todo lo de esta vez, menos las fechas">Volver a invitar</button>
            )}
            {esAdmin && pendiente && (
              <>
                <button className="btn sm" onClick={onAprobar} disabled={incompleto}
                  title={incompleto ? "Faltan las fechas o los días que viene" : undefined}>Aprobar</button>
                <button className="btn danger sm" onClick={onRechazar}>Rechazar</button>
              </>
            )}
          </div>
        </td>
      </tr>
      {abierto && (
        <tr className="fila-form-inv"><td colSpan={6}>
          <FormInvitado cat={cat} esAdmin={esAdmin} existente inicial={aFormulario(i)}
            onCancelar={onEditar} onGuardar={onGuardar} />
        </td></tr>
      )}
    </>
  );
}

function FormInvitado({ cat, esAdmin, inicial, existente, onCancelar, onGuardar }) {
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
        fechas: f.fechas,
        division: num(f.division), vecindad: f.vecindad, pareja_division: f.pareja_division,
        escuela: num(f.escuela), sin_prioridad: f.sin_prioridad,
        sesiones_dia_max: num(f.sesiones_dia_max),
        superficie_pref: f.superficie_pref, superficie_estricta: f.superficie_estricta,
        jugar_con: num(f.jugar_con), pareja_estricta: f.pareja_estricta,
        no_coincidir_con: f.no_coincidir_con,
        entrena_con: num(f.entrena_con), entrena_con_estricto: f.entrena_con_estricto,
        no_entrena_con: f.no_entrena_con,
        ...(!existente && f.repite_de ? { repite_de: f.repite_de } : {}),
      });
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setGuardando(false);
    }
  }

  return (
    <form className="inv-form card form-invitado" onSubmit={enviar}>
      <h3>{existente ? `Invitado: ${inicial.nombre}`
        : inicial.repite_de ? `Vuelve: ${inicial.nombre}` : "Nuevo invitado"}</h3>
      {inicial.repite_de && !existente && (
        <p className="hint">Con todo lo de la última vez. Pon las fechas, revisa los días y
          solicita: al aprobarlo es el mismo jugador.</p>
      )}

      <fieldset>
        <legend>Quién es</legend>
        <div className="fila-form">
          <label className="crece">Nombre
            <input required value={f.nombre} onChange={set("nombre")} />
          </label>
          {esAdmin && !existente && (
            <label>Entrenador que lo propone
              <select required value={f.entrenador_solicitante} onChange={set("entrenador_solicitante")}>
                <option value="">—</option>
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

      <fieldset>
        <legend>Cuándo viene</legend>
        <Calendario fechas={f.fechas} onChange={setFechas} franjas={franjas} />
      </fieldset>

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

      {error && <p className="err">{error}</p>}
      <div className="row-actions">
        <button className="btn" disabled={guardando}>
          {guardando ? "Guardando…" : existente ? "Guardar cambios" : "Solicitar"}
        </button>
        <button type="button" className="btn ghost" onClick={onCancelar}>Cancelar</button>
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
function Calendario({ fechas, onChange, franjas }) {
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
                className={["cal-dia", fechas[clave] ? "on" : "", clave === hoy ? "hoy" : "",
                  clave < hoy ? "pasado" : ""].filter(Boolean).join(" ")}
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
