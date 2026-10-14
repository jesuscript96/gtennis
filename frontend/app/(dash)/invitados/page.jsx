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
const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];
// El club no abre el miércoles ni el sábado por la tarde.
const TARDE_CERRADA = new Set([2, 5]);
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
  fecha_desde: "", fecha_hasta: "", dias: {},
  division: "", vecindad: "CLUB", pareja_division: "", escuela: "",
  sin_prioridad: false, sesiones_dia_max: "",
  superficie_pref: "", superficie_estricta: true,
  jugar_con: "", pareja_estricta: true, no_coincidir_con: [],
  entrena_con: "", entrena_con_estricto: false, no_entrena_con: [],
};

const fecha = (f) => (f ? new Date(`${f}T12:00`).toLocaleDateString("es-ES",
  { day: "numeric", month: "short" }) : "—");

function resumenDias(dias) {
  const partes = Object.entries(dias || {}).sort().map(([d, b]) => {
    const bloques = [];
    if (b.manana != null) bloques.push(b.manana || "mañana");
    if (b.tarde != null) bloques.push(b.tarde || "tarde");
    return `${DIAS[d].slice(0, 3)} ${bloques.join("+")}`;
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
                    ...aFormulario(i), fecha_desde: "", fecha_hasta: "",
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
    fecha_desde: i.fecha_desde ?? "", fecha_hasta: i.fecha_hasta ?? "",
  };
}

function FilaInvitado({ i, cat, esAdmin, divNombre, abierto, onEditar, onGuardar, onRepetir, onAprobar, onRechazar }) {
  const pendiente = i.estado === "PENDIENTE";
  const incompleto = !i.fecha_desde || !i.fecha_hasta || !Object.keys(i.dias || {}).length;
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
        <td>{i.fecha_desde ? `${fecha(i.fecha_desde)} – ${fecha(i.fecha_hasta)}` : <span className="marca-baja">Sin fechas</span>}</td>
        <td className="dias-inv">{resumenDias(i.dias)}</td>
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

  const setDia = (dia, bloque, valor) => setF((x) => {
    const dias = { ...x.dias };
    const fila = { ...(dias[dia] || {}) };
    if (valor === "no") delete fila[bloque]; else fila[bloque] = valor;
    if (Object.keys(fila).length) dias[dia] = fila; else delete dias[dia];
    return { ...x, dias };
  });
  const semanaEntera = () => setF((x) => {
    const dias = {};
    for (let d = 0; d < 5; d++) dias[d] = TARDE_CERRADA.has(d) ? { manana: "" } : { manana: "", tarde: "" };
    return { ...x, dias };
  });

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
        fecha_desde: f.fecha_desde || null, fecha_hasta: f.fecha_hasta || null, dias: f.dias,
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
        <div className="fila-form">
          <label>Desde<input type="date" required value={f.fecha_desde} onChange={set("fecha_desde")} /></label>
          <label>Hasta<input type="date" required min={f.fecha_desde || undefined}
            value={f.fecha_hasta} onChange={set("fecha_hasta")} /></label>
          <button type="button" className="btn ghost sm" onClick={semanaEntera}>
            De lunes a viernes, mañana y tarde
          </button>
        </div>
        <table className="data dias-invitado">
          <thead><tr><th>Día</th><th>Mañana</th><th>Tarde</th></tr></thead>
          <tbody>
            {DIAS.map((nombre, d) => (
              <tr key={d}>
                <td>{nombre}</td>
                {["manana", "tarde"].map((bloque) => {
                  const cerrado = bloque === "tarde" && TARDE_CERRADA.has(d);
                  const valor = f.dias[d]?.[bloque];
                  return (
                    <td key={bloque}>
                      {cerrado ? <span className="msg">Cerrado</span> : (
                        <select value={valor == null ? "no" : valor}
                          onChange={(e) => setDia(d, bloque, e.target.value)}>
                          <option value="no">No viene</option>
                          <option value="">Viene · la franja que encaje</option>
                          {franjas(bloque).map((t) => (
                            <option key={t.codigo} value={t.codigo}>
                              {t.codigo} · {String(t.hora_inicio || "").slice(0, 5)}
                            </option>
                          ))}
                        </select>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
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
