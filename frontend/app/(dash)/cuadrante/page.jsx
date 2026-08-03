"use client";

import { useEffect, useState } from "react";
import Avatar from "../../../components/Avatar";
import {
  getCuadrante,
  getLatestSemana,
  getPanel,
  generarSemana,
  regenerarTarde,
  publicarSemana,
  swapAsignacion,
  manualAssign,
  setCoach,
  removeAsignacion,
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

function setDrag(e, payload) {
  e.dataTransfer.setData("application/json", JSON.stringify(payload));
  e.dataTransfer.effectAllowed = "move";
}
const overOn = (e) => { e.preventDefault(); e.currentTarget.classList.add("drop-ok"); };
const overOff = (e) => e.currentTarget.classList.remove("drop-ok");
function readDrag(e) {
  try { return JSON.parse(e.dataTransfer.getData("application/json")); } catch { return null; }
}

// Extrae el banquillo (jugadores sin pista) de la respuesta de /panel.
function benchPlayers(panel) {
  if (!panel) return [];
  const out = [];
  for (const g of [...(panel.por_entrenador || []), ...(panel.sin_entrenador || [])]) {
    for (const j of g.jugadores || []) {
      if (!j.tiene_asignacion) {
        out.push({ id: j.id, nombre: j.nombre, foto: j.foto_url, division: j.division_nivel, coach: g.entrenador?.nombre });
      }
    }
  }
  out.sort((a, b) => (a.nombre || "").localeCompare(b.nombre || ""));
  return out;
}

export default function CuadrantePage() {
  const [semanaId, setSemanaId] = useState(null);
  const [dia, setDia] = useState(0);
  const [data, setData] = useState(null);
  const [panel, setPanel] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);

  async function load(id, d) {
    setError(null);
    try {
      const sid = id ?? (await getLatestSemana())?.id;
      if (!sid) { setError("No hay semanas. Crea una en Semanas y pulsa Generar."); return; }
      setSemanaId(sid);
      const [cua, pan] = await Promise.all([getCuadrante(sid, d), getPanel(sid, d)]);
      setData(cua);
      setPanel(pan);
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
    try { await fn(); await load(semanaId, dia); }
    catch (e) { setError(String(e.message || e)); }
    finally { setBusy(null); }
  }

  // Operación de drag&drop: ejecuta y recarga; muestra el error de la API si lo hay.
  async function op(fn) {
    setError(null);
    try { await fn(); await load(semanaId, dia); }
    catch (e) {
      let msg = String(e.message || e);
      try { msg = JSON.parse(msg).error || msg; } catch {}
      setError(msg);
    }
  }

  function onDropCell(ctx) {
    return (e) => {
      e.preventDefault(); overOff(e);
      const s = readDrag(e);
      if (!s) return;
      if (s.k === "bj") op(() => manualAssign({ jugador_id: s.jugador, semana: ctx.semana, dia: ctx.dia, turno: ctx.turno, pista: ctx.pista }));
      else if (s.k === "be") op(() => setCoach({ semana: ctx.semana, dia: ctx.dia, turno: ctx.turno, pista: ctx.pista, entrenador_id: s.entrenador }));
    };
  }
  function onDropPlayer(targetAsig, ctx) {
    return (e) => {
      e.preventDefault(); e.stopPropagation(); overOff(e);
      const s = readDrag(e);
      if (!s) return;
      if (s.k === "cj" && s.asignacion !== targetAsig) op(() => swapAsignacion(s.asignacion, targetAsig, "jugador"));
      else if (s.k === "bj") op(() => manualAssign({ jugador_id: s.jugador, semana: ctx.semana, dia: ctx.dia, turno: ctx.turno, pista: ctx.pista }));
      else if (s.k === "be") op(() => setCoach({ semana: ctx.semana, dia: ctx.dia, turno: ctx.turno, pista: ctx.pista, entrenador_id: s.entrenador }));
    };
  }
  function onDropCoach(targetAsig, ctx) {
    return (e) => {
      e.preventDefault(); e.stopPropagation(); overOff(e);
      const s = readDrag(e);
      if (!s) return;
      if (s.k === "cc" && s.asignacion !== targetAsig) op(() => swapAsignacion(s.asignacion, targetAsig, "entrenador"));
      else if (s.k === "be") op(() => setCoach({ semana: ctx.semana, dia: ctx.dia, turno: ctx.turno, pista: ctx.pista, entrenador_id: s.entrenador }));
    };
  }
  function onDropBench(e) {
    e.preventDefault(); overOff(e);
    const s = readDrag(e);
    if (s && s.k === "cj") op(() => removeAsignacion(s.asignacion));
  }

  if (error && !data) return <div><p className="err">{error}</p></div>;
  if (!data) return <p className="msg">Cargando cuadrante…</p>;

  const cellMap = {};
  for (const a of data.asignaciones) (cellMap[`${a.pista}_${a.turno}`] ||= []).push(a);
  const publicado = data.semana.estado === "PUBLICADO";
  const bench = benchPlayers(panel);
  const benchCoaches = panel?.entrenadores_libres || [];

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

      {error && <p className="err">{error}</p>}
      <p className="dnd-hint">Arrastra jugadores/entrenadores entre pistas para intercambiarlos, desde el banquillo a una pista para colocarlos, o de una pista al banquillo para quitarlos.</p>

      <div className="dnd-layout">
        <div className="dnd-main">
          <table className="grid">
            <thead>
              <tr><th></th>{data.turnos.map((t) => <th key={t.id}>{t.codigo}</th>)}</tr>
            </thead>
            <tbody>
              {data.sedes.map((sede) => (
                <tr key={`h-${sede.id}`} className="sede-row"><td colSpan={data.turnos.length + 1}>{sede.nombre}{sede.es_satelite ? " · satélite" : ""}</td></tr>
              )).flatMap((header, si) => {
                const sede = data.sedes[si];
                return [header, ...sede.pistas.map((p) => (
                  <tr key={p.id}>
                    <td className="pista-label">P{p.numero}</td>
                    {data.turnos.map((t) => (
                      <Cell
                        key={t.id}
                        items={cellMap[`${p.id}_${t.id}`]}
                        ctx={{ semana: semanaId, dia, turno: t.id, pista: p.id }}
                        onDropCell={onDropCell}
                        onDropPlayer={onDropPlayer}
                        onDropCoach={onDropCoach}
                      />
                    ))}
                  </tr>
                ))];
              })}
            </tbody>
          </table>
        </div>

        <aside className="bench-side" onDragOver={overOn} onDragLeave={overOff} onDrop={onDropBench}>
          <div className="bench-title">Banquillo · sin pista <span className="bench-count">{bench.length}</span></div>
          <div className="bench-side-hint">Arrastra a una pista para colocar · suelta aquí para quitar</div>
          <div className="bench-scroll">
            <div className="bench-col-items">
              {bench.length === 0 ? <span className="bench-empty">Todos los disponibles tienen pista.</span> :
                bench.map((p) => (
                  <div key={p.id} className="bench-chip dnd" draggable
                    onDragStart={(e) => setDrag(e, { k: "bj", jugador: p.id })}
                    title={`${p.nombre}${p.coach ? " · " + p.coach : ""}`}>
                    <Avatar nombre={p.nombre} fotoUrl={p.foto} kind="player" />
                    <span>{p.nombre}{p.division ? ` · D${p.division}` : ""}</span>
                  </div>
                ))}
            </div>
            {benchCoaches.length > 0 && (
              <>
                <div className="bench-title sm">Entrenadores libres</div>
                <div className="bench-col-items">
                  {benchCoaches.map((e2) => (
                    <div key={e2.id} className="bench-chip dnd" draggable
                      onDragStart={(e) => setDrag(e, { k: "be", entrenador: e2.id })} title={e2.nombre}>
                      <Avatar nombre={e2.nombre} fotoUrl={e2.foto_url} kind="coach" />
                      <span>{e2.nombre}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

function Cell({ items, ctx, onDropCell, onDropPlayer, onDropCoach }) {
  const empty = !items || items.length === 0;
  const color = empty ? "var(--border-strong)" : (ESTADO_COLOR[items[0].estado] || "var(--border-strong)");
  return (
    <td className={`cell ${empty ? "empty" : ""}`} style={{ borderLeftColor: color }}
      onDragOver={overOn} onDragLeave={overOff} onDrop={onDropCell(ctx)}>
      {(items || []).map((a) => (
        <div className="player dnd" key={a.id} draggable
          onDragStart={(e) => setDrag(e, { k: "cj", asignacion: a.id })}
          onDragOver={overOn} onDragLeave={overOff} onDrop={onDropPlayer(a.id, ctx)}
          title="Arrastra para intercambiar / al banquillo">
          <Avatar nombre={a.jugador_nombre} fotoUrl={a.jugador_foto} kind="player" />
          <i className="dot" style={{ background: ESTADO_COLOR[a.estado] }} />
          <span>{a.jugador_nombre}</span>
          {a.division_nivel ? <span className="div">D{a.division_nivel}</span> : null}
        </div>
      ))}
      {!empty && items[0].entrenador_nombre ? (
        <div className="coach dnd" draggable
          onDragStart={(e) => setDrag(e, { k: "cc", asignacion: items[0].id })}
          onDragOver={overOn} onDragLeave={overOff} onDrop={onDropCoach(items[0].id, ctx)}
          title="Arrastra para intercambiar entrenador">
          <Avatar nombre={items[0].entrenador_nombre} fotoUrl={items[0].entrenador_foto} kind="coach" />
          {items[0].entrenador_nombre}
        </div>
      ) : null}
      {empty ? <span className="cell-empty-hint">—</span> : null}
    </td>
  );
}
