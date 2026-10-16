"use client";

import { useEffect, useState } from "react";
import { getTorneosEntrenadores } from "../lib/api";

const VACIO = {
  nombre: "", circuito: "", nivel: "", lugar: "", fecha_inicio: "", fecha_fin: "",
  cierre_inscripcion: "", qualy_inicio: "", qualy_fin: "", solo_fines_semana: false, estado: "VALIDADO", acompanantes: [], acompanante_nota: "", notas: "",
};

// Alta y edición de un torneo. `inicial` = el torneo a editar (o nada para
// crear). `circuitos` = los que ya existen, para la lista desplegable.
export default function TorneoForm({ inicial, circuitos = [], onGuardar, onCancelar, guardando, error }) {
  const [f, setF] = useState(() => ({
    ...VACIO, ...(inicial || {}), cierre_inscripcion: inicial?.cierre_inscripcion || "",
    qualy_inicio: inicial?.qualy_inicio || "", qualy_fin: inicial?.qualy_fin || "",
  }));
  const [entrenadores, setEntrenadores] = useState([]);
  useEffect(() => {
    // La misma lista que el desplegable «Acompaña» del calendario: todos los
    // entrenadores activos, no solo los del grupo de quien da el alta.
    getTorneosEntrenadores().then(setEntrenadores).catch(() => {});
  }, []);

  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));
  function toggleAcomp(id) {
    setF((s) => ({
      ...s,
      acompanantes: s.acompanantes.includes(id) ? s.acompanantes.filter((x) => x !== id) : [...s.acompanantes, id],
    }));
  }
  function submit(e) {
    e.preventDefault();
    const body = {
      ...f, cierre_inscripcion: f.cierre_inscripcion || null,
      qualy_inicio: f.qualy_inicio || null, qualy_fin: f.qualy_fin || null,
    };
    // Si no hay fecha fin, el torneo dura un día.
    if (!body.fecha_fin) body.fecha_fin = body.fecha_inicio;
    onGuardar(body);
  }

  return (
    <form className="card torneo-form" onSubmit={submit}>
      <div className="form-grid">
        <label className="field col-2"><span>Nombre del torneo</span>
          <input required value={f.nombre} onChange={set("nombre")} placeholder="Ej. ITF J60 La Nucía" />
        </label>
        <label className="field"><span>Circuito</span>
          <input list="circuitos" value={f.circuito} onChange={set("circuito")} placeholder="ITF Junior, MARCA, TTK Warriors…" />
          <datalist id="circuitos">{circuitos.map((c) => <option key={c} value={c} />)}</datalist>
        </label>
        <label className="field"><span>Nivel / categoría</span>
          <input value={f.nivel} onChange={set("nivel")} placeholder="J60, M25, Sub-16, Cadete…" />
        </label>
        <label className="field"><span>Lugar</span>
          <input value={f.lugar} onChange={set("lugar")} placeholder="Ciudad o club" />
        </label>
        <label className="field"><span>Estado</span>
          <select value={f.estado} onChange={set("estado")}>
            <option value="PROPUESTO">Propuesto (pendiente de validar)</option>
            <option value="VALIDADO">Validado</option>
            <option value="CANCELADO">Cancelado</option>
          </select>
        </label>
        <label className="field"><span>Empieza</span>
          <input type="date" required value={f.fecha_inicio} onChange={set("fecha_inicio")} />
        </label>
        <label className="field"><span>Termina</span>
          <input type="date" value={f.fecha_fin} min={f.fecha_inicio} onChange={set("fecha_fin")} />
        </label>
        <label className="field"><span>Cierre de inscripción</span>
          <input type="date" value={f.cierre_inscripcion} onChange={set("cierre_inscripcion")} />
        </label>
        <label className="field"><span>Previa desde (si tiene clasificación)</span>
          <input type="date" value={f.qualy_inicio} max={f.fecha_inicio || undefined} onChange={set("qualy_inicio")} />
        </label>
        <label className="field"><span>Previa hasta</span>
          <input type="date" value={f.qualy_fin} min={f.qualy_inicio || undefined} max={f.fecha_inicio || undefined}
            onChange={set("qualy_fin")} />
        </label>
        <label className="field check-campo">
          <input type="checkbox" checked={!!f.solo_fines_semana}
            onChange={(e) => setF((s) => ({ ...s, solo_fines_semana: e.target.checked }))} />
          <span>Solo se juega en fin de semana</span>
        </label>
        <div className="field col-2"><span>Coach que acompaña</span>
          <div className="chips-acomp">
            {entrenadores.map((e) => (
              <button type="button" key={e.id}
                className={`chip-acomp${f.acompanantes.includes(e.id) ? " on" : ""}`}
                onClick={() => toggleAcomp(e.id)}>{e.nombre}</button>
            ))}
          </div>
        </div>
        <label className="field col-2"><span>Nota sobre el acompañante (si no es un entrenador de la lista)</span>
          <input value={f.acompanante_nota} onChange={set("acompanante_nota")} placeholder="Ej. van solos · acompaña un padre · Ricardo" />
        </label>
        <label className="field col-3"><span>Notas (viaje, alojamiento, logística…)</span>
          <textarea rows={3} value={f.notas} onChange={set("notas")} />
        </label>
      </div>
      {error && <p className="err">{error}</p>}
      <div className="form-acciones">
        {onCancelar && <button type="button" className="btn ghost" onClick={onCancelar}>Cancelar</button>}
        <button className="btn" disabled={guardando}>{guardando ? "Guardando…" : inicial?.id ? "Guardar cambios" : "Crear torneo"}</button>
      </div>
    </form>
  );
}
