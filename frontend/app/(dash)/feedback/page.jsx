"use client";
import { useEffect, useMemo, useState } from "react";
import { resource, getUser } from "../../../lib/api";

// Definicion de las 3 pestanas: mapean a uno o varios estados del backend.
const TABS = [
  {
    key: "NUEVO",
    label: "Nuevo",
    descripcion: "Pendiente de implementar en la plataforma.",
    estados: ["NUEVO", "EN_PROGRESO"],
    defecto: "NUEVO",
    clase: "tab-nuevo",
  },
  {
    key: "HECHO",
    label: "Implementado",
    descripcion: "Ya hecho en producción — pendiente de testear por el club.",
    estados: ["HECHO"],
    defecto: "HECHO",
    clase: "tab-hecho",
  },
  {
    key: "AJENO",
    label: "Ajenos a esta plataforma",
    descripcion: "Temas que no corresponden a esta app (precios, web pública, mantenimiento del club…).",
    estados: ["AJENO", "DESCARTADO"],
    defecto: "AJENO",
    clase: "tab-ajeno",
  },
];

const PRIORIDAD_CLASS = { ALTA: "alta", MEDIA: "media", BAJA: "baja" };
const EMPTY = {
  autor: "", titulo: "", descripcion: "", prioridad: "MEDIA", estado: "NUEVO",
};

export default function FeedbackPage() {
  const api = useMemo(() => resource("feedback"), []);
  const user = getUser();
  const esAdmin = !!user?.is_superadmin;

  const [tabKey, setTabKey] = useState("NUEVO");
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [editando, setEditando] = useState(null);   // item que se edita, o null
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);

  const tab = TABS.find((t) => t.key === tabKey);

  async function load() {
    setError(null);
    try {
      const estadosQ = tab.estados.join(",");
      const q = search
        ? `?estado=${estadosQ}&search=${encodeURIComponent(search)}`
        : `?estado=${estadosQ}`;
      setItems(await api.list(q));
    } catch (e) { setError(String(e.message || e)); }
  }

  useEffect(() => { setItems(null); load(); /* eslint-disable-next-line */ }, [tabKey]);
  useEffect(() => { if (items !== null) load(); /* eslint-disable-next-line */ }, [search]);

  function abrirNuevo() {
    setEditando("nuevo");
    setForm({ ...EMPTY, estado: tab.defecto });
    setFormError(null);
  }
  function abrirEditar(it) {
    setEditando(it.id);
    setForm({
      autor: it.autor || "", titulo: it.titulo || "",
      descripcion: it.descripcion || "", prioridad: it.prioridad,
      estado: it.estado,
    });
    setFormError(null);
  }
  function cancelar() { setEditando(null); setFormError(null); }

  async function guardar(e) {
    e.preventDefault();
    setSaving(true); setFormError(null);
    try {
      const body = {
        autor: form.autor || "Anónimo",
        titulo: form.titulo,
        descripcion: form.descripcion,
        prioridad: form.prioridad,
        estado: form.estado,
      };
      if (editando === "nuevo") await api.create(body);
      else await api.update(editando, body);
      setEditando(null);
      await load();
    } catch (e) { setFormError(String(e.message || e)); }
    finally { setSaving(false); }
  }

  async function borrar(id) {
    if (!confirm("¿Borrar este item de feedback?")) return;
    try { await api.remove(id); await load(); }
    catch (e) { alert(String(e.message || e)); }
  }

  // Mover entre pestanas: cambia el estado y recarga.
  async function mover(it, nuevoEstado) {
    try { await api.update(it.id, { estado: nuevoEstado }); await load(); }
    catch (e) { alert(String(e.message || e)); }
  }

  if (error && !items) return <p className="err">{error}</p>;
  if (!items) return <p className="msg">Cargando feedback…</p>;

  return (
    <div>
      <div className="page-head"><h1>Feedback</h1></div>

      <div className="feedback-tabs">
        {TABS.map((t) => (
          <button key={t.key} className={`tab ${t.clase} ${t.key === tabKey ? "active" : ""}`}
            onClick={() => setTabKey(t.key)}>
            {t.label}
          </button>
        ))}
      </div>
      <p className="help">{tab.descripcion}</p>

      <div className="feedback-toolbar">
        <input className="search" placeholder="Buscar…"
          value={search} onChange={(e) => setSearch(e.target.value)} />
        {esAdmin && (
          <button className="btn" onClick={abrirNuevo}>+ Nuevo en "{tab.label}"</button>
        )}
      </div>

      {editando !== null && (
        <form className="card fb-form" onSubmit={guardar}>
          <h3>{editando === "nuevo" ? "Nuevo item" : "Editar item"}</h3>
          <div className="fb-row">
            <input className="search" placeholder="Autor (quién lo pide)"
              value={form.autor} onChange={(e) => setForm({ ...form, autor: e.target.value })} />
            <select value={form.prioridad} onChange={(e) => setForm({ ...form, prioridad: e.target.value })}>
              <option value="ALTA">Prioridad Alta</option>
              <option value="MEDIA">Prioridad Media</option>
              <option value="BAJA">Prioridad Baja</option>
            </select>
            <select value={form.estado} onChange={(e) => setForm({ ...form, estado: e.target.value })}>
              <option value="NUEVO">Nuevo</option>
              <option value="EN_PROGRESO">En progreso</option>
              <option value="HECHO">Implementado</option>
              <option value="AJENO">Ajeno a esta plataforma</option>
              <option value="DESCARTADO">Descartado</option>
            </select>
          </div>
          <input className="search" placeholder="Título corto"
            value={form.titulo} onChange={(e) => setForm({ ...form, titulo: e.target.value })} />
          <textarea className="search" rows={3} placeholder="Descripción / detalle"
            value={form.descripcion} onChange={(e) => setForm({ ...form, descripcion: e.target.value })} />
          {formError && <p className="err">{formError}</p>}
          <div className="fb-actions">
            <button className="btn" disabled={saving}>{saving ? "Guardando…" : "Guardar"}</button>
            <button type="button" className="btn ghost" onClick={cancelar}>Cancelar</button>
          </div>
        </form>
      )}

      <div className="card">
        <table className="data">
          <thead>
            <tr>
              <th>Prioridad</th><th>Título</th><th>Descripción</th><th>Autor</th>
              <th style={{ textAlign: "right" }}>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr><td colSpan={5} className="msg">Sin items en esta pestaña.</td></tr>
            ) : items.map((it) => (
              <tr key={it.id}>
                <td>
                  <span className={`pill prio-${PRIORIDAD_CLASS[it.prioridad]}`}>
                    {it.prioridad_display}
                  </span>
                </td>
                <td><b>{it.titulo || "—"}</b></td>
                <td className="fb-desc">{it.descripcion}</td>
                <td>{it.autor || "—"}</td>
                <td>
                  <div className="row-actions">
                    {esAdmin && (
                      <>
                        {/* Mover a otra pestana con un click */}
                        {TABS.filter((t) => t.key !== tabKey).map((t) => (
                          <button key={t.key} className="btn sm ghost" title={`Mover a ${t.label}`}
                            onClick={() => mover(it, t.defecto)}>
                            → {t.label}
                          </button>
                        ))}
                        <button className="btn sm" onClick={() => abrirEditar(it)}>Editar</button>
                        <button className="btn danger sm" onClick={() => borrar(it.id)}>Borrar</button>
                      </>
                    )}
                    {!esAdmin && <span className="msg">solo lectura</span>}
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
