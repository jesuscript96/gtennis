"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { resource } from "../lib/api";

const DIAS = [
  [0, "L", "Lunes"], [1, "M", "Martes"], [2, "X", "Miércoles"],
  [3, "J", "Jueves"], [4, "V", "Viernes"], [5, "S", "Sábado"],
];

/**
 * Los jugadores de un entrenador: una lista de nombres y nada más.
 *
 * El entrenador no gestiona la ficha del alumno, así que no tiene sentido
 * enseñarle una tabla de campos vacíos con guiones. Lo único que declara es
 * cuándo entrena cada uno, y eso se abre al desplegar su fila.
 */
export default function MisJugadores() {
  const api = useMemo(() => resource("jugadores"), []);
  const [jugadores, setJugadores] = useState([]);
  const [turnos, setTurnos] = useState([]);
  const [abierto, setAbierto] = useState(null);
  const [busca, setBusca] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [aviso, setAviso] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.list().then(setJugadores).catch((e) => setError(e.message));
    resource("turnos").list().then(setTurnos).catch(() => {});
  }, [api]);

  const manana = turnos.filter((t) => t.bloque === "MANANA" && t.codigo !== "JP");
  const tarde = turnos.filter((t) => t.bloque !== "MANANA");
  const etiqueta = (t) => `${t.codigo} · ${t.hora_inicio.slice(0, 5)}`;

  const visibles = jugadores.filter((j) =>
    j.nombre.toLowerCase().includes(busca.trim().toLowerCase())
  );

  function resumen(j) {
    const m = turnos.find((t) => t.id === j.turno_manana);
    const t = turnos.find((t2) => t2.id === j.turno_tarde);
    const partes = [m && m.codigo, t && t.codigo].filter(Boolean);
    const excepciones = (j.horario || []).length;
    if (!partes.length && !excepciones) return "sin turnos declarados";
    return partes.join(" + ") + (excepciones ? ` · ${excepciones} día${excepciones > 1 ? "s" : ""} distintos` : "");
  }

  async function guardar(j, cambios) {
    setGuardando(true); setError(""); setAviso("");
    try {
      const actualizado = await api.update(j.id, cambios);
      setJugadores((prev) => prev.map((x) => (x.id === j.id ? { ...x, ...actualizado } : x)));
      setAviso(`Guardado · ${j.nombre}`);
    } catch (e) { setError(e.message); }
    setGuardando(false);
  }

  // Una fila de horario por día que se sale de lo habitual. Sin fila, ese día
  // usa los turnos de arriba.
  function cambiarDia(j, dia, campo, valor) {
    const filas = [...(j.horario || [])];
    const i = filas.findIndex((f) => f.dia === dia);
    const fila = i >= 0 ? { ...filas[i] } : { dia, turno_manana: j.turno_manana, turno_tarde: j.turno_tarde };
    fila[campo] = valor;
    if (i >= 0) filas[i] = fila; else filas.push(fila);
    guardar(j, { horario: filas });
  }

  function quitarDia(j, dia) {
    guardar(j, { horario: (j.horario || []).filter((f) => f.dia !== dia) });
  }

  return (
    <div className="page">
      <h1>Mis jugadores</h1>
      <p className="hint">
        Declara cuándo entrena cada uno. Toca un nombre para abrirlo.
      </p>

      <input className="buscador" placeholder="Buscar jugador…" value={busca}
        onChange={(e) => setBusca(e.target.value)} />

      {error && <p className="error">{error}</p>}
      {aviso && <p className="ok-msg">{aviso}</p>}

      <ul className="lista-jugadores">
        {visibles.map((j) => {
          const activo = abierto === j.id;
          const porDia = new Map((j.horario || []).map((f) => [f.dia, f]));
          return (
            <li key={j.id} className={activo ? "abierto" : ""}>
              <button type="button" className="fila-jugador"
                aria-expanded={activo}
                onClick={() => setAbierto(activo ? null : j.id)}>
                <span className="nombre">{j.nombre}</span>
                <span className="resumen">{resumen(j)}</span>
                <span className="chevron" aria-hidden="true">{activo ? "−" : "+"}</span>
              </button>

              {activo && (
                <div className="detalle-jugador">
                  <div className="fila-form">
                    <label>Por la mañana
                      <select value={j.turno_manana || ""} disabled={guardando}
                        onChange={(e) => guardar(j, { turno_manana: e.target.value || null })}>
                        <option value="">— no entrena —</option>
                        {manana.map((t) => <option key={t.id} value={t.id}>{etiqueta(t)}</option>)}
                      </select>
                    </label>
                    <label>Por la tarde
                      <select value={j.turno_tarde || ""} disabled={guardando}
                        onChange={(e) => guardar(j, { turno_tarde: e.target.value || null })}>
                        <option value="">— no entrena —</option>
                        {tarde.map((t) => <option key={t.id} value={t.id}>{etiqueta(t)}</option>)}
                      </select>
                    </label>
                  </div>

                  <details className="por-dias">
                    <summary>¿Algún día distinto?</summary>
                    <table className="tabla-dias">
                      <thead>
                        <tr><th>Día</th><th>Mañana</th><th>Tarde</th><th /></tr>
                      </thead>
                      <tbody>
                        {DIAS.map(([d, , nombre]) => {
                          const f = porDia.get(d);
                          return (
                            <tr key={d} className={f ? "excepcion" : ""}>
                              <td>{nombre}</td>
                              <td>
                                <select value={(f ? f.turno_manana : j.turno_manana) || ""}
                                  disabled={guardando}
                                  onChange={(e) => cambiarDia(j, d, "turno_manana", e.target.value || null)}>
                                  <option value="">— no —</option>
                                  {manana.map((t) => <option key={t.id} value={t.id}>{t.codigo}</option>)}
                                </select>
                              </td>
                              <td>
                                <select value={(f ? f.turno_tarde : j.turno_tarde) || ""}
                                  disabled={guardando}
                                  onChange={(e) => cambiarDia(j, d, "turno_tarde", e.target.value || null)}>
                                  <option value="">— no —</option>
                                  {tarde.map((t) => <option key={t.id} value={t.id}>{t.codigo}</option>)}
                                </select>
                              </td>
                              <td>
                                {f && (
                                  <button type="button" className="link-menor"
                                    onClick={() => quitarDia(j, d)}>
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

                  <div className="accesos">
                    <Link href={`/ausencias-fechas?jugador=${j.id}`}>Declarar una baja</Link>
                    <Link href={`/ausencias?jugador=${j.id}`}>Ausencia de esta semana</Link>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>

      {!visibles.length && <p className="hint">Ningún jugador con ese nombre.</p>}
    </div>
  );
}
