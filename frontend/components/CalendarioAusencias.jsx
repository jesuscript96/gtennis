"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  addAusenciaFechas, addPreferenciaSuperficie, delAusenciaFechas,
  delPreferenciaSuperficie, getAusenciasFechas, getPreferenciasSuperficie,
  getUser,
} from "../lib/api";
import { roleRank } from "../lib/perms";
import { ESTADO_COLOR, SUPERFICIE_COLOR } from "../lib/format";

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
const cuando = (a) => (a.fecha_fin !== a.fecha_inicio
  ? `del ${fmtCorta(a.fecha_inicio)} al ${fmtCorta(a.fecha_fin)}`
  : `del ${fmtCorta(a.fecha_inicio)}`);

// Lo que se declara, en el idioma de quien lo declara. Para el alumno, por
// dentro son el estado y el subtipo de la matriz de estados.
export const MOTIVOS_JUGADOR = [
  { value: "LESION", label: "Lesión", estado: "AUSENCIA_JUGADOR", subtipo: "LESION" },
  { value: "ENFERMEDAD", label: "Enfermedad", estado: "AUSENCIA_JUGADOR", subtipo: "ENFERMEDAD" },
  { value: "ESTUDIOS", label: "Estudios", estado: "AUSENCIA_JUGADOR", subtipo: "ESTUDIOS" },
  { value: "PRUEBA_MEDICA", label: "Prueba médica", estado: "AUSENCIA_JUGADOR", subtipo: "PRUEBA_MEDICA" },
  { value: "VACACIONES", label: "Vacaciones", estado: "AUSENCIA_JUGADOR", subtipo: "VACACIONES" },
  { value: "TORNEO", label: "Torneo", estado: "EN_TORNEO", subtipo: "" },
  { value: "OTRO", label: "Otro", estado: "AUSENCIA_JUGADOR", subtipo: "" },
  // No son faltas: viene, pero esos días entrena en esa superficie (preparar
  // un torneo en rápida, por ejemplo). Van a su propio modelo y el motor no
  // le pone en otra.
  { value: "SUP_TIERRA", label: "Entrena en tierra", superficie: "TIERRA" },
  { value: "SUP_RESINA", label: "Entrena en resina", superficie: "RESINA" },
];
export const MOTIVOS_ENTRENADOR = [
  { value: "VACACIONES", label: "Vacaciones" },
  { value: "TORNEO", label: "Torneo" },
  { value: "FORMACION", label: "Formación" },
  { value: "ENFERMEDAD", label: "Enfermedad" },
  { value: "PERSONAL", label: "Asunto personal" },
  { value: "OTRO", label: "Otro" },
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
// Qué franjas tapa cada opción: marcar «Toda la mañana» deja sin sentido M1 y
// M2 sueltas, y al revés.
const CUBRE = {
  DIA: ["MANANA", "TARDE", "M1", "M2", "T1", "T2"],
  MANANA: ["M1", "M2"], TARDE: ["T1", "T2"],
  M1: ["MANANA"], M2: ["MANANA"], T1: ["TARDE"], T2: ["TARDE"],
};

// Marcar o desmarcar una franja. Se pueden elegir varias («M1 y T1»); el día
// entero va solo, y un bloque sustituye a sus franjas sueltas. Nunca se queda
// vacío: sin nada marcado vuelve a «Todo el día».
export function alternarAmbito(actuales, valor) {
  if (actuales.includes(valor)) {
    const resto = actuales.filter((a) => a !== valor);
    return resto.length ? resto : ["DIA"];
  }
  if (valor === "DIA") return ["DIA"];
  const fuera = new Set(["DIA", ...(CUBRE[valor] || [])]);
  return [...actuales.filter((a) => !fuera.has(a)), valor];
}

const SUBTIPO_CORTO = {
  LESION: "lesión", ENFERMEDAD: "enfermedad", ESTUDIOS: "estudios",
  PRUEBA_MEDICA: "prueba médica", VACACIONES: "vacaciones", MILONGA: "milonga",
};

// De dónde salen las faltas de un alumno y cómo se escriben. Junto a ellas,
// la superficie que tiene declarada por fechas: se pinta en el mismo
// calendario, con el día entero (la superficie no va por franjas).
function fuenteDeJugador(jugador) {
  return {
    clave: `jugador-${jugador.id}`,
    cargar: async () => {
      const [faltas, prefs] = await Promise.all([
        getAusenciasFechas(jugador.id), getPreferenciasSuperficie(jugador.id),
      ]);
      // La superficie fija de la ficha (sin fechas) no se pinta: cubriría
      // todos los días y taparía las faltas.
      const conFechas = prefs
        .filter((p) => p.fecha_desde && p.fecha_hasta)
        .map((p) => ({
          ...p, id: `sup-${p.id}`, prefId: p.id, esSuperficie: true,
          fecha_inicio: p.fecha_desde, fecha_fin: p.fecha_hasta, ambito: "DIA",
        }));
      return [...faltas, ...conFechas]
        .sort((a, b) => (a.fecha_inicio < b.fecha_inicio ? 1 : -1));
    },
    crear: ({ desde, hasta, ambito, motivo, nota }) => (motivo.superficie
      ? addPreferenciaSuperficie({
        jugador: jugador.id, superficie: motivo.superficie,
        fecha_desde: desde, fecha_hasta: hasta, estricta: true,
      })
      : addAusenciaFechas({
        jugador: jugador.id, fecha_inicio: desde, fecha_fin: hasta, ambito,
        estado: motivo.estado, subtipo: motivo.subtipo, nota,
      })),
    borrar: (a) => (a.esSuperficie
      ? delPreferenciaSuperficie(a.prefId) : delAusenciaFechas(a.id)),
    describir: (a) => (a.esSuperficie
      ? `entrena en ${a.superficie === "RESINA" ? "resina" : "tierra"}`
      : [
        a.subtipo && SUBTIPO_CORTO[a.subtipo],
        a.estado === "EN_TORNEO" && "torneo",
        a.nota,
      ].filter(Boolean).join(" · ")),
    colorDe: (a) => (a.esSuperficie
      ? SUPERFICIE_COLOR[a.superficie] : ESTADO_COLOR[a.estado]) || "#999",
  };
}

/**
 * Las faltas sobre un calendario: de un alumno, o de un entrenador.
 *
 * Se marcan los días —uno, varios sueltos o arrastrando un rango—, se dice si
 * falta todo el día, un bloque o una franja y por qué, y se declara; y una vez
 * declarada se ve pintada en el mismo sitio donde se miró.
 *
 * Los días seguidos se guardan como UNA ausencia con ida y vuelta, que es como
 * lo entiende el motor; los sueltos, como una por tramo.
 *
 * Con `jugador` trabaja sobre las faltas de ese alumno. Para otra cosa —las del
 * entrenador en su agenda— se le pasa una `fuente` ({clave, cargar, crear,
 * borrar, describir, colorDe}) y sus `motivos`.
 */
export default function CalendarioAusencias({ jugador, fuente, motivos, onCambio }) {
  const origen = fuente || fuenteDeJugador(jugador);
  const lista = motivos || MOTIVOS_JUGADOR;
  // La superficie la declaran los coaches (01/10/2026); el entrenador solo
  // declara faltas y ve la superficie que le han puesto.
  const coach = roleRank(getUser()) >= 2;
  const conSuperficie = coach && lista.some((m) => m.superficie);
  const motivosFalta = lista.filter((m) => !m.superficie);
  const superficies = lista.filter((m) => m.superficie);
  // La fuente se rehace en cada render de quien la pasa: se lee de una ref y
  // se recarga solo cuando cambia su clave.
  const origenRef = useRef(origen);
  origenRef.current = origen;

  const hoy = new Date();
  const [mes, setMes] = useState(new Date(hoy.getFullYear(), hoy.getMonth(), 1));
  const [ausencias, setAusencias] = useState([]);
  // La selección manda desde una ref y se refleja en el estado. Leyéndola del
  // estado, dos clics seguidos en el mismo tick trabajan sobre la selección
  // vieja y el primero se pierde — y marcar días sueltos rápido es justo lo
  // que se hace aquí.
  const selRef = useRef(new Set());
  const [sel, setSel] = useState(() => new Set());
  const [ambitos, setAmbitos] = useState(["DIA"]);
  const [motivo, setMotivo] = useState(motivosFalta[0].value);
  const [nota, setNota] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const pintando = useRef(null);

  const cargar = useCallback(async () => {
    try {
      setAusencias(await origenRef.current.cargar());
    } catch (e) { setError(e.message); }
  }, [origen.clave]); // eslint-disable-line react-hooks/exhaustive-deps

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
    const m = lista.find((x) => x.value === motivo) || lista[0];
    setGuardando(true); setError(""); setInfo("");
    try {
      // Una falta por tramo y por franja marcada: el motor las lee de una en
      // una. La superficie va siempre al día entero.
      const franjas = m.superficie ? ["DIA"] : ambitos;
      let tardia = false;
      for (const [desde, hasta] of tramos(dias)) {
        for (const ambito of franjas) {
          const r = await origenRef.current.crear({ desde, hasta, ambito, motivo: m, nota });
          if (r?.tardia) tardia = true;
        }
      }
      // Pasado el corte (19:00; viernes 16:30 para el sábado) el cuadrante de
      // ese día ya no cambia solo.
      if (tardia) {
        setInfo("Guardada. Ese día ya estaba cerrado: el cuadrante no cambia, sale "
          + "tachado y se ha avisado a dirección y a su entrenador para moverlo a mano.");
      }
      marcar(new Set());
      setNota("");
      setAmbitos(["DIA"]);
      await cargar();
      onCambio?.();
    } catch (e) { setError(e.message); }
    setGuardando(false);
  }

  async function borrar(a) {
    if (!window.confirm(
      `¿Quitar ${a.esSuperficie ? "la superficie" : "la falta"} ${cuando(a)}?`
    )) return;
    setGuardando(true);
    try {
      await origenRef.current.borrar(a);
      await cargar();
      onCambio?.();
    } catch (e) { setError(e.message); }
    setGuardando(false);
  }

  // Rejilla del mes, empezando en lunes y completando la primera semana.
  const celdas = [];
  const primero = new Date(mes.getFullYear(), mes.getMonth(), 1);
  for (let i = 0; i < (primero.getDay() + 6) % 7; i++) celdas.push(null);
  const ultimo = new Date(mes.getFullYear(), mes.getMonth() + 1, 0).getDate();
  for (let d = 1; d <= ultimo; d++) {
    celdas.push(iso(new Date(mes.getFullYear(), mes.getMonth(), d)));
  }

  const mover = (n) => setMes(new Date(mes.getFullYear(), mes.getMonth() + n, 1));
  const isoHoy = iso(hoy);
  const ambitoDe = (a) => AMBITOS.find((x) => x.value === a.ambito);
  // Lo ya declarado en los días marcados: tocar un día con algo es la forma
  // natural de llegar a quitarlo, sobre todo en el móvil.
  const enLaMarca = ausencias.filter((a) =>
    [...sel].some((d) => a.fecha_inicio <= d && d <= a.fecha_fin));
  // Las pasadas no se quitan nunca y alargan la lista: van plegadas.
  const vigentes = ausencias.filter((a) => a.fecha_fin >= isoHoy)
    .sort((a, b) => (a.fecha_inicio < b.fecha_inicio ? -1 : 1));
  const pasadas = ausencias.filter((a) => a.fecha_fin < isoHoy);
  const queEs = (a) => (a.esSuperficie ? [origen.describir(a)]
    : [ambitoDe(a)?.corto || a.ambito || "día", origen.describir(a)])
    .filter(Boolean).join(" · ");
  const fila = (a) => (
    <li key={a.id}>
      <i className="punto" style={{ background: origen.colorDe(a) }} />
      <span className="texto">
        <span className="cuando">
          {fmtCorta(a.fecha_inicio)}
          {a.fecha_fin !== a.fecha_inicio && ` → ${fmtCorta(a.fecha_fin)}`}
        </span>
        <span className="que">{queEs(a)}</span>
        {a.tardia && <span className="tag-tardia">tras el corte</span>}
      </span>
      {(!a.esSuperficie || coach) && (
        <button type="button" className="btn danger sm quitar" disabled={guardando}
          onClick={() => borrar(a)}>
          {a.esSuperficie ? "Quitar superficie" : "Quitar falta"}
        </button>
      )}
    </li>
  );
  const motivoSel = lista.find((m) => m.value === motivo) || motivosFalta[0];
  const esSuperficie = Boolean(motivoSel.superficie);

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
                [ambitoDe(f)?.label || f.ambito, origen.describir(f)]
                  .filter(Boolean).join(" · ")
              ).join("\n") || undefined}
              onPointerDown={() => empezar(dia)}
              onPointerEnter={() => extender(dia)}>
              <span className="num">{deIso(dia).getDate()}</span>
              <span className="marcas">
                {faltas.slice(0, 3).map((f) => (
                  <i key={f.id} style={{ background: origen.colorDe(f) }}
                    className={f.esSuperficie ? "marca sup"
                      : !f.ambito || f.ambito === "DIA" ? "marca llena" : "marca"} />
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
          {ausencias.some((a) => a.esSuperficie) && <> ·
            <i className="marca sup" style={{ background: SUPERFICIE_COLOR.RESINA }} /> superficie</>}
        </p>
      )}

      {error && <p className="error">{error}</p>}
      {info && <p className="cal-info">{info}</p>}

      {sel.size > 0 ? (
        <div className="cal-declarar">
          <p className="cal-resumen">
            <b>{sel.size} día{sel.size === 1 ? "" : "s"}</b> marcado
            {sel.size === 1 ? "" : "s"}
            {tramos([...sel].sort()).length > 1 && ` en ${tramos([...sel].sort()).length} tramos`}
          </p>
          {enLaMarca.length > 0 && (
            <div className="cal-ya">
              <p className="cal-ya-tit">
                Ya tiene{sel.size === 1 ? " ese día" : " en esos días"}:
              </p>
              <ul className="cal-lista">{enLaMarca.map(fila)}</ul>
            </div>
          )}
          {conSuperficie && (
            <div className="cal-tipo" role="group" aria-label="Qué declaras">
              <button type="button" className={esSuperficie ? "chip" : "chip on"}
                aria-pressed={!esSuperficie}
                onClick={() => setMotivo(motivosFalta[0].value)}>Una falta</button>
              <button type="button" className={esSuperficie ? "chip on" : "chip"}
                aria-pressed={esSuperficie}
                onClick={() => setMotivo(superficies[0].value)}>Viene, en otra superficie</button>
            </div>
          )}
          <div className="fila-form">
            <label>{esSuperficie ? "Superficie" : "Motivo"}
              <select value={motivo} onChange={(e) => setMotivo(e.target.value)}>
                {(esSuperficie ? superficies : motivosFalta).map((m) =>
                  <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </label>
            {!esSuperficie && <>
              <label className="crece">Nota (opcional)
                <input value={nota} onChange={(e) => setNota(e.target.value)}
                  placeholder="Ej. vuelve el lunes" />
              </label>
            </>}
          </div>
          {!esSuperficie && (
            <div className="cal-ambitos" role="group" aria-label="Qué falta">
              <span className="cal-ambitos-tit">Falta <small>(puedes marcar varias)</small></span>
              {AMBITOS.map((a) => (
                <button key={a.value} type="button"
                  className={ambitos.includes(a.value) ? "chip on" : "chip"}
                  aria-pressed={ambitos.includes(a.value)}
                  onClick={() => setAmbitos((prev) => alternarAmbito(prev, a.value))}>
                  {a.label}
                </button>
              ))}
            </div>
          )}
          {esSuperficie && (
            <p className="hint">
              Esos días el motor solo le pone en pistas de {motivoSel.superficie === "RESINA"
                ? "resina" : "tierra"}, en todas sus sesiones.
            </p>
          )}
          <div className="cal-acciones">
            <button type="button" className="btn" disabled={guardando}
              onClick={declarar}>
              {guardando ? "Guardando…"
                : esSuperficie ? "Declarar la superficie" : "Declarar la falta"}
            </button>
            <button type="button" className="btn ghost sm"
              onClick={() => marcar(new Set())}>Quitar la marca</button>
          </div>
        </div>
      ) : (
        <p className="hint">
          Toca los días que falta —o arrastra para marcar varios— y di de qué va.
          Para quitar algo, toca su día o usa «Quitar» en la lista de abajo.
        </p>
      )}

      {vigentes.length > 0 && (
        <div className="cal-declaradas">
          <p className="cal-ya-tit">Declarado</p>
          <ul className="cal-lista">{vigentes.map(fila)}</ul>
        </div>
      )}
      {pasadas.length > 0 && (
        <details className="cal-pasadas">
          <summary>Ya pasadas ({pasadas.length})</summary>
          <ul className="cal-lista">{pasadas.map(fila)}</ul>
        </details>
      )}
    </div>
  );
}
