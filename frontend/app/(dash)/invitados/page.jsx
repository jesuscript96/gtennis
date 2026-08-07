"use client";
import { useEffect, useState } from "react";
import { getInvitados, crearInvitado, aprobarInvitado, rechazarInvitado, getUser, resource } from "../../../lib/api";

const ESTADO_CLASS = { PENDIENTE: "pend", APROBADO: "ok", RECHAZADO: "no" };

export default function InvitadosPage() {
  const [items, setItems] = useState(null);
  const [jugadores, setJugadores] = useState([]);
  const [error, setError] = useState(null);
  const [form, setForm] = useState({ nombre: "", grupo_anfitrion: "", nota: "" });
  const [saving, setSaving] = useState(false);
  const user = getUser();
  const esAdmin = !!user?.is_superadmin;

  async function load() {
    try { setItems(await getInvitados()); } catch (e) { setError(String(e.message || e)); }
  }
  useEffect(() => {
    load();
    resource("jugadores").list().then(setJugadores).catch(() => {});
  }, []);

  async function crear(e) {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      await crearInvitado({
        nombre: form.nombre,
        grupo_anfitrion: form.grupo_anfitrion ? Number(form.grupo_anfitrion) : null,
        nota: form.nota,
      });
      setForm({ nombre: "", grupo_anfitrion: "", nota: "" });
      await load();
    } catch (e) { setError(String(e.message || e)); } finally { setSaving(false); }
  }

  async function accion(fn) {
    try { await fn(); await load(); } catch (e) { alert(String(e.message || e)); }
  }

  if (error && !items) return <p className="err">{error}</p>;
  if (!items) return <p className="msg">Cargando invitados…</p>;

  const pendientes = items.filter((i) => i.estado === "PENDIENTE");

  return (
    <div>
      <div className="page-head"><h1>Invitados</h1></div>
      <p className="help">Un entrenador propone un invitado (solo su grupo). El Director Deportivo debe aprobarlo antes de que entre en los entrenamientos.</p>

      <form className="inv-form card" onSubmit={crear}>
        <div className="inv-row">
          <input className="search" placeholder="Nombre del invitado" required value={form.nombre}
            onChange={(e) => setForm((f) => ({ ...f, nombre: e.target.value }))} />
          <select value={form.grupo_anfitrion} onChange={(e) => setForm((f) => ({ ...f, grupo_anfitrion: e.target.value }))}>
            <option value="">Grupo anfitrión (jugador)…</option>
            {jugadores.map((j) => <option key={j.id} value={j.id}>{j.nombre}</option>)}
          </select>
          <input className="search" placeholder="Nota (opcional)" value={form.nota}
            onChange={(e) => setForm((f) => ({ ...f, nota: e.target.value }))} />
          <button className="btn" disabled={saving}>{saving ? "Enviando…" : "Solicitar"}</button>
        </div>
        {error && <p className="err">{error}</p>}
      </form>

      {esAdmin && pendientes.length > 0 && (
        <p className="help" style={{ borderLeftColor: "var(--accent)" }}>
          Tienes <b>{pendientes.length}</b> invitado(s) pendiente(s) de aprobar.
        </p>
      )}

      <div className="card">
        <table className="data">
          <thead><tr><th>Invitado</th><th>Solicita</th><th>Grupo</th><th>Estado</th><th style={{ textAlign: "right" }}>Acciones</th></tr></thead>
          <tbody>
            {items.length === 0 ? (
              <tr><td colSpan={5} className="msg">Sin invitados.</td></tr>
            ) : items.map((i) => (
              <tr key={i.id}>
                <td>{i.nombre}</td>
                <td>{i.entrenador_nombre}</td>
                <td>{i.grupo_nombre || "—"}</td>
                <td><span className={`pill ${ESTADO_CLASS[i.estado]}`}>{i.estado_display}</span></td>
                <td>
                  <div className="row-actions">
                    {esAdmin && i.estado === "PENDIENTE" ? (
                      <>
                        <button className="btn sm" onClick={() => accion(() => aprobarInvitado(i.id))}>Aprobar</button>
                        <button className="btn danger sm" onClick={() => accion(() => rechazarInvitado(i.id))}>Rechazar</button>
                      </>
                    ) : <span className="msg">—</span>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
