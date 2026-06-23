"use client";

import { useEffect, useMemo, useState } from "react";
import { getLatestSemana, getTabla } from "../../../lib/api";
import Avatar from "../../../components/Avatar";

const ESTADO_COLOR = {
  DISPONIBLE: "var(--st-disponible)",
  AUSENCIA_JUGADOR: "var(--st-ausencia)",
  CALENTAMIENTO: "var(--st-calentamiento)",
  EN_TORNEO: "var(--st-torneo)",
  CLIMATOLOGIA: "var(--st-clima)",
  AUSENCIA_COACH: "var(--st-coach)",
};

const first = (n) => (n || "").split(" ")[0];

// Agrupa las asignaciones en "sesiones": una pista, un día, un turno → varios jugadores + coach.
// Devuelve { dia: { "turno-pista": session } } (plano por día; el render reagrupa por turno).
function buildSessions(asignaciones) {
  const byDia = {};
  for (const a of asignaciones) {
    const dia = (byDia[a.dia] ||= {});
    const s = (dia[`${a.turno_codigo}-${a.pista}`] ||= {
      key: `${a.dia}-${a.turno_codigo}-${a.pista}`,
      pista: a.pista,
      pista_numero: a.pista_numero,
      sede: a.sede,
      turno: a.turno_codigo,
      players: [],
      coach: null,
    });
    s.players.push({
      id: a.jugador,
      nombre: a.jugador_nombre,
      foto: a.jugador_foto,
      division: a.division_nivel,
      estado: a.estado,
    });
    if (a.entrenador && !s.coach) {
      s.coach = { id: a.entrenador, nombre: a.entrenador_nombre, foto: a.entrenador_foto };
    }
  }
  return byDia;
}

export default function SemanaPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const [sede, setSede] = useState("");
  const [coach, setCoach] = useState("");
  const [q, setQ] = useState("");
  const [turnosOff, setTurnosOff] = useState(() => new Set());

  useEffect(() => {
    (async () => {
      try {
        const s = await getLatestSemana();
        if (!s) return setError("No hay semanas. Crea y genera una en Semanas.");
        setData(await getTabla(s.id));
      } catch (e) {
        setError(String(e.message || e));
      }
    })();
  }, []);

  const sessions = useMemo(() => (data ? buildSessions(data.asignaciones) : {}), [data]);

  const coaches = useMemo(() => {
    if (!data) return [];
    const seen = new Map();
    for (const a of data.asignaciones) {
      if (a.entrenador && !seen.has(a.entrenador)) seen.set(a.entrenador, a.entrenador_nombre);
    }
    return [...seen].map(([id, nombre]) => ({ id, nombre })).sort((x, y) => (x.nombre || "").localeCompare(y.nombre || ""));
  }, [data]);

  if (error) return <p className="err">{error}</p>;
  if (!data) return <p className="msg">Cargando semana…</p>;

  const ql = q.trim().toLowerCase();
  function pass(s) {
    if (sede && s.sede !== sede) return false;
    if (coach && String(s.coach?.id) !== String(coach)) return false;
    if (turnosOff.has(s.turno)) return false;
    if (ql) {
      const hit =
        s.players.some((p) => (p.nombre || "").toLowerCase().includes(ql)) ||
        (s.coach?.nombre || "").toLowerCase().includes(ql);
      if (!hit) return false;
    }
    return true;
  }

  function toggleTurno(code) {
    setTurnosOff((prev) => {
      const next = new Set(prev);
      next.has(code) ? next.delete(code) : next.add(code);
      return next;
    });
  }

  const filtered = (s) => Object.values(s).filter(pass);
  const totalShown = data.dias.reduce(
    (acc, d) => acc + filtered(sessions[d.idx] || {}).reduce((n, s) => n + s.players.length, 0),
    0
  );

  return (
    <div>
      <div className="page-head">
        <h1>Semana · {data.semana.fecha_inicio}</h1>
        <span className={`badge ${data.semana.estado === "PUBLICADO" ? "pub" : ""}`}>
          {data.semana.estado === "PUBLICADO" ? "Publicado" : "Borrador"}
        </span>
      </div>

      <div className="help">
        Toda la semana de un vistazo: cada columna es un <b>día</b>, dentro van los <b>turnos</b> y cada
        tarjeta es una <b>pista</b> con sus jugadores. Filtra por sede, entrenador o turno, o busca un jugador.
      </div>

      <div className="week-filters">
        <select value={sede} onChange={(e) => setSede(e.target.value)} style={{ maxWidth: 190 }}>
          <option value="">Todas las sedes</option>
          {data.sedes.map((s) => (
            <option key={s.id} value={s.nombre}>{s.nombre}</option>
          ))}
        </select>
        <select value={coach} onChange={(e) => setCoach(e.target.value)} style={{ maxWidth: 210 }}>
          <option value="">Todos los entrenadores</option>
          {coaches.map((c) => (
            <option key={c.id} value={c.id}>{c.nombre}</option>
          ))}
        </select>
        <div className="turno-chips">
          {data.turnos.map((t) => (
            <button
              key={t.codigo}
              className={turnosOff.has(t.codigo) ? "" : "active"}
              onClick={() => toggleTurno(t.codigo)}
              title={`Mostrar/ocultar ${t.codigo}`}
            >
              {t.codigo}
            </button>
          ))}
        </div>
        <input
          className="search"
          placeholder="Buscar jugador…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ maxWidth: 220 }}
        />
        {(sede || coach || ql || turnosOff.size > 0) && (
          <button className="btn ghost sm" onClick={() => { setSede(""); setCoach(""); setQ(""); setTurnosOff(new Set()); }}>
            Limpiar
          </button>
        )}
      </div>

      {totalShown === 0 ? (
        <p className="msg">Nada que mostrar con estos filtros.</p>
      ) : (
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
                {list.length === 0 ? (
                  <div className="wk-empty">—</div>
                ) : (
                  data.turnos
                    .filter((t) => byTurno[t.codigo])
                    .map((t) => (
                      <div className="week-turno" key={t.codigo}>
                        <div className="wk-turno-label">{t.codigo}</div>
                        {byTurno[t.codigo]
                          .sort((a, b) => a.sede.localeCompare(b.sede) || a.pista_numero - b.pista_numero)
                          .map((s) => (
                            <Session key={s.key} s={s} />
                          ))}
                      </div>
                    ))
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Session({ s }) {
  const color = ESTADO_COLOR[s.players[0]?.estado] || "var(--border-strong)";
  return (
    <div className="wk-session" style={{ borderLeft: `3px solid ${color}` }}>
      <div className="wk-head">
        <span className="wk-pista">P{s.pista_numero}</span>
        <span className="wk-sede">{s.sede}</span>
      </div>
      <div className="wk-players">
        {s.players.map((p) => (
          <div className="wk-av" key={p.id} title={p.nombre}>
            <Avatar nombre={p.nombre} fotoUrl={p.foto} kind="player" />
            <span className="nm">{first(p.nombre)}</span>
          </div>
        ))}
        {s.coach && (
          <div className="wk-av coach" key={`c-${s.coach.id}`} title={`Coach: ${s.coach.nombre}`}>
            <Avatar nombre={s.coach.nombre} fotoUrl={s.coach.foto} kind="coach" />
            <span className="nm">{first(s.coach.nombre)}</span>
          </div>
        )}
      </div>
    </div>
  );
}
