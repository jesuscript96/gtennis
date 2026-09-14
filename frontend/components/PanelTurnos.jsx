"use client";

import { useEffect, useMemo, useState } from "react";
import { resource } from "../lib/api";

const DIAS = [
  [0, "Lunes"], [1, "Martes"], [2, "Miércoles"],
  [3, "Jueves"], [4, "Viernes"], [5, "Sábado"],
];

/**
 * Cuándo entrena un alumno: su franja de mañana, la de tarde y los días que se
 * salen de lo habitual.
 *
 * Es el mismo panel para el entrenador (dentro de "Mis jugadores") y para
 * dirección (desde la ficha del alumno). El dato es el mismo y tiene que
 * declararse igual; lo único que cambia es desde dónde se abre.
 *
 * Sin franja declarada el motor elige, y en todo caso mete al alumno en UNA de
 * las dos de cada bloque, nunca en las dos el mismo día.
 */
export default function PanelTurnos({ jugador, onGuardado, compacto = false }) {
  const api = useMemo(() => resource("jugadores"), []);
  const [turnos, setTurnos] = useState([]);
  const [j, setJ] = useState(jugador);
  const [guardando, setGuardando] = useState(false);
  const [aviso, setAviso] = useState("");
  const [error, setError] = useState("");

  useEffect(() => { setJ(jugador); }, [jugador]);
  useEffect(() => {
    resource("turnos").list().then(setTurnos).catch(() => {});
  }, []);

  const manana = turnos.filter((t) => t.bloque === "MANANA" && t.codigo !== "JP");
  const tarde = turnos.filter((t) => t.bloque !== "MANANA");
  const etiqueta = (t) => `${t.codigo} · ${t.hora_inicio.slice(0, 5)}`;
  const porDia = new Map((j.horario || []).map((f) => [f.dia, f]));

  async function guardar(cambios) {
    setGuardando(true); setError(""); setAviso("");
    try {
      const actualizado = await api.update(j.id, cambios);
      const nuevo = { ...j, ...actualizado };
      setJ(nuevo);
      setAviso(`Guardado · ${j.nombre}`);
      onGuardado?.(nuevo);
    } catch (e) { setError(e.message); }
    setGuardando(false);
  }

  // Una fila de horario por día que se sale de lo habitual. Sin fila, ese día
  // usa las franjas de arriba.
  function cambiarDia(dia, campo, valor) {
    const filas = [...(j.horario || [])];
    const i = filas.findIndex((f) => f.dia === dia);
    const fila = i >= 0
      ? { ...filas[i] }
      : { dia, turno_manana: j.turno_manana, turno_tarde: j.turno_tarde };
    fila[campo] = valor;
    if (i >= 0) filas[i] = fila; else filas.push(fila);
    guardar({ horario: filas });
  }

  const quitarDia = (dia) =>
    guardar({ horario: (j.horario || []).filter((f) => f.dia !== dia) });

  return (
    <div className="panel-turnos">
      {error && <p className="error">{error}</p>}
      {aviso && <p className="ok-msg">{aviso}</p>}

      <div className="fila-form">
        <label>Por la mañana
          <select value={j.turno_manana || ""} disabled={guardando}
            onChange={(e) => guardar({ turno_manana: e.target.value || null })}>
            <option value="">— la que salga —</option>
            {manana.map((t) => <option key={t.id} value={t.id}>{etiqueta(t)}</option>)}
          </select>
        </label>
        <label>Por la tarde
          <select value={j.turno_tarde || ""} disabled={guardando}
            onChange={(e) => guardar({ turno_tarde: e.target.value || null })}>
            <option value="">— la que salga —</option>
            {tarde.map((t) => <option key={t.id} value={t.id}>{etiqueta(t)}</option>)}
          </select>
        </label>
      </div>
      {!compacto && (
        <p className="hint">
          Sin elegir franja, el motor le pone en la que encaje — siempre una
          sola de las dos al día, nunca las dos.
        </p>
      )}

      <details className="por-dias" open={!compacto && porDia.size > 0}>
        <summary>¿Algún día distinto?</summary>
        <table className="tabla-dias">
          <thead>
            <tr><th>Día</th><th>Mañana</th><th>Tarde</th><th /></tr>
          </thead>
          <tbody>
            {DIAS.map(([d, nombre]) => {
              const f = porDia.get(d);
              return (
                <tr key={d} className={f ? "excepcion" : ""}>
                  <td>{nombre}</td>
                  <td>
                    <select value={(f ? f.turno_manana : j.turno_manana) || ""}
                      disabled={guardando}
                      onChange={(e) => cambiarDia(d, "turno_manana", e.target.value || null)}>
                      <option value="">— no —</option>
                      {manana.map((t) => <option key={t.id} value={t.id}>{t.codigo}</option>)}
                    </select>
                  </td>
                  <td>
                    <select value={(f ? f.turno_tarde : j.turno_tarde) || ""}
                      disabled={guardando}
                      onChange={(e) => cambiarDia(d, "turno_tarde", e.target.value || null)}>
                      <option value="">— no —</option>
                      {tarde.map((t) => <option key={t.id} value={t.id}>{t.codigo}</option>)}
                    </select>
                  </td>
                  <td>
                    {f && (
                      <button type="button" className="link-menor"
                        onClick={() => quitarDia(d)}>
                        como siempre
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </details>
    </div>
  );
}
