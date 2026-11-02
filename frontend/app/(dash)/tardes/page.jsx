"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  altaEquipoTardes, bajaEquipoTardes, bajaJugadorTardes, crearJugadorTardes, editarJugadorTardes,
  getEquipoTardes, getJugadoresTardes, reactivarJugadorTardes,
} from "../../../lib/api";
import { fmtLarga } from "../../../lib/torneos";

const hoy = () => new Date().toISOString().slice(0, 10);
const VACIO = { nombre: "", sexo: "", fecha_nacimiento: "", fecha_alta: hoy(), email: "", quien_1: "", email_2: "",
  quien_2: "", idioma: "ES" };

/** Alta o cambios de un jugador. Las fechas vacías se mandan como null. */
function FichaJugador({ inicial, onGuardar, onCancelar }) {
  const [f, setF] = useState({ ...VACIO, ...inicial });
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const cambia = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));

  async function guardar(e) {
    e.preventDefault();
    setGuardando(true); setError("");
    const datos = { ...f, fecha_nacimiento: f.fecha_nacimiento || null, fecha_alta: f.fecha_alta || null };
    try { await onGuardar(datos); } catch (err) { setError(err.message); setGuardando(false); }
  }

  return (
    <form className="card inf-form tardes-ficha" onSubmit={guardar}>
      <div className="tardes-campos">
        <label>Nombre y apellidos<input value={f.nombre} onChange={cambia("nombre")} required /></label>
        <label>Chico o chica
          <select value={f.sexo} onChange={cambia("sexo")}>
            <option value="">Sin indicar</option>
            <option value="CHICO">Chico</option>
            <option value="CHICA">Chica</option>
          </select>
        </label>
        <label>Fecha de nacimiento<input type="date" value={f.fecha_nacimiento || ""} onChange={cambia("fecha_nacimiento")} /></label>
        <label>Fecha de alta<input type="date" value={f.fecha_alta || ""} onChange={cambia("fecha_alta")} /></label>
        <label>Email de la familia<input type="email" value={f.email} onChange={cambia("email")} /></label>
        <label>¿Quién es?<input value={f.quien_1} onChange={cambia("quien_1")} placeholder="Madre, padre…" /></label>
        <label>Segundo email (opcional)<input type="email" value={f.email_2} onChange={cambia("email_2")} /></label>
        <label>¿Quién es?<input value={f.quien_2} onChange={cambia("quien_2")} placeholder="Madre, padre…" /></label>
        <label>Idioma del informe para la familia
          <select value={f.idioma} onChange={cambia("idioma")}>
            <option value="ES">Español</option>
            <option value="EN">Inglés</option>
          </select>
        </label>
      </div>
      <p className="eval-nota">
        El informe se hace siempre en español; el idioma solo cambia el PDF que se envía a la familia.
      </p>
      {error && <p className="err">{error}</p>}
      <div className="eval-pie">
        <button type="button" className="btn ghost" onClick={onCancelar}>Cancelar</button>
        <button type="submit" className="btn" disabled={guardando}>{guardando ? "Guardando…" : "Guardar"}</button>
      </div>
    </form>
  );
}

function FilaJugador({ j, onCambio }) {
  const [modo, setModo] = useState(null); // null | "editar" | "baja"
  const [fecha, setFecha] = useState(hoy());
  const [error, setError] = useState("");
  const deBaja = j.fecha_baja && j.fecha_baja < hoy();

  async function hacer(fn) {
    setError("");
    try { onCambio(await fn()); setModo(null); } catch (e) { setError(e.message); }
  }

  if (modo === "editar") {
    return (
      <li>
        <FichaJugador inicial={j} onCancelar={() => setModo(null)}
          onGuardar={async (datos) => { onCambio(await editarJugadorTardes(j.id, datos)); setModo(null); }} />
      </li>
    );
  }
  return (
    <li className="card inf-fila">
      <div className="inf-fila-cab">
        <span className="eval-lista-nombre">{j.nombre}</span>
        {j.edad != null && <span className="eval-lista-meta">{j.edad} años</span>}
        {j.idioma === "EN" && <span className="pill gris">informe en inglés</span>}
        {deBaja ? <span className="pill no">De baja desde el {fmtLarga(j.fecha_baja)}</span>
          : j.fecha_baja ? <span className="pill pend">Baja el {fmtLarga(j.fecha_baja)}</span>
          : j.fecha_alta && <span className="pill ok">Alta el {fmtLarga(j.fecha_alta)}</span>}
      </div>
      <div className="inf-fila-partes">
        <span className="inf-asignado">Entrenador: <b>{j.evaluador?.nombre || "sin asignar"}</b></span>
        <span className="inf-asignado">
          Familia: <b>{[j.email, j.email_2].filter(Boolean).join(" · ") || "sin email"}</b>
        </span>
      </div>
      <div className="inf-fila-pie">
        {modo === "baja" ? (
          <>
            <label className="inf-asignado">Baja desde
              <input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} />
            </label>
            <button type="button" className="btn ghost sm" onClick={() => setModo(null)}>Cancelar</button>
            <button type="button" className="btn danger sm" disabled={!fecha}
              onClick={() => hacer(() => bajaJugadorTardes(j.id, fecha))}>Dar de baja</button>
          </>
        ) : (
          <>
            <button type="button" className="btn ghost sm" onClick={() => setModo("editar")}>Editar</button>
            {j.fecha_baja
              ? <button type="button" className="btn ghost sm" onClick={() => hacer(() => reactivarJugadorTardes(j.id))}>Quitar la baja</button>
              : <button type="button" className="btn ghost sm" onClick={() => setModo("baja")}>Dar de baja</button>}
          </>
        )}
        {error && <span className="err">{error}</span>}
      </div>
    </li>
  );
}

function Jugadores() {
  const [lista, setLista] = useState(null);
  const [bajas, setBajas] = useState(false);
  const [busca, setBusca] = useState("");
  const [nuevo, setNuevo] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { getJugadoresTardes(bajas).then(setLista).catch((e) => setError(e.message)); }, [bajas]);

  if (error) return <p className="err">{error}</p>;
  if (!lista) return <p className="msg">Cargando…</p>;
  const q = busca.trim().toLowerCase();
  const visibles = lista.filter((j) => !q || j.nombre.toLowerCase().includes(q));
  const cambia = (j) => setLista((l) => l.map((x) => (x.id === j.id ? j : x)));

  return (
    <>
      <div className="inf-filtros">
        <input className="eval-busca" type="search" placeholder="Buscar jugador" value={busca}
          onChange={(e) => setBusca(e.target.value)} />
        <label className="inf-asignado tardes-bajas">
          <input type="checkbox" checked={bajas} onChange={(e) => setBajas(e.target.checked)} /> Ver también las bajas
        </label>
        {!nuevo && <button type="button" className="btn" onClick={() => setNuevo(true)}>Nuevo jugador</button>}
      </div>
      {nuevo && (
        <FichaJugador onCancelar={() => setNuevo(false)} onGuardar={async (datos) => {
          const j = await crearJugadorTardes(datos);
          setLista((l) => [...l, j].sort((a, b) => a.nombre.localeCompare(b.nombre)));
          setNuevo(false);
        }} />
      )}
      <p className="eval-nota">{visibles.length} jugador{visibles.length === 1 ? "" : "es"}. El entrenador de cada uno se asigna en <Link href="/informes">Informes</Link>.</p>
      <ul className="inf-lista">
        {visibles.map((j) => <FilaJugador key={j.id} j={j} onCambio={cambia} />)}
      </ul>
    </>
  );
}

const FUNCIONES = [["TENIS", "Entrenadores de tenis"], ["FISICO", "Preparación física"]];

function Equipo() {
  const [datos, setDatos] = useState(null);
  const [elegido, setElegido] = useState({ TENIS: "", FISICO: "" });
  const [error, setError] = useState("");

  const cargar = () => getEquipoTardes().then(setDatos).catch((e) => setError(e.message));
  useEffect(() => { cargar(); }, []);

  async function hacer(fn) {
    setError("");
    try { await fn(); await cargar(); } catch (e) { setError(e.message); }
  }

  if (!datos) return error ? <p className="err">{error}</p> : <p className="msg">Cargando…</p>;
  return (
    <>
      <p className="eval-nota">
        Quién hace los informes de Competición de tardes. Los de tenis salen en el desplegable para asignar
        jugadores en Informes; a los de física les llegan los recordatorios de la parte física. Solo se puede
        añadir a quien ya tiene usuario en la app.
      </p>
      {FUNCIONES.map(([funcion, titulo]) => {
        const miembros = datos.miembros.filter((m) => m.funcion === funcion);
        const ya = new Set(miembros.map((m) => m.usuario));
        return (
          <section key={funcion} className="card tardes-equipo">
            <h2>{titulo}</h2>
            {miembros.length === 0 ? <p className="eval-nota">Nadie todavía.</p> : (
              <ul className="tardes-miembros">
                {miembros.map((m) => (
                  <li key={m.id}>
                    <span>{m.nombre}</span>
                    <button type="button" className="btn ghost sm" onClick={() => hacer(() => bajaEquipoTardes(m.id))}>
                      Dar de baja
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="inf-dest">
              <select value={elegido[funcion]} onChange={(e) => setElegido((x) => ({ ...x, [funcion]: e.target.value }))}>
                <option value="">Elige a quién añadir…</option>
                {datos.candidatos.filter((c) => !ya.has(c.id)).map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
              </select>
              <button type="button" className="btn sm" disabled={!elegido[funcion]}
                onClick={() => hacer(async () => {
                  await altaEquipoTardes(Number(elegido[funcion]), funcion);
                  setElegido((x) => ({ ...x, [funcion]: "" }));
                })}>Dar de alta</button>
            </div>
          </section>
        );
      })}
      {error && <p className="err">{error}</p>}
    </>
  );
}

export default function TardesPage() {
  const [vista, setVista] = useState("jugadores");
  return (
    <div>
      <div className="page-head"><h1>Competición de tardes</h1></div>
      <p className="help">
        Los jugadores de <b>Competición de tardes</b> y el equipo que hace sus informes. Aquí se dan de alta
        y de baja; los informes se reparten, se hacen y se validan en <Link href="/informes">Informes</Link>.
      </p>
      <div className="tabs-inv" role="tablist">
        {[["jugadores", "Jugadores"], ["equipo", "Entrenadores"]].map(([k, t]) => (
          <button key={k} type="button" role="tab" aria-selected={vista === k}
            className={`chip${vista === k ? " on" : ""}`} onClick={() => setVista(k)}>{t}</button>
        ))}
      </div>
      {vista === "jugadores" ? <Jugadores /> : <Equipo />}
    </div>
  );
}
