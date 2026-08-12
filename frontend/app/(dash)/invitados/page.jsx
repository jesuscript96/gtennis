"use client";
import { useEffect, useState } from "react";
import { getInvitados, crearInvitado, aprobarInvitado, rechazarInvitado, getUser, resource } from "../../../lib/api";

const ESTADO_CLASS = { PENDIENTE: "pend", APROBADO: "ok", RECHAZADO: "no" };

export default function InvitadosPage() {
  const [items, setItems] = useState(null);
  const [jugadores, setJugadores] = useState([]);
  const [entrenadores, setEntrenadores] = useState([]);
  const [error, setError] = useState(null);
  const EMPTY = { nombre: "", entrenador_solicitante: "", nota: "", edad: "", superficie_pref: "", jugar_con: "", pareja_estricta: true };
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const user = getUser();
  const esAdmin = !!user?.is_superadmin;

  async function load() {
    try { setItems(await getInvitados()); } catch (e) { setError(String(e.message || e)); }
  }
  useEffect(() => {
    load();
    resource("jugadores").list().then(setJugadores).catch(() => {});
    if (esAdmin) resource("entrenadores").list().then(setEntrenadores).catch(() => {});
  }, [esAdmin]);

  async function crear(e) {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      await crearInvitado({
        nombre: form.nombre,
        // Admin elige entrenador; entrenador/coach se autorrellena en backend.
        entrenador_solicitante: esAdmin && form.entrenador_solicitante
          ? Number(form.entrenador_solicitante) : undefined,
        nota: form.nota,
        edad: form.edad ? Number(form.edad) : null,
        superficie_pref: form.superficie_pref || "",
        jugar_con: form.jugar_con ? Number(form.jugar_con) : null,
        pareja_estricta: form.pareja_estricta,
      });
      setForm(EMPTY);
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
      <p className="help">
        {esAdmin
          ? "Selecciona el entrenador que propone al invitado para asociarlo a su grupo. Tras aprobarlo se creará como jugador activo."
          : "Propón un invitado para tu grupo. Dirección deportiva lo aprobará antes de que entre en los entrenamientos."}
      </p>

      <form className="inv-form card" onSubmit={crear}>
        <div className="inv-row">
          <input className="search" placeholder="Nombre del invitado" required value={form.nombre}
            onChange={(e) => setForm((f) => ({ ...f, nombre: e.target.value }))} />
          {esAdmin ? (
            <select value={form.entrenador_solicitante} required
              onChange={(e) => setForm((f) => ({ ...f, entrenador_solicitante: e.target.value }))}>
              <option value="">Entrenador que propone…</option>
              {entrenadores.map((en) => <option key={en.id} value={en.id}>{en.nombre}</option>)}
            </select>
          ) : null}
          <input className="search" placeholder="Nota (opcional)" value={form.nota}
            onChange={(e) => setForm((f) => ({ ...f, nota: e.target.value }))} />
          <button className="btn" disabled={saving}>{saving ? "Enviando…" : "Solicitar"}</button>
        </div>
        <div className="inv-row">
          <input className="search" type="number" min="3" max="99" placeholder="Edad (opcional)" value={form.edad}
            onChange={(e) => setForm((f) => ({ ...f, edad: e.target.value }))} />
          <select value={form.superficie_pref} onChange={(e) => setForm((f) => ({ ...f, superficie_pref: e.target.value }))}>
            <option value="">Superficie indiferente</option>
            <option value="TIERRA">Tierra batida</option>
            <option value="RESINA">Resina (rápida)</option>
          </select>
          <select value={form.jugar_con} onChange={(e) => setForm((f) => ({ ...f, jugar_con: e.target.value }))}>
            <option value="">Jugar con… (pareja preferida)</option>
            {jugadores.map((j) => <option key={j.id} value={j.id}>{j.nombre}</option>)}
          </select>
          <label className="inv-check">
            <input type="checkbox" checked={form.pareja_estricta}
              onChange={(e) => setForm((f) => ({ ...f, pareja_estricta: e.target.checked }))} />
            Misma pista obligatoria
          </label>
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
          <thead><tr><th>Invitado</th><th>Propone</th><th>Estado</th><th style={{ textAlign: "right" }}>Acciones</th></tr></thead>
          <tbody>
            {items.length === 0 ? (
              <tr><td colSpan={4} className="msg">Sin invitados.</td></tr>
            ) : items.map((i) => (
              <tr key={i.id}>
                <td>{i.nombre}</td>
                <td>{i.entrenador_nombre || "—"}</td>
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
