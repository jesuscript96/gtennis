"use client";

import { useEffect, useMemo, useState } from "react";
import { resource } from "../lib/api";

const DIAS = [
  [0, "Lunes"], [1, "Martes"], [2, "Miércoles"],
  [3, "Jueves"], [4, "Viernes"], [5, "Sábado"],
];
// El club no abre los miércoles por la tarde (engine.service.CERRADO).
const CERRADO = new Set(["2-tarde"]);
const NO = "NO";

/**
 * Cuándo entrena un alumno: su franja de mañana, la de tarde y los días que se
 * salen de lo habitual.
 *
 * Es el mismo panel para el entrenador (dentro de "Mis jugadores") y para
 * dirección (desde el botón Turnos de la ficha). El dato es el mismo y tiene
 * que declararse igual; lo único que cambia es desde dónde se abre.
 *
 * En cada día, cada bloque tiene TRES respuestas: «la que salga», una franja
 * concreta, o «no entrena». Antes solo había dos y un hueco valía por «no», así
 * que decir «el martes por la tarde no» obligaba a fijarle franja de mañana o
 * le quitaba también las mañanas.
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

  // Qué dice la celda de un día y un bloque: «NO», el id de la franja, o ""
  // para «la que salga». Sin fila, lo de siempre.
  function valorCelda(dia, bloque) {
    const f = porDia.get(dia);
    const turno = bloque === "manana" ? "turno_manana" : "turno_tarde";
    const entrena = bloque === "manana" ? "entrena_manana" : "entrena_tarde";
    if (!f) return j[turno] || "";
    if (f[entrena] === false) return NO;
    return f[turno] || "";
  }

  // Tocar un bloque de un día crea (o cambia) la fila de ese día, y el otro
  // bloque se queda como siempre: esa es la parte que antes se rompía.
  function cambiarDia(dia, bloque, valor) {
    const filas = [...(j.horario || [])];
    const i = filas.findIndex((f) => f.dia === dia);
    const fila = i >= 0 ? { ...filas[i] } : {
      dia,
      turno_manana: j.turno_manana, turno_tarde: j.turno_tarde,
      entrena_manana: true, entrena_tarde: true,
    };
    const turno = bloque === "manana" ? "turno_manana" : "turno_tarde";
    const entrena = bloque === "manana" ? "entrena_manana" : "entrena_tarde";
    if (valor === NO) {
      fila[entrena] = false;
      fila[turno] = null;
    } else {
      fila[entrena] = true;
      fila[turno] = valor ? Number(valor) : null;
    }
    if (i >= 0) filas[i] = fila; else filas.push(fila);
    guardar({ horario: filas });
  }

  const quitarDia = (dia) =>
    guardar({ horario: (j.horario || []).filter((f) => f.dia !== dia) });

  const celda = (dia, bloque, opciones) => {
    if (bloque === "tarde" && CERRADO.has(`${dia}-tarde`)) {
      return <span className="cerrado">cerrado</span>;
    }
    const valor = valorCelda(dia, bloque);
    return (
      <select value={valor} disabled={guardando}
        className={valor === NO ? "no-entrena" : ""}
        onChange={(e) => cambiarDia(dia, bloque, e.target.value)}>
        <option value="">la que salga</option>
        {opciones.map((t) => <option key={t.id} value={t.id}>{t.codigo}</option>)}
        <option value={NO}>no entrena</option>
      </select>
    );
  };

  return (
    <div className="panel-turnos">
      {error && <p className="error">{error}</p>}
      {aviso && <p className="ok-msg">{aviso}</p>}

      <div className="fila-form">
        <label>Por la mañana, de normal
          <select value={j.turno_manana || ""} disabled={guardando}
            onChange={(e) => guardar({ turno_manana: e.target.value || null })}>
            <option value="">— la que salga —</option>
            {manana.map((t) => <option key={t.id} value={t.id}>{etiqueta(t)}</option>)}
          </select>
        </label>
        <label>Por la tarde, de normal
          <select value={j.turno_tarde || ""} disabled={guardando}
            onChange={(e) => guardar({ turno_tarde: e.target.value || null })}>
            <option value="">— la que salga —</option>
            {tarde.map((t) => <option key={t.id} value={t.id}>{etiqueta(t)}</option>)}
          </select>
        </label>
      </div>
      {!compacto && (
        <p className="hint">
          «La que salga» deja elegir al programa, siempre una sola de las dos al
          día. Para quitarle un bloque un día concreto, usa la tabla de abajo.
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
                  <td>{celda(d, "manana", manana)}</td>
                  <td>{celda(d, "tarde", tarde)}</td>
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
