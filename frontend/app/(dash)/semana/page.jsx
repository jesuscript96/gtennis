"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getLatestSemana, getTabla, getPanel, swapAsignacion,
  manualAssign, setCoach, removeAsignacion,
} from "../../../lib/api";
import Avatar from "../../../components/Avatar";

function setDrag(e, payload) {
  e.dataTransfer.setData("application/json", JSON.stringify(payload));
  e.dataTransfer.effectAllowed = "move";
}
const overOn = (e) => { e.preventDefault(); e.currentTarget.classList.add("drop-ok"); };
const overOff = (e) => e.currentTarget.classList.remove("drop-ok");
const readDrag = (e) => { try { return JSON.parse(e.dataTransfer.getData("application/json")); } catch { return null; } };

const ESTADO_COLOR = {
  DISPONIBLE: "var(--st-disponible)",
  AUSENCIA_JUGADOR: "var(--st-ausencia)",
  CALENTAMIENTO: "var(--st-calentamiento)",
  EN_TORNEO: "var(--st-torneo)",
  CLIMATOLOGIA: "var(--st-clima)",
  AUSENCIA_COACH: "var(--st-coach)",
};
const ESTADO_LABEL = {
  AUSENCIA_JUGADOR: "Ausencia",
  CALENTAMIENTO: "Calentamiento",
  EN_TORNEO: "En torneo",
  CLIMATOLOGIA: "Climatología",
  AUSENCIA_COACH: "Ausencia coach",
};
const noDisponible = (estado) => estado && estado !== "DISPONIBLE";
const first = (n) => (n || "").split(" ")[0];

function buildSessions(asignaciones) {
  const byDia = {};
  for (const a of asignaciones) {
    const dia = (byDia[a.dia] ||= {});
    const s = (dia[`${a.turno_codigo}-${a.pista}`] ||= {
      key: `${a.dia}-${a.turno_codigo}-${a.pista}`,
      dia: a.dia, turno_id: a.turno, pista: a.pista,
      pista_numero: a.pista_numero, sede: a.sede, turno: a.turno_codigo,
      players: [], coach: null,
    });
    s.players.push({
      id: a.jugador, asignacion: a.id, nombre: a.jugador_nombre,
      foto: a.jugador_foto, division: a.division_nivel, estado: a.estado,
    });
    if (a.entrenador && !s.coach) {
      s.coach = { id: a.entrenador, asignacion: a.id, nombre: a.entrenador_nombre, foto: a.entrenador_foto };
    }
  }
  return byDia;
}

function benchPlayers(panel) {
  if (!panel) return [];
  const out = [];
  for (const g of [...(panel.por_entrenador || []), ...(panel.sin_entrenador || [])]) {
    for (const j of g.jugadores || []) {
      if (!j.tiene_asignacion) out.push({ id: j.id, nombre: j.nombre, foto: j.foto_url, division: j.division_nivel, estado: j.estado });
    }
  }
  out.sort((a, b) => (a.nombre || "").localeCompare(b.nombre || ""));
  return out;
}

export default function SemanaPage() {
  const [data, setData] = useState(null);
  const [semanaId, setSemanaId] = useState(null);
  const [panel, setPanel] = useState(null);
  const [benchDay, setBenchDay] = useState(0);
  const [error, setError] = useState(null);

  const [sede, setSede] = useState("");
  const [coach, setCoach2] = useState("");
  const [q, setQ] = useState("");
  const [turnosOff, setTurnosOff] = useState(() => new Set());

  async function reload(id, bday) {
    const sid = id ?? semanaId;
    if (!sid) return;
    const [tabla, pan] = await Promise.all([getTabla(sid), getPanel(sid, bday ?? benchDay)]);
    setData(tabla);
    setPanel(pan);
  }

  useEffect(() => {
    (async () => {
      try {
        const s = await getLatestSemana();
        if (!s) return setError("No hay semanas. Crea y genera una en Semanas.");
        setSemanaId(s.id);
        await reload(s.id, 0);
      } catch (e) { setError(String(e.message || e)); }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (semanaId) getPanel(semanaId, benchDay).then(setPanel).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [benchDay]);

  async function op(fn) {
    setError(null);
    try { await fn(); await reload(); }
    catch (e) {
      let msg = String(e.message || e);
      try { msg = JSON.parse(msg).error || msg; } catch {}
      setError(msg);
    }
  }
  const onSwap = (a, b, kind) => op(() => swapAsignacion(a, b, kind));

  const sessions = useMemo(() => (data ? buildSessions(data.asignaciones) : {}), [data]);
  const coaches = useMemo(() => {
    if (!data) return [];
    const seen = new Map();
    for (const a of data.asignaciones) if (a.entrenador && !seen.has(a.entrenador)) seen.set(a.entrenador, a.entrenador_nombre);
    return [...seen].map(([id, nombre]) => ({ id, nombre })).sort((x, y) => (x.nombre || "").localeCompare(y.nombre || ""));
  }, [data]);

  if (error && !data) return <p className="err">{error}</p>;
  if (!data) return <p className="msg">Cargando semana…</p>;

  const ql = q.trim().toLowerCase();
  function pass(s) {
    if (sede && s.sede !== sede) return false;
    if (coach && String(s.coach?.id) !== String(coach)) return false;
    if (turnosOff.has(s.turno)) return false;
    if (ql) {
      const hit = s.players.some((p) => (p.nombre || "").toLowerCase().includes(ql)) || (s.coach?.nombre || "").toLowerCase().includes(ql);
      if (!hit) return false;
    }
    return true;
  }
  const toggleTurno = (code) => setTurnosOff((prev) => { const n = new Set(prev); n.has(code) ? n.delete(code) : n.add(code); return n; });
  const filtered = (s) => Object.values(s).filter(pass);

  // Drop handlers (mismo formato que el Cuadrante).
  const dropSession = (s) => (e) => {
    e.preventDefault(); overOff(e);
    const d = readDrag(e); if (!d) return;
    if (d.k === "bj") op(() => manualAssign({ jugador_id: d.jugador, semana: semanaId, dia: s.dia, turno: s.turno_id, pista: s.pista }));
    else if (d.k === "be") op(() => setCoach({ semana: semanaId, dia: s.dia, turno: s.turno_id, pista: s.pista, entrenador_id: d.entrenador }));
  };
  const dropPlayer = (targetAsig, s) => (e) => {
    e.preventDefault(); e.stopPropagation(); overOff(e);
    const d = readDrag(e); if (!d) return;
    if (d.k === "cj" && d.asignacion !== targetAsig) op(() => swapAsignacion(d.asignacion, targetAsig, "jugador"));
    else if (d.k === "bj") op(() => manualAssign({ jugador_id: d.jugador, semana: semanaId, dia: s.dia, turno: s.turno_id, pista: s.pista }));
    else if (d.k === "be") op(() => setCoach({ semana: semanaId, dia: s.dia, turno: s.turno_id, pista: s.pista, entrenador_id: d.entrenador }));
  };
  const dropCoach = (targetAsig, s) => (e) => {
    e.preventDefault(); e.stopPropagation(); overOff(e);
    const d = readDrag(e); if (!d) return;
    if (d.k === "cc" && d.asignacion !== targetAsig) op(() => swapAsignacion(d.asignacion, targetAsig, "entrenador"));
    else if (d.k === "be") op(() => setCoach({ semana: semanaId, dia: s.dia, turno: s.turno_id, pista: s.pista, entrenador_id: d.entrenador }));
  };
  const dropBench = (e) => { e.preventDefault(); overOff(e); const d = readDrag(e); if (d && d.k === "cj") op(() => removeAsignacion(d.asignacion)); };

  const bench = benchPlayers(panel);
  const benchCoaches = panel?.entrenadores_libres || [];

  return (
    <div>
      <div className="page-head">
        <h1>Semana · {data.semana.fecha_inicio}</h1>
        <span className={`badge ${data.semana.estado === "PUBLICADO" ? "pub" : ""}`}>
          {data.semana.estado === "PUBLICADO" ? "Publicado" : "Borrador"}
        </span>
      </div>

      <div className="help">
        Cada columna es un <b>día</b>, dentro van los <b>turnos</b> y cada tarjeta es una <b>pista</b>.
        Arrastra desde el <b>banquillo</b> (abajo) a una pista para colocar, de una pista al banquillo para quitar, o entre pistas para intercambiar.
      </div>

      <div className="week-filters">
        <select value={sede} onChange={(e) => setSede(e.target.value)} style={{ maxWidth: 190 }}>
          <option value="">Todas las sedes</option>
          {data.sedes.map((s) => <option key={s.id} value={s.nombre}>{s.nombre}</option>)}
        </select>
        <select value={coach} onChange={(e) => setCoach2(e.target.value)} style={{ maxWidth: 210 }}>
          <option value="">Todos los entrenadores</option>
          {coaches.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
        </select>
        <div className="turno-chips">
          {data.turnos.map((t) => (
            <button key={t.codigo} className={turnosOff.has(t.codigo) ? "" : "active"} onClick={() => toggleTurno(t.codigo)} title={`Mostrar/ocultar ${t.codigo}`}>{t.codigo}</button>
          ))}
        </div>
        <input className="search" placeholder="Buscar jugador…" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 220 }} />
        {(sede || coach || ql || turnosOff.size > 0) && (
          <button className="btn ghost sm" onClick={() => { setSede(""); setCoach2(""); setQ(""); setTurnosOff(new Set()); }}>Limpiar</button>
        )}
      </div>

      <div className="dnd-layout">
        <div className="dnd-main">
          {error && <p className="err" style={{ marginBottom: 12 }}>{error}</p>}
          <div className="week-board">
            {data.dias.map((d) => {
              const list = filtered(sessions[d.idx] || {});
              const byTurno = {};
              for (const s of list) (byTurno[s.turno] ||= []).push(s);
              const count = list.reduce((n, s) => n + s.players.length, 0);
              return (
                <div className="week-col" key={d.idx}>
                  <div className="week-col-head">
                    <span className="wk-day">{d.nombre}</span>
                    <span className="wk-count">{count}</span>
                  </div>
                  {list.length === 0 ? <div className="wk-empty">—</div> : (
                    data.turnos.filter((t) => byTurno[t.codigo]).map((t) => (
                      <div className="week-turno" key={t.codigo}>
                        <div className="wk-turno-label">{t.codigo}</div>
                        {byTurno[t.codigo].sort((a, b) => a.sede.localeCompare(b.sede) || a.pista_numero - b.pista_numero).map((s) => (
                          <Session key={s.key} s={s} dropSession={dropSession} dropPlayer={dropPlayer} dropCoach={dropCoach} />
                        ))}
                      </div>
                    ))
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <aside className="bench-side" onDragOver={overOn} onDragLeave={overOff} onDrop={dropBench}>
          <div className="bench-title">Banquillo · sin pista <span className="bench-count">{bench.length}</span></div>
          <div className="bench-side-hint">Elige el día y arrastra a una pista · suelta aquí para quitar</div>
          <div className="bench-days">
            {data.dias.map((d) => (
              <button key={d.idx} className={`bench-day ${d.idx === benchDay ? "active" : ""}`} onClick={() => setBenchDay(d.idx)}>{d.nombre.slice(0, 3)}</button>
            ))}
          </div>
          <div className="bench-scroll">
            <div className="bench-col-items">
              {bench.length === 0 ? <span className="bench-empty">Todos tienen pista este día.</span> :
                bench.map((p) => (
                  <div key={p.id} className={`bench-chip dnd${noDisponible(p.estado) ? " nd" : ""}`} draggable
                    onDragStart={(e) => setDrag(e, { k: "bj", jugador: p.id })}
                    title={noDisponible(p.estado) ? `${p.nombre} · ${ESTADO_LABEL[p.estado] || p.estado} (arrastra para forzar pista)` : p.nombre}>
                    {noDisponible(p.estado) && (
                      <span className="bench-state-dot" style={{ background: ESTADO_COLOR[p.estado] || "var(--border-strong)" }} />
                    )}
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
                    <div key={e2.id} className="bench-chip dnd" draggable onDragStart={(e) => setDrag(e, { k: "be", entrenador: e2.id })} title={e2.nombre}>
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

function Session({ s, dropSession, dropPlayer, dropCoach }) {
  const color = ESTADO_COLOR[s.players[0]?.estado] || "var(--border-strong)";
  return (
    <div className="wk-session" style={{ borderLeft: `3px solid ${color}` }}
      onDragOver={overOn} onDragLeave={overOff} onDrop={dropSession(s)}>
      <div className="wk-head">
        <span className="wk-pista">P{s.pista_numero}</span>
        <span className="wk-sede">{s.sede}</span>
      </div>
      <div className="wk-players">
        {s.players.map((p) => (
          <div className="wk-av dnd" key={p.id} title={`${p.nombre} · arrastra`}
            draggable onDragStart={(e) => setDrag(e, { k: "cj", asignacion: p.asignacion })}
            onDragOver={overOn} onDragLeave={overOff} onDrop={dropPlayer(p.asignacion, s)}>
            <Avatar nombre={p.nombre} fotoUrl={p.foto} kind="player" />
            <span className="nm">{first(p.nombre)}</span>
          </div>
        ))}
        {s.coach && (
          <div className="wk-av coach dnd" key={`c-${s.coach.id}`} title={`Coach: ${s.coach.nombre} · arrastra`}
            draggable onDragStart={(e) => setDrag(e, { k: "cc", asignacion: s.coach.asignacion })}
            onDragOver={overOn} onDragLeave={overOff} onDrop={dropCoach(s.coach.asignacion, s)}>
            <Avatar nombre={s.coach.nombre} fotoUrl={s.coach.foto} kind="coach" />
            <span className="nm">{first(s.coach.nombre)}</span>
          </div>
        )}
      </div>
    </div>
  );
}
