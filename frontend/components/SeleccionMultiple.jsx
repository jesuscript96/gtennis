"use client";

// Desplegable de selección múltiple (26/11/2026, filtro de circuitos del
// calendario de torneos): casillas, buscador si hay muchas opciones, cuántos
// hay de cada una y «Limpiar». Sin nada marcado = todos.

import { useEffect, useMemo, useRef, useState } from "react";

const sinTildes = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

export default function SeleccionMultiple({ opciones, valores, onChange, todos = "Todos", plural = "elegidos" }) {
  const [abierto, setAbierto] = useState(false);
  const [q, setQ] = useState("");
  const caja = useRef(null);
  const buscar = useRef(null);

  useEffect(() => {
    if (!abierto) return undefined;
    const fuera = (e) => { if (caja.current && !caja.current.contains(e.target)) setAbierto(false); };
    const tecla = (e) => { if (e.key === "Escape") setAbierto(false); };
    document.addEventListener("mousedown", fuera);
    document.addEventListener("touchstart", fuera);
    document.addEventListener("keydown", tecla);
    // En el móvil no: sacaría el teclado tapando la lista.
    if (window.matchMedia?.("(pointer: fine)").matches) buscar.current?.focus();
    return () => {
      document.removeEventListener("mousedown", fuera);
      document.removeEventListener("touchstart", fuera);
      document.removeEventListener("keydown", tecla);
    };
  }, [abierto]);
  useEffect(() => { if (!abierto) setQ(""); }, [abierto]);

  const vistas = useMemo(() => {
    const t = sinTildes(q.trim());
    return t ? opciones.filter((o) => sinTildes(o.etiqueta).includes(t)) : opciones;
  }, [opciones, q]);

  const marcado = (v) => valores.includes(v);
  const alternar = (v) => onChange(marcado(v) ? valores.filter((x) => x !== v) : [...valores, v]);

  let texto = todos;
  if (valores.length === 1) texto = valores[0];
  else if (valores.length === 2) texto = `${valores[0]} y ${valores[1]}`;
  else if (valores.length > 2) texto = `${valores.length} ${plural}`;

  return (
    <div className={`selmul${abierto ? " abierto" : ""}${valores.length ? " con-valor" : ""}`} ref={caja}>
      <button type="button" className="selmul-boton" aria-haspopup="listbox" aria-expanded={abierto}
        onClick={() => setAbierto((a) => !a)} title={valores.join(", ")}>
        <span className="selmul-texto">{texto}</span>
        {valores.length > 0 && <span className="selmul-n">{valores.length}</span>}
        <svg className="selmul-flecha" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {abierto && (
        <div className="selmul-panel" role="listbox" aria-multiselectable="true">
          {opciones.length > 7 && (
            <input ref={buscar} className="selmul-buscar" placeholder="Buscar…" value={q} onChange={(e) => setQ(e.target.value)} />
          )}
          <div className="selmul-lista">
            {vistas.map((o) => (
              <label key={o.valor} className={`selmul-op${marcado(o.valor) ? " si" : ""}`} role="option" aria-selected={marcado(o.valor)}>
                <input type="checkbox" checked={marcado(o.valor)} onChange={() => alternar(o.valor)} />
                <span className="selmul-caja" aria-hidden="true">
                  <svg width="11" height="11" viewBox="0 0 12 12"><path d="M2.5 6.2 5 8.6l4.6-5.2" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                </span>
                <span className="selmul-etq">{o.etiqueta}</span>
                {o.n != null && <span className="selmul-cuenta">{o.n}</span>}
              </label>
            ))}
            {!vistas.length && <p className="selmul-nada">Nada con «{q}».</p>}
          </div>
          <div className="selmul-pie">
            <button type="button" className="selmul-limpiar" disabled={!valores.length} onClick={() => onChange([])}>
              Limpiar{valores.length ? ` (${valores.length})` : ""}
            </button>
            <button type="button" className="btn sm" onClick={() => setAbierto(false)}>Listo</button>
          </div>
        </div>
      )}
    </div>
  );
}
