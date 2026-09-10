"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getMiAgenda, getMiDia, getMisSesiones, saveMiSemana,
  getMisAusencias, addMiAusencia, delMiAusencia,
  getEntrenadoresAgenda, getUser,
} from "../../../lib/api";

const DIAS_CORTOS = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];
const fechaLarga = (iso) => {
  const d = new Date(iso);
  return `${DIAS_CORTOS[d.getDay()]} ${d.getDate()}`;
};
const fechaCorta = (iso) => {
  const d = new Date(iso);
  return `${d.getDate()}/${d.getMonth() + 1}`;
};
const MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];
const iso = (d) => d.toISOString().slice(0, 10);

export default function MiAgenda() {
  const [semana, setSemana] = useState([]);
  const [hoy, setHoy] = useState(null);
  const [ausencias, setAusencias] = useState([]);
  const [nombre, setNombre] = useState("");
  const [aviso, setAviso] = useState("");
  const [error, setError] = useState("");
  const [anio, setAnio] = useState(new Date().getFullYear());
  const [nueva, setNueva] = useState({ fecha_inicio: "", fecha_fin: "", motivo: "" });
  // Dirección mira (y rellena) la agenda de cualquiera; el coach, la de los
  // entrenadores de su bloque. Sin elegir a nadie se abre la que toque por
  // defecto: la propia si la hay, y si no la del primero de la lista.
  const usuario = getUser();
  const eligeOtros = !!(usuario?.is_superadmin || usuario?.is_coach);
  const [equipo, setEquipo] = useState([]);
  const [quien, setQuien] = useState("");
  // Sus pistas: es lo primero que quiere ver al entrar. Empieza en hoy, pero
  // puede adelantarse — «¿qué tengo mañana?» es la otra pregunta obvia.
  const [sesiones, setSesiones] = useState(null);
  const [diaPista, setDiaPista] = useState(null);

  async function cargar(de = quien) {
    try {
      setError("");
      const [a, d, v, ses] = await Promise.all([
        getMiAgenda(de), getMiDia(de), getMisAusencias(de), getMisSesiones(de, diaPista),
      ]);
      setSemana(a.semana); setNombre(a.entrenador); setHoy(d); setAusencias(v);
      setSesiones(ses);
    } catch (e) { setError(e.message); }
  }
  useEffect(() => {
    if (eligeOtros) getEntrenadoresAgenda().then(setEquipo).catch(() => {});
  }, [eligeOtros]);
  useEffect(() => { cargar(quien); }, [quien]);
  useEffect(() => {
    if (diaPista) getMisSesiones(quien, diaPista).then(setSesiones).catch(() => {});
  }, [diaPista, quien]);

  function moverDia(pasos) {
    const base = new Date(diaPista || (sesiones && sesiones.fecha) || Date.now());
    base.setDate(base.getDate() + pasos);
    setDiaPista(base.toISOString().slice(0, 10));
  }

  // Los días marcados como ausencia, para pintarlos en el calendario del año.
  const diasFuera = useMemo(() => {
    const m = new Map();
    for (const a of ausencias) {
      for (let d = new Date(a.fecha_inicio); iso(d) <= a.fecha_fin; d.setDate(d.getDate() + 1)) {
        m.set(iso(d), a.motivo || "Ausencia");
      }
    }
    return m;
  }, [ausencias]);

  async function alternar(dia, bloque) {
    const next = semana.map((f) => (f.dia === dia ? { ...f, [bloque]: !f[bloque] } : f));
    setSemana(next);
    try {
      const r = await saveMiSemana(next.map(({ dia, manana, tarde }) => ({ dia, manana, tarde })), quien);
      setSemana(r.semana);
      setAviso("Jornada guardada");
      setTimeout(() => setAviso(""), 2000);
      setHoy(await getMiDia(quien));
    } catch (e) { setError(e.message); cargar(); }
  }

  async function crearAusencia(e) {
    e.preventDefault();
    if (!nueva.fecha_inicio || !nueva.fecha_fin) return;
    try {
      await addMiAusencia(nueva, quien);
      setNueva({ fecha_inicio: "", fecha_fin: "", motivo: "" });
      setAusencias(await getMisAusencias(quien));
      setHoy(await getMiDia(quien));
    } catch (e) { setError(e.message); }
  }

  async function borrar(id) {
    await delMiAusencia(id, quien);
    setAusencias(await getMisAusencias(quien));
    setHoy(await getMiDia(quien));
  }

  return (
    <div className="page">
      <h1>{eligeOtros ? "Agenda de entrenadores" : "Mi agenda"}{nombre ? ` · ${nombre}` : ""}</h1>

      {eligeOtros && (
        <div className="selector-entrenador">
          <label>Entrenador
            <select value={quien} onChange={(e) => setQuien(e.target.value)}>
              <option value="">{nombre || "el primero de la lista"}</option>
              {equipo.map((e) => (
                <option key={e.id} value={e.id}>{e.nombre}</option>
              ))}
            </select>
          </label>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {aviso && <p className="ok-msg">{aviso}</p>}

      {/* ---- SUS PISTAS DE HOY ---- */}
      {sesiones && (
        <section className="pistas-hoy">
          <div className="cab-pistas">
            <h2>{diaPista ? "En pista" : "Hoy en pista"}</h2>
            <div className="nav-dia">
              <button type="button" onClick={() => moverDia(-1)} aria-label="Día anterior">‹</button>
              <span>{fechaLarga(sesiones.fecha)}</span>
              <button type="button" onClick={() => moverDia(1)} aria-label="Día siguiente">›</button>
              {diaPista && (
                <button type="button" className="link-menor" onClick={() => setDiaPista(null)}>hoy</button>
              )}
            </div>
          </div>
          {!sesiones.hay_semana ? (
            <p className="hint">
              La semana del {fechaCorta(sesiones.fecha)} todavía no está montada.
            </p>
          ) : sesiones.pistas.length === 0 ? (
            <p className="hint">Hoy no tienes ninguna pista asignada.</p>
          ) : (
            <div className="rejilla-pistas">
              {sesiones.pistas.map((p, i) => (
                <article key={i} className="pista-card">
                  <header>
                    <span className="pista-turno">{p.turno}</span>
                    <span className="pista-hora">{p.hora_inicio}–{p.hora_fin}</span>
                  </header>
                  <div className="pista-donde">
                    <strong>Pista {p.pista}</strong>
                    <span>{p.sede} · {p.superficie}</span>
                  </div>
                  <ul className="pista-jugadores">
                    {p.jugadores.map((j) => <li key={j.id}>{j.nombre}</li>)}
                  </ul>
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      {/* ---- HOY ---- */}
      {hoy && (
        <section className="card hoy">
          <h2>Hoy · {hoy.dia} {new Date(hoy.fecha).getDate()} de {MESES[new Date(hoy.fecha).getMonth()]}</h2>
          {hoy.ausente ? (
            <p className="hoy-fuera">Estás de baja{hoy.motivo ? `: ${hoy.motivo}` : ""}</p>
          ) : (
            <div className="hoy-bloques">
              <span className={hoy.manana ? "bloque on" : "bloque off"}>
                Mañana {hoy.manana ? "· entrenas" : "· libre"}
              </span>
              <span className={hoy.tarde ? "bloque on" : "bloque off"}>
                Tarde {hoy.tarde ? "· entrenas" : "· libre"}
              </span>
            </div>
          )}
        </section>
      )}

      {/* ---- SEMANA ---- */}
      <section className="card">
        <h2>Mi semana</h2>
        <p className="hint">Marca en qué bloques trabajas. Por defecto, mañana y tarde.</p>
        <table className="semana-tabla">
          <thead>
            <tr><th>Día</th><th>Mañana</th><th>Tarde</th></tr>
          </thead>
          <tbody>
            {semana.filter((f) => f.dia <= 5).map((f) => (
              <tr key={f.dia} className={hoy && f.nombre === hoy.dia ? "es-hoy" : ""}>
                <td>{f.nombre}</td>
                {["manana", "tarde"].map((b) => (
                  <td key={b}>
                    <button
                      type="button"
                      className={f[b] ? "toggle on" : "toggle off"}
                      aria-pressed={f[b]}
                      onClick={() => alternar(f.dia, b)}
                    >
                      {f[b] ? "Sí" : "No"}
                    </button>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* ---- CALENDARIO ANUAL ---- */}
      <section className="card">
        <h2>Calendario del año</h2>
        <p className="hint">
          Para bajas, viajes o vueltas con meses de antelación. Los días marcados
          salen en rojo y el motor no te pondrá en pista.
        </p>

        <form className="fila-form" onSubmit={crearAusencia}>
          <label>Desde
            <input type="date" required value={nueva.fecha_inicio}
              onChange={(e) => setNueva({ ...nueva, fecha_inicio: e.target.value })} />
          </label>
          <label>Hasta
            <input type="date" required value={nueva.fecha_fin}
              onChange={(e) => setNueva({ ...nueva, fecha_fin: e.target.value })} />
          </label>
          <label className="crece">Motivo
            <input type="text" placeholder="operación, viaje, curso…" value={nueva.motivo}
              onChange={(e) => setNueva({ ...nueva, motivo: e.target.value })} />
          </label>
          <button type="submit" className="btn">Añadir</button>
        </form>

        {ausencias.length > 0 && (
          <ul className="lista-ausencias">
            {ausencias.map((a) => (
              <li key={a.id}>
                <span>{a.fecha_inicio} → {a.fecha_fin}</span>
                <span className="motivo">{a.motivo}</span>
                <button className="link-danger" onClick={() => borrar(a.id)}>Quitar</button>
              </li>
            ))}
          </ul>
        )}

        <div className="anio-nav">
          <button className="btn-sm" onClick={() => setAnio(anio - 1)}>←</button>
          <strong>{anio}</strong>
          <button className="btn-sm" onClick={() => setAnio(anio + 1)}>→</button>
        </div>
        <div className="anio">
          {MESES.map((m, mi) => (
            <div key={mi} className="mes">
              <div className="mes-nombre">{m}</div>
              <div className="mes-dias">
                {Array.from({ length: new Date(anio, mi + 1, 0).getDate() }, (_, i) => {
                  const f = `${anio}-${String(mi + 1).padStart(2, "0")}-${String(i + 1).padStart(2, "0")}`;
                  const fuera = diasFuera.get(f);
                  return (
                    <span key={f} className={fuera ? "dia fuera" : "dia"} title={fuera || f}>
                      {i + 1}
                    </span>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
