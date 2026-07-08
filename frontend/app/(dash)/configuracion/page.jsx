"use client";

import { useEffect, useState } from "react";
import { getConfig, saveConfig } from "../../../lib/api";

const NUM_FIELDS = [
  ["peso_asignacion", "Peso · que todos jueguen", "Prioridad dominante. Cuanto más alto, antes repite pareja que dejar a alguien fuera."],
  ["peso_central", "Peso · priorizar pistas GTennis", "Bonus por cada jugador asignado a pista central. Más alto = llena GTennis antes de usar satélites."],
  ["peso_satelite", "Peso · evitar satélites", "Penalización por usar pistas satélite. Más alto = se usan solo si hace falta."],
  ["peso_repeticion", "Peso · antirrepetición", "Penalización por repetir pareja. Más alto = más rotación."],
  ["max_dias_misma_pista", "Máx. días misma pista", "A partir de estas repeticiones en la semana, se penaliza fuerte."],
  ["time_limit_s", "Límite del solver (s)", "Tiempo máximo de cálculo por turno."],
];

export default function ConfiguracionPage() {
  const [cfg, setCfg] = useState(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getConfig().then(setCfg).catch((e) => setError(String(e.message || e)));
  }, []);

  async function onSave(e) {
    e.preventDefault();
    setSaving(true);
    setMsg(null);
    setError(null);
    try {
      const saved = await saveConfig({
        ...cfg,
        peso_asignacion: Number(cfg.peso_asignacion),
        peso_central: Number(cfg.peso_central),
        peso_satelite: Number(cfg.peso_satelite),
        peso_repeticion: Number(cfg.peso_repeticion),
        max_dias_misma_pista: Number(cfg.max_dias_misma_pista),
        time_limit_s: Number(cfg.time_limit_s),
        aplicar_vecindad: !!cfg.aplicar_vecindad,
      });
      setCfg(saved);
      setMsg("Guardado. Se aplicará en la próxima generación del cuadrante.");
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setSaving(false);
    }
  }

  if (error && !cfg) return <p className="err">{error}</p>;
  if (!cfg) return <p className="msg">Cargando configuración…</p>;

  return (
    <div>
      <div className="page-head"><h1>Criterios del motor</h1></div>
      <p className="help">
        Las <b>restricciones duras</b> (vecindad de división, vetos, capacidad) no se rompen nunca.
        Las <b>blandas</b> son preferencias: aquí ajustas su <b>peso = prioridad</b>. El motor
        elige la combinación que maximiza la suma. Cambia un número y dale a guardar — sin tocar código.
      </p>

      <form className="card" style={{ padding: 24, maxWidth: 560 }} onSubmit={onSave}>
        {NUM_FIELDS.map(([key, label, hint]) => (
          <label className="field" key={key}>
            <span>{label}</span>
            <input
              type="number"
              value={cfg[key]}
              onChange={(e) => setCfg({ ...cfg, [key]: e.target.value })}
            />
            <span style={{ marginTop: 6, fontSize: 11 }}>{hint}</span>
          </label>
        ))}

        <label className="check">
          <input
            type="checkbox"
            checked={!!cfg.aplicar_vecindad}
            onChange={(e) => setCfg({ ...cfg, aplicar_vecindad: e.target.checked })}
          />
          Aplicar regla de vecindad de división (N±1)
        </label>

        {msg && <p style={{ color: "var(--st-disponible)", fontSize: 13 }}>{msg}</p>}
        {error && <p className="err">{error}</p>}
        <div className="actions">
          <button className="btn" disabled={saving}>{saving ? "Guardando…" : "Guardar criterios"}</button>
        </div>
      </form>
    </div>
  );
}
