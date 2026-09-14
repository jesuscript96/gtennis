"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  addAusenciaFechas, delAusenciaFechas, getAusenciasFechas,
} from "../lib/api";
import { ESTADO_COLOR } from "../lib/format";

const MESES = [
  "enero", "febrero", "marzo", "abril", "mayo", "junio",
  "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
];
const DIAS_CABECERA = ["L", "M", "X", "J", "V", "S", "D"];

// Fechas en local, nunca `new Date("2026-09-14")`: eso se interpreta en UTC y
// en España adelanta el día una hora, con lo que la ausencia del 16 se declara
// el 15.
const iso = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const deIso = (s) => {
  const [a, m, d] = s.split("-").map(Number);
  return new Date(a, m - 1, d);
};
const sumaDias = (s, n) => {
  const d = deIso(s);
  d.setDate(d.getDate() + n);
  return iso(d);
};
const fmtCorta = (s) => {
  const d = deIso(s);
  return `${d.getDate()} ${MESES[d.getMonth()].slice(0, 3)}`;
};

// Lo que se declara, en el idioma del entrenador. Por dentro son el estado y el
// subtipo de la matriz de estados.
const MOTIVOS = [
  { value: "LESION", label: "Lesión", estado: "AUSENCIA_JUGADOR", subtipo: "LESION" },
  { value: "ENFERMEDAD", label: "Enfermedad", estado: "AUSENCIA_JUGADOR", subtipo: "ENFERMEDAD" },
  { value: "ESTUDIOS", label: "Estudios", estado: "AUSENCIA_JUGADOR", subtipo: "ESTUDIOS" },
  { value: "PRUEBA_MEDICA", label: "Prueba médica", estado: "AUSENCIA_JUGADOR", subtipo: "PRUEBA_MEDICA" },
  { value: "VACACIONES", label: "Vacaciones", estado: "AUSENCIA_JUGADOR", subtipo: "VACACIONES" },
  { value: "TORNEO", label: "Torneo", estado: "EN_TORNEO", subtipo: "" },
  { value: "OTRO", label: "Otro", estado: "AUSENCIA_JUGADOR", subtipo: "" },
];
const AMBITOS = [
  { value: "DIA", label: "Todo el día", corto: "día" },
  { value: "MANANA", label: "Solo la mañana", corto: "mañana" },
  { value: "TARDE", label: "Solo la tarde", corto: "tarde" },
  { value: "M1", label: "Solo M1 · 8:30", corto: "M1" },
  { value: "M2", label: "Solo M2 · 10:30", corto: "M2" },
  { value: "T1", label: "Solo T1 · 14:15", corto: "T1" },
  { value: "T2", label: "Solo T2 · 15:30", corto: "T2" },
];

/**
 * Las faltas de un alumno sobre un calendario.
 *
 * Antes esto era un formulario con dos campos de fecha, y declarar "no viene
 * del 2 al 15" obligaba a leer el calendario en otro sitio y teclear dos
 * fechas. Aquí se marcan los días —uno, varios sueltos o arrastrando un
 * rango—, se dice de qué va la falta y se declara; y una vez declarada se ve
 * pintada en el mismo sitio donde se miró.
 *
 * Los días seguidos se guardan como UNA ausencia con ida y vuelta, que es como
 * lo entiende el motor; los sueltos, como una por tramo.
 */
export default function CalendarioAusencias({ jugador }) {
  const hoy = new Date();
  const [mes, setMes] = useState(new Date(hoy.getFullYear(), hoy.getMonth(), 1));
  const [ausencias, setAusencias] = useState([]);
  // La selección manda desde una ref y se refleja en el estado. Leyéndola del
  // estado, dos clics seguidos en el mismo tick trabajan sobre la selección
  // vieja y el primero se pierde — y marcar días sueltos rápido es justo lo
  // que se hace aquí.
  const selRef = useRef(new Set());
  const [sel, setSel] = useState(() => new Set());
  const [ambito, setAmbito] = useState("DIA");
  const [motivo, setMotivo] = useState("LESION");
  const [nota, setNota] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const pintando = useRef(null);

  const cargar = useCallback(async () => {
    try {
      setAusencias(await getAusenciasFechas(jugador.id));
    } catch (e) { setError(e.message); }
  }, [jugador.id]);

  useEffect(() => { cargar(); }, [cargar]);

  // Arrastrar para marcar varios días seguidos; se suelte donde se suelte.
  useEffect(() => {
    const fin = () => { pintando.current = null; };
    window.addEventListener("pointerup", fin);
    window.addEventListener("pointercancel", fin);
    return () => {
      window.removeEventListener("pointerup", fin);
      window.removeEventListener("pointercancel", fin);
    };
  }, []);

  const deLaFecha = (dia) =>
    ausencias.filter((a) => a.fecha_inicio <= dia && dia <= a.fecha_fin);

  const marcar = (nuevo) => { selRef.current = nuevo; setSel(nuevo); };

  function empezar(dia) {
    const previo = selRef.current;
    const siguiente = new Set(previo);
    const quitando = siguiente.has(dia);
    if (quitando) siguiente.delete(dia); else siguiente.add(dia);
    pintando.current = { ancla: dia, quitando, base: new Set(previo) };
    marcar(siguiente);
  }

  function extender(dia) {
    const p = pintando.current;
    if (!p) return;
    const siguiente = new Set(p.base);
    const [a, b] = p.ancla <= dia ? [p.ancla, dia] : [dia, p.ancla];
    for (let d = a; d <= b; d = sumaDias(d, 1)) {
      if (p.quitando) siguiente.delete(d); else siguiente.add(d);
    }
    marcar(siguiente);
  }

  // Días seguidos = una sola ausencia con ida y vuelta.
  function tramos(dias) {
    const out = [];
    let ini = null, prev = null;
    for (const d of dias) {
      if (ini === null) { ini = prev = d; continue; }
      if (sumaDias(prev, 1) === d) { prev = d; continue; }
      out.push([ini, prev]);
      ini = prev = d;
    }
    if (ini !== null) out.push([ini, prev]);
    return out;
  }

  async function declarar() {
    const dias = [...selRef.current].sort();
    if (!dias.length) return;
    const m = MOTIVOS.find((x) => x.value === motivo);
    setGuardando(true); setError("");
    try {
      for (const [desde, hasta] of tramos(dias)) {
        await addAusenciaFechas({
          jugador: jugador.id,
          fecha_inicio: desde, fecha_fin: hasta,
          ambito, estado: m.estado, subtipo: m.subtipo, nota,
        });
      }
      marcar(new Set());
      setNota("");
      await cargar();
    } catch (e) { setError(e.message); }
    setGuardando(false);
  }

  async function borrar(a) {
    if (!window.confirm(
      `¿Quitar la falta del ${fmtCorta(a.fecha_inicio)}` +
      `${a.fecha_fin !== a.fecha_inicio ? ` al ${fmtCorta(a.fecha_fin)}` : ""}?`
    )) return;
    setGuardando(true);
    try {
      await delAusenciaFechas(a.id);
      await cargar();
    } catch (e) { setError(e.message); }
    setGuardando(false);
  }

  // Rejilla del mes, empezando en lunes y completando la primera semana.
  const primero = new Date(mes.getFullYear(), mes.getMonth(), 1);
  const hueco = (primero.getDay() + 6) % 7;
  const celdas = [];
  for (let i = 0; i < hueco; i++) celdas.push(null);
  const ultimo = new Date(mes.getFullYear(), mes.getMonth() + 1, 0).getDate();
  for (let d = 1; d <= ultimo; d++) {
    celdas.push(iso(new Date(mes.getFullYear(), mes.getMonth(), d)));
  }

  const mover = (n) => setMes(new Date(mes.getFullYear(), mes.getMonth() + n, 1));
  const isoHoy = iso(hoy);

  return (
    <div className="calendario-ausencias">
      <div className="cal-head">
        <button type="button" className="cal-nav" onClick={() => mover(-1)}
          aria-label="Mes anterior">‹</button>
        <strong>{MESES[mes.getMonth()]} {mes.getFullYear()}</strong>
        <button type="button" className="cal-nav" onClick={() => mover(1)}
          aria-label="Mes siguiente">›</button>
      </div>

      <div className="cal-rejilla">
        {DIAS_CABECERA.map((d) => <span key={d} className="cal-dow">{d}</span>)}
        {celdas.map((dia, i) => {
          if (!dia) return <span key={`h${i}`} className="cal-dia vacio" />;
          const faltas = deLaFecha(dia);
          const domingo = (deIso(dia).getDay() === 0);
          return (
            <button key={dia} type="button"
              className={[
                "cal-dia",
                sel.has(dia) ? "sel" : "",
                dia === isoHoy ? "hoy" : "",
                domingo ? "domingo" : "",
                faltas.length ? "con-falta" : "",
              ].filter(Boolean).join(" ")}
              title={faltas.map((f) =>
                `${f.ambito === "DIA" ? "Todo el día" : AMBITOS.find((a) => a.value === f.ambito)?.label || f.ambito}` +
                `${f.subtipo ? ` · ${f.subtipo.toLowerCase()}` : ""}${f.nota ? ` · ${f.nota}` : ""}`
              ).join("\n") || undefined}
              onPointerDown={() => empezar(dia)}
              onPointerEnter={() => extender(dia)}>
              <span className="num">{deIso(dia).getDate()}</span>
              <span className="marcas">
                {faltas.slice(0, 3).map((f) => (
                  <i key={f.id} style={{ background: ESTADO_COLOR[f.estado] || "#999" }}
                    className={f.ambito === "DIA" ? "marca llena" : "marca"} />
                ))}
              </span>
            </button>
          );
        })}
      </div>

      {ausencias.length > 0 && (
        <p className="cal-leyenda">
          <i className="marca llena" /> todo el día ·
          <i className="marca" /> solo una parte
        </p>
      )}

      {error && <p className="error">{error}</p>}

      {sel.size > 0 ? (
        <div className="cal-declarar">
          <p className="cal-resumen">
            <b>{sel.size} día{sel.size === 1 ? "" : "s"}</b> marcado
            {sel.size === 1 ? "" : "s"}
            {tramos([...sel].sort()).length > 1 && ` en ${tramos([...sel].sort()).length} tramos`}
          </p>
          <div className="fila-form">
            <label>Falta
              <select value={ambito} onChange={(e) => setAmbito(e.target.value)}>
                {AMBITOS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
              </select>
            </label>
            <label>Motivo
              <select value={motivo} onChange={(e) => setMotivo(e.target.value)}>
                {MOTIVOS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </label>
            <label className="crece">Nota (opcional)
              <input value={nota} onChange={(e) => setNota(e.target.value)}
                placeholder="Ej. vuelve el lunes" />
            </label>
          </div>
          <div className="cal-acciones">
            <button type="button" className="btn" disabled={guardando}
              onClick={declarar}>
              {guardando ? "Guardando…" : "Declarar la falta"}
            </button>
            <button type="button" className="btn ghost sm"
              onClick={() => marcar(new Set())}>Quitar la marca</button>
          </div>
        </div>
      ) : (
        <p className="hint">
          Toca los días que falta —o arrastra para marcar varios— y di de qué va.
        </p>
      )}

      {ausencias.length > 0 && (
        <ul className="cal-lista">
          {ausencias.map((a) => (
            <li key={a.id}>
              <i className="punto" style={{ background: ESTADO_COLOR[a.estado] || "#999" }} />
              <span className="cuando">
                {fmtCorta(a.fecha_inicio)}
                {a.fecha_fin !== a.fecha_inicio && ` → ${fmtCorta(a.fecha_fin)}`}
              </span>
              <span className="que">
                {AMBITOS.find((x) => x.value === a.ambito)?.corto || a.ambito}
                {a.subtipo && ` · ${a.subtipo.toLowerCase().replace("_", " ")}`}
                {a.nota && ` · ${a.nota}`}
              </span>
              <button type="button" className="quitar" disabled={guardando}
                title="Quitar esta falta" onClick={() => borrar(a)}>✕</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
