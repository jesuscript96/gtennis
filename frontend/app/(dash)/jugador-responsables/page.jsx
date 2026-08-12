"use client";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { resource } from "../../../lib/api";

function Inner() {
  const params = useSearchParams();
  const jugadorId = params.get("jugador");
  const jugadorNombre = params.get("nombre") || "jugador";
  const [rows, setRows] = useState(null);
  const [entrenadores, setEntrenadores] = useState([]);
  const [nuevo, setNuevo] = useState("");
  const [rol, setRol] = useState("secundario");
  const [error, setError] = useState(null);

  async function load() {
    try {
      setRows(await resource("responsables").list(`?jugador=${jugadorId}`));
    } catch (e) {
      setError(String(e.message || e));
    }
  }
  useEffect(() => {
    if (!jugadorId) return;
    load();
    resource("entrenadores").list().then(setEntrenadores).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jugadorId]);

  async function anadir(e) {
    e.preventDefault();
    if (!nuevo) return;
    const prioridad = rol === "principal" ? 1 : 2;
    try {
      await resource("responsables").create({
        jugador: Number(jugadorId),
        entrenador: Number(nuevo),
        prioridad,
      });
      setNuevo("");
      setError(null);
      await load();
    } catch (e) {
      setError(String(e.message || e));
    }
  }
  async function quitar(id) {
    try {
      await resource("responsables").remove(id);
      await load();
    } catch (e) {
      alert(String(e.message || e));
    }
  }

  if (!jugadorId)
    return <p className="msg">Abre esta página desde el botón «Entrenadores» de un jugador.</p>;
  if (error && !rows) return <p className="err">{error}</p>;
  if (!rows) return <p className="msg">Cargando…</p>;

  const usados = new Set(rows.map((r) => r.entrenador));
  const ordenados = [...rows].sort((a, b) => a.prioridad - b.prioridad);

  return (
    <div>
      <div className="page-head"><h1>Entrenadores de {jugadorNombre}</h1></div>
      <p className="help">
        El grupo <b>principal</b> (los entrenadores de su sub-columna) se lleva el
        <b> 70%</b>; los <b>secundarios</b> (otras sub-columnas de su mismo bloque de
        color), el <b>30%</b>. Dentro de cada grupo el % se reparte a partes iguales.
        El motor lo usa para decidir con quién entrena cada jugador.
      </p>

      <div className="card">
        <table className="data">
          <thead>
            <tr><th>Peso</th><th>Entrenador</th><th>%</th><th style={{ textAlign: "right" }}>Acciones</th></tr>
          </thead>
          <tbody>
            {ordenados.length === 0 ? (
              <tr><td colSpan={4} className="msg">Sin entrenadores asignados.</td></tr>
            ) : ordenados.map((r) => (
              <tr key={r.id}>
                <td>{r.prioridad === 1 ? "Principal" : `Secundario (${r.prioridad})`}</td>
                <td>{r.entrenador_nombre}</td>
                <td>{r.porcentaje_objetivo}%</td>
                <td style={{ textAlign: "right" }}>
                  <button className="btn danger sm" onClick={() => quitar(r.id)}>Quitar</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <form className="toolbar" onSubmit={anadir} style={{ marginTop: 12 }}>
        <select value={nuevo} onChange={(e) => setNuevo(e.target.value)}>
          <option value="">Añadir entrenador…</option>
          {entrenadores.filter((e) => !usados.has(e.id)).map((e) => (
            <option key={e.id} value={e.id}>{e.nombre}</option>
          ))}
        </select>
        <select value={rol} onChange={(e) => setRol(e.target.value)}>
          <option value="principal">como Principal</option>
          <option value="secundario">como Secundario</option>
        </select>
        <button className="btn" disabled={!nuevo}>Añadir</button>
      </form>
      {error && <p className="err">{error}</p>}
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<p className="msg">Cargando…</p>}>
      <Inner />
    </Suspense>
  );
}
