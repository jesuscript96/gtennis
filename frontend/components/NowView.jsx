"use client";

import { useCallback, useEffect, useState } from "react";
import { getAhora, getCuadrante } from "../lib/api";
import CourtCard from "./CourtCard";

export default function NowView() {
  const [meta, setMeta] = useState(null);
  const [day, setDay] = useState(null);
  const [mode, setMode] = useState("cancha");
  const [override, setOverride] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const m = await getAhora();
      setMeta(m);
      if (m.semana) setDay(await getCuadrante(m.semana.id, m.dia));
      else setDay(null);
    } catch (e) {
      setError(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  if (error) return <p className="err">{error}</p>;
  if (!meta) return <p className="msg">Cargando…</p>;

  const shown = override || meta.turno_mostrado || meta.turnos[0]?.codigo;
  const asig = (day?.asignaciones || []).filter((a) => a.turno_codigo === shown);
  const byPista = {};
  for (const a of asig) (byPista[a.pista] ||= []).push(a);

  const statusEl =
    meta.status === "en_curso" ? (
      <span className="now-turno"><span className="live-dot" />En curso · {meta.dia_nombre} · turno <b>{meta.turno_actual.codigo}</b></span>
    ) : meta.status === "proximo" ? (
      <span className="now-turno">{meta.dia_nombre} · próximo turno <b>{meta.proximo.codigo}</b> en {meta.proximo.en_minutos} min</span>
    ) : (
      <span className="now-turno">Academia cerrada</span>
    );

  return (
    <div>
      <div className="now-head">
        <div className="now-status">
          <span className="now-clock">{meta.ahora}</span>
          {statusEl}
        </div>
        <div className="now-tabs">
          <button className={mode === "cancha" ? "active" : ""} onClick={() => setMode("cancha")}>Vista cancha</button>
          <button className={mode === "foto" ? "active" : ""} onClick={() => setMode("foto")}>Vista foto</button>
        </div>
      </div>

      <div className="turno-chips" style={{ marginBottom: 8 }}>
        {meta.turnos.map((t) => (
          <button
            key={t.id}
            className={t.codigo === shown ? "active" : ""}
            onClick={() => setOverride(t.codigo === meta.turno_mostrado ? null : t.codigo)}
          >
            {t.codigo}
          </button>
        ))}
      </div>

      {!meta.semana ? (
        <p className="msg">No hay cuadrante para esta semana. Genera una en Semanas.</p>
      ) : (
        meta.sedes.map((sede) => (
          <div key={sede.id}>
            <div className="sede-title">{sede.nombre}{sede.es_satelite ? " · satélite" : ""}</div>
            <div className="court-grid">
              {sede.pistas.map((p) => {
                const items = byPista[p.id] || [];
                const players = items.map((a) => ({
                  id: a.jugador, nombre: a.jugador_nombre, foto: a.jugador_foto,
                  division: a.division_nivel, estado: a.estado,
                }));
                const c = items.find((a) => a.entrenador_nombre);
                const coach = c ? { nombre: c.entrenador_nombre, foto: c.entrenador_foto } : null;
                return (
                  <CourtCard
                    key={p.id}
                    pista={{ label: `Pista ${p.numero}` }}
                    players={players}
                    coach={coach}
                    mode={mode}
                  />
                );
              })}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
