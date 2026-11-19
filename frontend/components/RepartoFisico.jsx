"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { asignarFisico, getRepartoFisico } from "../lib/api";
import { abrirParte } from "../lib/informes";
import { fmtLarga } from "../lib/torneos";

// Quién hace la parte física de cada jugador (19/11/2026). Quien coordina la
// preparación física (Josep Mari) lo reparte: en Alto rendimiento entre quienes
// tienen «Evalúa física de Alto rendimiento» y en Competición de tardes entre el
// equipo de física de tardes. Los demás ven el reparto y sus «Asignados a mí».

const ESCUELAS = [["tardes", "Competición de tardes"], ["alto_rendimiento", "Alto rendimiento"]];

function pasa(j, filtro, yo) {
  if (filtro === "mios") return j.evaluador?.id === yo;
  if (filtro === "sin") return !j.evaluador;
  return true;
}

function textoUltima(u) {
  if (!u) return ["Sin evaluar", "gris"];
  if (u.estado === "BORRADOR") return ["A medias", "pend"];
  return [`Última: ${fmtLarga(u.fecha)}`, "ok"];
}

/** El desplegable de una escuela; si el asignado ya no está en su equipo, sale igual. */
function Opciones({ equipo, actual }) {
  const lista = actual && !equipo.some((u) => u.id === actual.id) ? [...equipo, actual] : equipo;
  return lista.map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>);
}

function Fila({ j, datos, asignar, guardando }) {
  const router = useRouter();
  const [error, setError] = useState("");
  const [texto, pill] = textoUltima(j.ultima);
  const seguir = j.ultima?.estado === "BORRADOR";
  return (
    <li className="card inf-fila">
      <div className="inf-fila-cab">
        <span className="eval-lista-nombre">{j.nombre}</span>
        {j.edad != null && <span className="eval-lista-meta">{j.edad} años</span>}
        <span className={`pill ${pill}`}>{texto}</span>
      </div>
      <div className="inf-fila-partes">
        {datos.puede_asignar ? (
          <label className="inf-asignado">
            Lo evalúa:
            <select value={j.evaluador?.id || ""} disabled={guardando}
              onChange={(e) => asignar([j.id], e.target.value)}>
              <option value="">Sin asignar</option>
              <Opciones equipo={datos.evaluadores[j.circuito]} actual={j.evaluador} />
            </select>
          </label>
        ) : (
          <span className="inf-asignado">Lo evalúa: <b>{j.evaluador?.nombre || "sin asignar"}</b></span>
        )}
        <button type="button" className="btn ghost sm"
          onClick={() => abrirParte(router, j.id, "fisico", seguir ? j.ultima.id : null).catch((e) => setError(e.message))}>
          {seguir ? "Seguir" : "Evaluar"}
        </button>
        {error && <span className="err">{error}</span>}
      </div>
    </li>
  );
}

/** «Los N sin asignar → [persona] [Asignar]» de una escuela. */
function Masivo({ ids, equipo, asignar, guardando }) {
  const [quien, setQuien] = useState("");
  return (
    <div className="reparto-masivo">
      <span>{ids.length === 1 ? "El que queda sin asignar" : `Los ${ids.length} sin asignar`}:</span>
      <select value={quien} onChange={(e) => setQuien(e.target.value)} aria-label="A quién se asignan">
        <option value="">Elige a quién…</option>
        {equipo.map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
      </select>
      <button type="button" className="btn sm" disabled={!quien || guardando}
        onClick={() => asignar(ids, quien).then(() => setQuien(""))}>
        Asignar
      </button>
    </div>
  );
}

export default function RepartoFisico() {
  const [datos, setDatos] = useState(null);
  const [filtro, setFiltro] = useState(null);
  const [busca, setBusca] = useState("");
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);

  useEffect(() => { getRepartoFisico().then(setDatos).catch((e) => setError(e.message)); }, []);

  async function asignar(ids, evaluador) {
    setError(""); setGuardando(true);
    try { setDatos(await asignarFisico(ids, evaluador ? Number(evaluador) : null)); }
    catch (e) { setError(e.message); }
    finally { setGuardando(false); }
  }

  if (!datos) return error ? <p className="err">{error}</p> : <p className="msg">Cargando…</p>;

  const opciones = [["mios", "Asignados a mí"], ["todos", "Todos"], ["sin", "Sin asignar"]];
  const cuenta = Object.fromEntries(opciones.map(([k]) => [k, datos.jugadores.filter((j) => pasa(j, k, datos.yo)).length]));
  // Quien reparte entra en los que faltan; los demás, en los suyos.
  const actual = filtro || (datos.puede_asignar ? (cuenta.sin ? "sin" : "todos") : (cuenta.mios ? "mios" : "todos"));
  const q = busca.trim().toLowerCase();
  const visibles = datos.jugadores.filter((j) => pasa(j, actual, datos.yo) && (!q || j.nombre.toLowerCase().includes(q)));

  return (
    <>
      <p className="help">
        {datos.puede_asignar
          ? <>Elige quién hace la parte física de cada jugador: en <b>Alto rendimiento</b> y en <b>Competición de
            tardes</b> salen las personas de cada equipo. Al asignado le llega un aviso, los recordatorios del
            informe y lo tiene en «Asignados a mí». Los demás preparadores pueden evaluarle igual.</>
          : <>Quién hace la parte física de cada jugador. Lo reparte quien coordina la preparación física; en
            «Asignados a mí» tienes los tuyos.</>}
      </p>
      <div className="inf-filtros">
        <input className="eval-busca" type="search" placeholder="Buscar jugador"
          value={busca} onChange={(e) => setBusca(e.target.value)} />
        <div className="tabs-inv">
          {opciones.map(([k, t]) => (
            <button key={k} type="button" className={`chip${actual === k ? " on" : ""}`} onClick={() => setFiltro(k)}>
              {t} · {cuenta[k]}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="err">{error}</p>}
      {visibles.length === 0 && <p className="msg">Nadie con ese filtro.</p>}
      {ESCUELAS.map(([c, titulo]) => {
        const lista = visibles.filter((j) => j.circuito === c);
        if (lista.length === 0) return null;
        const sin = lista.filter((j) => !j.evaluador).map((j) => j.id);
        return (
          <section key={c} className="reparto-escuela">
            <h2 className="reparto-titulo">{titulo} <span className="eval-lista-meta">· {lista.length}</span></h2>
            {datos.puede_asignar && sin.length > 0 && (
              <Masivo key={`${c}-${sin.length}`} ids={sin} equipo={datos.evaluadores[c]} asignar={asignar} guardando={guardando} />
            )}
            <ul className="inf-lista">
              {lista.map((j) => <Fila key={j.id} j={j} datos={datos} asignar={asignar} guardando={guardando} />)}
            </ul>
          </section>
        );
      })}
    </>
  );
}
