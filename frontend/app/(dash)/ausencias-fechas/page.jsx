"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getAusenciasFechas, addAusenciaFechas, delAusenciaFechas, resource,
} from "../../../lib/api";

const AMBITOS = [
  ["DIA", "Todo el día"],
  ["MANANA", "Toda la mañana"],
  ["TARDE", "Toda la tarde"],
  ["M1", "M1 · 8:30-10:00"],
  ["M2", "M2 · 10:30-12:30"],
  ["JP", "Junior Program · 12:30-14:30"],
  ["T1", "T1 · 14:15-15:30"],
  ["T2", "T2 · 15:30-17:30"],
];
// «Todo el día» y los bloques enteros ya incluyen a los demás: marcarlos con
// una franja suelta sería contradictorio, así que se excluyen entre sí.
const GENERALES = ["DIA", "MANANA", "TARDE"];
const NOMBRE_AMBITO = (v) => (AMBITOS.find(([k]) => k === v) || [, v])[1];
const MOTIVOS = [
  ["LESION", "Lesión"], ["ENFERMEDAD", "Enfermedad"], ["ESTUDIOS", "Estudios"],
  ["PRUEBA_MEDICA", "Prueba médica"], ["VACACIONES", "Vacaciones / viaje"],
];
const VACIO = {
  jugador: "", fecha_inicio: "", fecha_fin: "", ambitos: ["DIA"],
  hora_desde: "", hora_hasta: "", estado: "AUSENCIA_JUGADOR", subtipo: "", nota: "",
};

export default function AusenciasFechas() {
  const [lista, setLista] = useState([]);
  const [jugadores, setJugadores] = useState([]);
  const [f, setF] = useState(VACIO);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");

  useEffect(() => {
    resource("jugadores").list().then((d) => setJugadores(d.results || d)).catch(() => {});
    recargar();
  }, []);
  const recargar = () => getAusenciasFechas().then(setLista).catch((e) => setError(e.message));

  // El formulario cambia de forma según lo que se esté declarando: para un
  // solo día tiene sentido afinar la hora ("llega a las 10:30"); para una baja
  // de tres semanas, no — ahí basta con el ámbito.
  const unSoloDia = f.fecha_inicio && f.fecha_inicio === f.fecha_fin;
  const dias = useMemo(() => {
    if (!f.fecha_inicio || !f.fecha_fin) return 0;
    const a = new Date(f.fecha_inicio), b = new Date(f.fecha_fin);
    return Math.round((b - a) / 86400000) + 1;
  }, [f.fecha_inicio, f.fecha_fin]);

  function set(campo, valor) {
    setF((prev) => {
      const next = { ...prev, [campo]: valor };
      // Al elegir la ida, se propone el mismo día como vuelta: la mayoría de
      // las ausencias son de una jornada.
      if (campo === "fecha_inicio" && !prev.fecha_fin) next.fecha_fin = valor;
      // Si deja de ser un solo día, las horas ya no aplican.
      if (next.fecha_inicio !== next.fecha_fin) { next.hora_desde = ""; next.hora_hasta = ""; }
      return next;
    });
  }

  // «Todo el día» manda sobre lo demás; marcar M1 después de él lo sustituye,
  // y marcar la mañana entera retira M1, M2 y JP. Así no se guardan filas que
  // se contradicen.
  function alternarAmbito(v) {
    setF((prev) => {
      const tenia = prev.ambitos.includes(v);
      if (tenia) {
        const quedan = prev.ambitos.filter((x) => x !== v);
        return { ...prev, ambitos: quedan.length ? quedan : ["DIA"] };
      }
      if (GENERALES.includes(v)) return { ...prev, ambitos: [v] };
      return { ...prev, ambitos: [...prev.ambitos.filter((x) => !GENERALES.includes(x)), v] };
    });
  }

  async function crear(e) {
    e.preventDefault();
    setError(""); setAviso("");
    try {
      const body = { ...f };
      if (!body.hora_desde) delete body.hora_desde;
      if (!body.hora_hasta) delete body.hora_hasta;
      if (!body.subtipo) delete body.subtipo;
      const creadas = await addAusenciaFechas(body);
      const n = Array.isArray(creadas) ? creadas.length : 1;
      setF(VACIO); recargar();
      setAviso(n > 1 ? `Ausencia declarada en ${n} franjas` : "Ausencia declarada");
      setTimeout(() => setAviso(""), 2500);
    } catch (e) { setError(e.message); }
  }

  return (
    <div className="page">
      <h1>Ausencias por fechas</h1>
      <p className="hint">
        Una baja larga se declara una sola vez, con su fecha de ida y de vuelta.
        Para algo de un día concreto se puede afinar la franja o la hora.
      </p>
      {error && <p className="error">{error}</p>}
      {aviso && <p className="ok-msg">{aviso}</p>}

      <form className="card form-ausencia" onSubmit={crear}>
        <div className="fila-form">
          <label className="crece">Jugador
            <select required value={f.jugador} onChange={(e) => set("jugador", e.target.value)}>
              <option value="">— elige —</option>
              {jugadores.map((j) => <option key={j.id} value={j.id}>{j.nombre}</option>)}
            </select>
          </label>
          <label>Desde
            <input type="date" required value={f.fecha_inicio}
              onChange={(e) => set("fecha_inicio", e.target.value)} />
          </label>
          <label>Hasta
            <input type="date" required value={f.fecha_fin}
              onChange={(e) => set("fecha_fin", e.target.value)} />
          </label>
          {dias > 0 && (
            <span className="badge-dias">
              {dias === 1 ? "un solo día" : `${dias} días`}
            </span>
          )}
        </div>

        <div className="fila-form">
          <label>Motivo
            <select value={f.subtipo} onChange={(e) => set("subtipo", e.target.value)}>
              <option value="">— sin especificar —</option>
              {MOTIVOS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
            </select>
          </label>
        </div>

        <div className="bloque-ambitos">
          <span className="etiqueta-bloque">
            ¿Qué se pierde? Puedes marcar varias franjas
          </span>
          <div className="chips-ambito">
            {AMBITOS.map(([v, t]) => (
              <label key={v} className={f.ambitos.includes(v) ? "chip-ambito activo" : "chip-ambito"}>
                <input type="checkbox" checked={f.ambitos.includes(v)}
                  onChange={() => alternarAmbito(v)} />
                {t}
              </label>
            ))}
          </div>
        </div>

        {/* Solo para un día: la hora exacta. En un rango no tiene sentido. */}
        {unSoloDia && (
          <div className="fila-form franja-horas">
            <span className="etiqueta-bloque">Solo un día: puedes acotar la hora</span>
            <label>De
              <input type="time" value={f.hora_desde}
                onChange={(e) => set("hora_desde", e.target.value)} />
            </label>
            <label>A
              <input type="time" value={f.hora_hasta}
                onChange={(e) => set("hora_hasta", e.target.value)} />
            </label>
            <span className="hint sin-margen">
              Déjalas vacías si falta al alcance entero.
            </span>
          </div>
        )}

        <div className="fila-form">
          <label className="crece">Nota
            <input type="text" placeholder="operación de rodilla, viaje familiar…"
              value={f.nota} onChange={(e) => set("nota", e.target.value)} />
          </label>
          <button type="submit" className="btn">Declarar ausencia</button>
        </div>
      </form>

      <section className="card">
        <h2>Declaradas</h2>
        {lista.length === 0 ? (
          <p className="hint">Todavía no hay ninguna.</p>
        ) : (
          <table className="tabla-ausencias">
            <thead>
              <tr>
                <th>Jugador</th><th>Desde</th><th>Hasta</th><th>Alcance</th>
                <th>Motivo</th><th>Nota</th><th></th>
              </tr>
            </thead>
            <tbody>
              {lista.map((a) => (
                <tr key={a.id}>
                  <td>{a.jugador_nombre}</td>
                  <td>{a.fecha_inicio}</td>
                  <td>{a.fecha_fin}</td>
                  <td>
                    {NOMBRE_AMBITO(a.ambito)}
                    {a.hora_desde && (
                      <span className="horas"> {a.hora_desde.slice(0, 5)}–{(a.hora_hasta || "").slice(0, 5)}</span>
                    )}
                  </td>
                  <td>{(MOTIVOS.find(([v]) => v === a.subtipo) || [, "—"])[1]}</td>
                  <td className="nota-celda">{a.nota}</td>
                  <td>
                    <button className="link-danger"
                      onClick={() => delAusenciaFechas(a.id).then(recargar)}>
                      Quitar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
