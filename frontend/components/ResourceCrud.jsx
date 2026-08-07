"use client";

import { useEffect, useMemo, useState } from "react";
import { resource } from "../lib/api";

function emptyValue(fl) {
  if (fl.type === "bool") return false;
  if (fl.type === "mfk") return [];
  return "";
}

function defaults(fields) {
  const f = {};
  for (const fl of fields) f[fl.name] = fl.default ?? emptyValue(fl);
  return f;
}

function toBody(fields, form) {
  const body = {};
  for (const fl of fields) {
    let v = form[fl.name];
    if (fl.type === "bool") v = !!v;
    else if (fl.type === "number" || fl.type === "fk") v = v === "" || v == null ? null : Number(v);
    else if (fl.type === "mfk") v = Array.isArray(v) ? v.map(Number) : [];
    else if (fl.type === "select") v = v === "" || v == null ? null : fl.numeric ? Number(v) : v;
    else if (fl.type === "time") v = v === "" || v == null ? null : v;
    body[fl.name] = v;
  }
  return body;
}

export default function ResourceCrud({ config }) {
  const api = useMemo(() => resource(config.endpoint), [config.endpoint]);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [fkOptions, setFkOptions] = useState({});
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const q = config.search && search ? `?search=${encodeURIComponent(search)}` : "";
      setItems(await api.list(q));
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // load fk option lists
    const fks = config.fields.filter((f) => f.type === "fk" || f.type === "mfk");
    Promise.all(
      fks.map((f) => resource(f.endpoint).list().then((rows) => [f.name, rows]).catch(() => [f.name, []]))
    ).then((pairs) => setFkOptions(Object.fromEntries(pairs)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.endpoint]);

  function openNew() {
    setEditing(null);
    setForm(defaults(config.fields));
    setFormError(null);
    setOpen(true);
  }
  function openEdit(row) {
    setEditing(row);
    const f = {};
    for (const fl of config.fields) f[fl.name] = row[fl.name] ?? emptyValue(fl);
    setForm(f);
    setFormError(null);
    setOpen(true);
  }

  async function save(e) {
    e.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      const body = toBody(config.fields, form);
      if (editing) await api.update(editing.id, body);
      else await api.create(body);
      setOpen(false);
      await load();
    } catch (err) {
      setFormError(String(err.message || err));
    } finally {
      setSaving(false);
    }
  }

  async function remove(row) {
    if (!confirm(`¿Eliminar este ${config.singular}?`)) return;
    try {
      await api.remove(row.id);
      await load();
    } catch (e) {
      alert(String(e.message || e));
    }
  }

  return (
    <div>
      <div className="page-head">
        <h1>{config.title}</h1>
        <button className="btn" onClick={openNew}>+ Nuevo</button>
      </div>

      {config.help && <p className="help">{config.help}</p>}

      {config.search && (
        <div className="toolbar">
          <input
            className="search"
            placeholder="Buscar…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load()}
          />
          <button className="btn ghost sm" onClick={load}>Buscar</button>
        </div>
      )}

      {error && <p className="err">{error}</p>}

      <div className="card">
        <table className="data">
          <thead>
            <tr>
              {config.numbered && <th style={{ width: 44, textAlign: "right", color: "var(--muted)" }}>#</th>}
              {config.columns.map((c) => (
                <th key={c.key}>{c.label}</th>
              ))}
              <th style={{ textAlign: "right" }}>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={config.columns.length + (config.numbered ? 2 : 1)} className="msg">Cargando…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={config.columns.length + (config.numbered ? 2 : 1)} className="msg">Sin registros.</td></tr>
            ) : (
              items.map((row, i) => (
                <tr key={row.id}>
                  {config.numbered && <td style={{ textAlign: "right", color: "var(--muted)", fontVariantNumeric: "tabular-nums" }}>{i + 1}</td>}
                  {config.columns.map((c) => (
                    <td key={c.key}>{renderCell(c, row)}</td>
                  ))}
                  <td>
                    <div className="row-actions">
                      <button className="btn ghost sm" onClick={() => openEdit(row)}>Editar</button>
                      <button className="btn danger sm" onClick={() => remove(row)}>Borrar</button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {open && (
        <div className="overlay" onClick={() => setOpen(false)}>
          <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={save}>
            <h2>{editing ? "Editar" : "Nuevo"} {config.singular}</h2>
            {config.fields.map((fl) => (
              <Field
                key={fl.name}
                field={fl}
                value={form[fl.name]}
                options={fkOptions[fl.name] || []}
                onChange={(v) => setForm((f) => ({ ...f, [fl.name]: v }))}
              />
            ))}
            {formError && <p className="err">{formError}</p>}
            <div className="actions">
              <button type="button" className="btn ghost" onClick={() => setOpen(false)}>Cancelar</button>
              <button type="submit" className="btn" disabled={saving}>
                {saving ? "Guardando…" : "Guardar"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

function renderCell(col, row) {
  const v = row[col.key];
  if (col.render) return col.render(v, row);
  if (col.type === "bool") return <span className={`pill ${v ? "yes" : "no"}`}>{v ? "Sí" : "No"}</span>;
  return v ?? "—";
}

function Field({ field, value, options, onChange }) {
  if (field.type === "bool") {
    return (
      <label className="check">
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
        {field.label}
      </label>
    );
  }
  if (field.type === "fk") {
    return (
      <label className="field">
        <span>{field.label}</span>
        <select value={value ?? ""} onChange={(e) => onChange(e.target.value)} required={field.required}>
          <option value="">—</option>
          {options.map((o) => (
            <option key={o.id} value={o.id}>{field.optionLabel(o)}</option>
          ))}
        </select>
      </label>
    );
  }
  if (field.type === "select") {
    return (
      <label className="field">
        <span>{field.label}</span>
        <select value={value ?? ""} onChange={(e) => onChange(e.target.value)} required={field.required}>
          <option value="">—</option>
          {field.options.map((o) => (
            <option key={String(o.value)} value={o.value}>{o.label}</option>
          ))}
        </select>
      </label>
    );
  }
  if (field.type === "textarea") {
    return (
      <label className="field">
        <span>{field.label}</span>
        <textarea
          rows={4}
          value={value ?? ""}
          required={field.required}
          onChange={(e) => onChange(e.target.value)}
        />
      </label>
    );
  }
  if (field.type === "mfk") {
    const sel = Array.isArray(value) ? value.map(Number) : [];
    const toggle = (id) =>
      onChange(sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]);
    return (
      <div className="field">
        <span>{field.label}</span>
        <div className="mfk">
          {options.length === 0 ? <span className="msg">Sin opciones.</span> :
            options.map((o) => (
              <label key={o.id} className="mfk-opt">
                <input type="checkbox" checked={sel.includes(Number(o.id))} onChange={() => toggle(Number(o.id))} />
                {field.optionLabel(o)}
              </label>
            ))}
        </div>
        {field.help && <small className="mfk-help">{field.help}</small>}
      </div>
    );
  }
  const inputType =
    field.type === "number" ? "number" :
    field.type === "date" ? "date" :
    field.type === "time" ? "time" : "text";
  return (
    <label className="field">
      <span>{field.label}</span>
      <input
        type={inputType}
        value={value ?? ""}
        required={field.required}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
