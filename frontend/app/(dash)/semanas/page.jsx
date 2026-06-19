"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { resource, generarSemana, publicarSemana } from "../../../lib/api";

const api = resource("semanas");

export default function SemanasPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [fecha, setFecha] = useState("");
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  async function load() {
    setLoading(true);
    try {
      setItems(await api.list());
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, []);

  async function crear(e) {
    e.preventDefault();
    setError(null);
    try {
      await api.create({ fecha_inicio: fecha });
      setFecha("");
      await load();
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  async function run(id, label, fn) {
    setBusy(`${id}-${label}`);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <div className="page-head"><h1>Semanas</h1></div>

      <form className="toolbar" onSubmit={crear}>
        <input type="date" style={{ maxWidth: 200 }} value={fecha} onChange={(e) => setFecha(e.target.value)} required />
        <button className="btn">Crear semana</button>
        <span style={{ color: "var(--muted)", fontSize: 12 }}>(lunes de la semana)</span>
      </form>
      {error && <p className="err">{error}</p>}

      <div className="card">
        <table className="data">
          <thead>
            <tr>
              <th>Inicio</th><th>Estado</th><th>Generado</th><th>Publicado</th>
              <th style={{ textAlign: "right" }}>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} className="msg">Cargando…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={5} className="msg">Sin semanas.</td></tr>
            ) : (
              items.map((s) => (
                <tr key={s.id}>
                  <td>{s.fecha_inicio}</td>
                  <td>
                    <span className={`pill ${s.estado === "PUBLICADO" ? "yes" : "no"}`}>
                      {s.estado === "PUBLICADO" ? "Publicado" : "Borrador"}
                    </span>
                  </td>
                  <td>{s.generado_at ? "Sí" : "—"}</td>
                  <td>{s.publicado_at ? "Sí" : "—"}</td>
                  <td>
                    <div className="row-actions">
                      <button className="btn ghost sm" disabled={busy} onClick={() => run(s.id, "gen", () => generarSemana(s.id))}>
                        {busy === `${s.id}-gen` ? "…" : "Generar"}
                      </button>
                      <button className="btn ghost sm" disabled={busy || s.estado === "PUBLICADO"} onClick={() => run(s.id, "pub", () => publicarSemana(s.id))}>
                        Publicar
                      </button>
                      <Link className="btn sm" href="/cuadrante">Ver</Link>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
