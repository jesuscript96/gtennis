"use client";

import { useEffect, useState } from "react";
import { getPersonal, guardarFuncion, guardarPerfil } from "../../../lib/api";

// Club → Personas y funciones (10/11/2026). Dirección asigna a cada persona su
// perfil y las funciones que le tocan, sin tocar el programa. Dirección tiene
// todas las funciones sin marcarlas.
const AYUDA = {
  TOCA_CUADRANTE: "Mueve el cuadrante a mano, lo rehace, lo deshace y lo publica.",
  APRUEBA_INVITADOS: "Mete invitados y aprueba sus días. Cuenta como dirección para los invitados.",
  COORDINA_TARDES: "Reparte los jugadores de Competición de tardes, da altas y bajas del equipo y recibe el aviso de validar.",
  VALIDA_INFORMES: "Aprueba, corrige o devuelve informes. Abre y corrige las dos partes.",
  ENVIA_INFORMES: "Envía a las familias los informes aprobados.",
  TARDES_TENIS: "Hace la parte de tenis de los informes de tardes que le reparten.",
  TARDES_FISICO: "Hace la parte física de los informes de tardes.",
};

export default function FuncionesPage() {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState(null);
  const [guardando, setGuardando] = useState(null);
  const [filtro, setFiltro] = useState("");

  useEffect(() => {
    getPersonal().then(setDatos).catch((e) => setError(String(e.message || e)));
  }, []);

  function reemplaza(p) {
    setDatos((d) => ({ ...d, personas: d.personas.map((x) => (x.id === p.id ? p : x)) }));
  }

  async function toggle(persona, codigo, activa) {
    setGuardando(`${persona.id}-${codigo}`);
    try { reemplaza(await guardarFuncion(persona.id, codigo, activa)); }
    catch (e) { alert(String(e.message || e)); }
    finally { setGuardando(null); }
  }

  async function cambiaPerfil(persona, role) {
    if (!confirm(`¿Cambiar el perfil de ${persona.nombre}?`)) return;
    try { reemplaza(await guardarPerfil(persona.id, role)); }
    catch (e) { alert(String(e.message || e)); }
  }

  if (error) return <p className="err">{error}</p>;
  if (!datos) return <p className="msg">Cargando…</p>;

  const marcada = (p, codigo) => (codigo.startsWith("TARDES_")
    ? p.tardes.includes(codigo.replace("TARDES_", ""))
    : p.funciones.includes(codigo));
  const personas = datos.personas.filter((p) =>
    `${p.nombre} ${p.username}`.toLowerCase().includes(filtro.trim().toLowerCase()));

  return (
    <div>
      <div className="page-head"><h1>Personas y funciones</h1></div>
      <p className="help">
        El perfil decide lo que cada uno ve. Las funciones añaden tareas concretas a una persona.
        Dirección las tiene todas. Los cambios se notan en la siguiente pantalla que abra esa persona.
      </p>
      <details className="help" style={{ marginBottom: 16 }}>
        <summary>Qué hace cada función</summary>
        <ul>
          {datos.funciones.map((f) => <li key={f.codigo}><b>{f.nombre}:</b> {AYUDA[f.codigo]}</li>)}
        </ul>
      </details>
      <input className="search" placeholder="Buscar persona…" value={filtro}
             onChange={(e) => setFiltro(e.target.value)} style={{ marginBottom: 12, maxWidth: 320 }} />
      <div className="card" style={{ overflowX: "auto" }}>
        <table className="data funciones">
          <thead>
            <tr>
              <th>Persona</th>
              <th>Perfil</th>
              {datos.funciones.map((f) => <th key={f.codigo} title={AYUDA[f.codigo]}>{f.nombre}</th>)}
            </tr>
          </thead>
          <tbody>
            {personas.map((p) => (
              <tr key={p.id}>
                <td data-label="Persona"><b>{p.nombre}</b><div className="muted" style={{ fontSize: 12 }}>{p.username}</div></td>
                <td data-label="Perfil">
                  <select value={p.role} onChange={(e) => cambiaPerfil(p, e.target.value)}>
                    {datos.perfiles.map((r) => <option key={r.role} value={r.role}>{r.nombre}</option>)}
                  </select>
                </td>
                {datos.funciones.map((f) => (
                  <td key={f.codigo} data-label={f.nombre} style={{ textAlign: "center" }}>
                    {p.perfil === "direccion" && !f.codigo.startsWith("TARDES_")
                      ? <span className="muted" title="Dirección las tiene todas">✓</span>
                      : <input type="checkbox" aria-label={`${f.nombre} · ${p.nombre}`}
                               checked={marcada(p, f.codigo)}
                               disabled={guardando === `${p.id}-${f.codigo}`}
                               onChange={(e) => toggle(p, f.codigo, e.target.checked)} />}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
