"use client";

import { useEffect, useState } from "react";
import Avatar from "../../../components/Avatar";
import {
  getCuadrante,
  getLatestSemana,
  generarSemana,
  regenerarTarde,
  publicarSemana,
  swapAsignacion,
} from "../../../lib/api";

const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];
const ESTADO_COLOR = {
  DISPONIBLE: "var(--st-disponible)",
  AUSENCIA_JUGADOR: "var(--st-ausencia)",
  CALENTAMIENTO: "var(--st-calentamiento)",
  EN_TORNEO: "var(--st-torneo)",
  CLIMATOLOGIA: "var(--st-clima)",
  AUSENCIA_COACH: "var(--st-coach)",
};
const LEYENDA = [
  ["Disponible", "var(--st-disponible)"],
  ["Ausencia jugador", "var(--st-ausencia)"],
  ["Calentamiento", "var(--st-calentamiento)"],
  ["En torneo", "var(--st-torneo)"],
  ["Climatología", "var(--st-clima)"],
  ["Ausencia coach", "var(--st-coach)"],
];

function onDragStart(e, id, kind) {
  e.dataTransfer.setData("application/json", JSON.stringify({ id, kind }));
  e.dataTransfer.effectAllowed = "move";
}
function onDragOver(e) {
  e.preventDefault();
  e.currentTarget.classList.add("drop-ok");
}
function onDragLeave(e) {
  e.currentTarget.classList.remove("drop-ok");
}
function makeDrop(targetId, kind, onSwap) {
  return (e) => {
    e.preventDefault();
    e.currentTarget.classList.remove("drop-ok");
    let src;
    try { src = JSON.parse(e.dataTransfer.getData("application/json")); } catch { return; }
    if (!src || src.kind !== kind || src.id === targetId) return;
    onSwap(src.id, targetId, kind);
  };
}

export default function CuadrantePage() {
  const [semanaId, setSemanaId] = useState(null);
  const [dia, setDia] = useState(0);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);

  async function load(id, d) {
    setError(null);
    try {
      const sid = id ?? (await getLatestSemana())?.id;
      if (!sid) {
        setError("No hay semanas. Crea una en Semanas y pulsa Generar.");
        return;
      }
      setSemanaId(sid);
      setData(await getCuadrante(sid, d));
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  useEffect(() => {
    load(null, dia);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dia]);

  async function run(label, fn) {
    setBusy(label);
    try {
      await fn();
      await load(semanaId, dia);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(null);
    }
  }

  async function onSwap(aId, bId, kind) {
    try {
      await swapAsignacion(aId, bId, kind);
      await load(semanaId, dia);
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  if (error) return <div><p className="err">{error}</p></div>;
  if (!data) return <p className="msg">Cargando cuadrante…</p>;

  const cellMap = {};
  for (const a of data.asignaciones) (cellMap[`${a.pista}_${a.turno}`] ||= []).push(a);
  const publicado = data.semana.estado === "PUBLICADO";

  return (
    <div>
      <div className="page-head">
        <h1>Cuadrante · {data.semana.fecha_inicio}</h1>
        <span className={`badge ${publicado ? "pub" : ""}`}>
          {publicado ? "Publicado" : "Borrador · pendiente de publicar"}
        </span>
      </div>

      <div className="controls">
        {DIAS.map((d, i) => (
          <button key={i} className={i === dia ? "active" : ""} onClick={() => setDia(i)}>{d}</button>
        ))}
        <span style={{ flex: 1 }} />
        <button className="btn ghost sm" disabled={busy} onClick={() => run("gen", () => generarSemana(semanaId))}>
          {busy === "gen" ? "Generando…" : "Generar semana"}
        </button>
        <button className="btn ghost sm" disabled={busy} onClick={() => run("tarde", () => regenerarTarde(semanaId, dia))}>
          {busy === "tarde" ? "Regenerando…" : "Regenerar tarde"}
        </button>
        <button className="btn sm" disabled={busy || publicado} onClick={() => run("pub", () => publicarSemana(semanaId))}>
          {publicado ? "Publicado" : "Publicar"}
        </button>
      </div>

      <p className="dnd-hint">Arrastra un jugador sobre otro para intercambiarlos. Lo mismo con los entrenadores.</p>

      <table className="grid">
        <thead>
          <tr>
            <th></th>
            {data.turnos.map((t) => <th key={t.id}>{t.codigo}</th>)}
          </tr>
        </thead>
        <tbody>
          {data.sedes.map((sede) => (
            <SedeBlock key={sede.id} sede={sede} turnos={data.turnos} cellMap={cellMap} onSwap={onSwap} />
          ))}
        </tbody>
      </table>

      <div className="legend">
        {LEYENDA.map(([label, color]) => (
          <span key={label}><i className="dot" style={{ background: color }} />{label}</span>
        ))}
      </div>
    </div>
  );
}

function SedeBlock({ sede, turnos, cellMap, onSwap }) {
  return (
    <>
      <tr className="sede-row">
        <td colSpan={turnos.length + 1}>{sede.nombre}{sede.es_satelite ? " · satélite" : ""}</td>
      </tr>
      {sede.pistas.map((p) => (
        <tr key={p.id}>
          <td className="pista-label">P{p.numero}</td>
          {turnos.map((t) => <Cell key={t.id} items={cellMap[`${p.id}_${t.id}`]} onSwap={onSwap} />)}
        </tr>
      ))}
    </>
  );
}

function Cell({ items, onSwap }) {
  if (!items || items.length === 0) return <td className="cell empty" />;
  const color = ESTADO_COLOR[items[0].estado] || "var(--glass-border)";
  return (
    <td className="cell" style={{ borderLeftColor: color }}>
      {items.map((a) => (
        <div
          className="player dnd"
          key={a.id}
          draggable
          onDragStart={(e) => onDragStart(e, a.id, "jugador")}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={makeDrop(a.id, "jugador", onSwap)}
          title="Arrastra para intercambiar"
        >
          <Avatar nombre={a.jugador_nombre} fotoUrl={a.jugador_foto} kind="player" />
          <i className="dot" style={{ background: ESTADO_COLOR[a.estado] }} />
          <span>{a.jugador_nombre}</span>
          {a.division_nivel ? <span className="div">D{a.division_nivel}</span> : null}
        </div>
      ))}
      {items[0].entrenador_nombre ? (
        <div
          className="coach dnd"
          draggable
          onDragStart={(e) => onDragStart(e, items[0].id, "entrenador")}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={makeDrop(items[0].id, "entrenador", onSwap)}
          title="Arrastra para intercambiar entrenador"
        >
          <Avatar nombre={items[0].entrenador_nombre} fotoUrl={items[0].entrenador_foto} kind="coach" />
          {items[0].entrenador_nombre}
        </div>
      ) : null}
    </td>
  );
}
