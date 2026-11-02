"use client";

import { useEffect, useState } from "react";
import { guardarEvaluacion, pulirComentario, terminarEvaluacion } from "../lib/api";
import { fmtLarga } from "../lib/torneos";

const COMPETICION = "competicion";

// 1-8: bloques · 9: competición · 10: el entrenador escribe fortalezas y
// mejoras · 11: cómo quedan pasadas a limpio. Desde el 02/11/2026 no se elige
// idioma: se evalúa siempre en español y el idioma de la familia solo cambia
// el PDF que se le envía.
const PASO_COMPETICION = 9;
const PASO_FRASES = 10;
const PASO_RESUMEN = 11;

export function pasoInicial(ev, bloques) {
  if (ev.estado === "TERMINADA") return PASO_RESUMEN;
  if (!ev.puntuados) return 1;
  const i = bloques.findIndex((b) => b.criterios.some((c) => !(c.clave in ev.puntuaciones)));
  return i === -1 ? PASO_COMPETICION : i + 1;
}

function Notas({ bloque, notas, onNota }) {
  return (
    <div className="eval-criterios">
      {bloque.criterios.map((c) => (
        <div key={c.clave} className="eval-criterio">
          <span className="eval-criterio-nombre" id={`lbl-${c.clave}`}>{c.etiqueta}</span>
          <div className="eval-notas" role="radiogroup" aria-labelledby={`lbl-${c.clave}`}>
            {[1, 2, 3, 4, 5].map((n) => (
              <button key={n} type="button" role="radio" aria-checked={notas[c.clave] === n}
                className={notas[c.clave] === n ? "activa" : ""} onClick={() => onNota(c.clave, n)}>
                {n}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * El asistente del Informe de Rendimiento, bloque a bloque. Cada «Siguiente»
 * guarda en el servidor lo de ese bloque, así que se puede dejar a medias y
 * seguir otro día. Si hay comentario nuevo, primero lo pule Claude y el
 * entrenador ve cómo queda antes de avanzar.
 */
export default function AsistenteEvaluacion({ evaluacion, bloques, ia, pasoInicio, onTerminada, onCambio }) {
  const [ev, setEv] = useState(evaluacion);
  const [paso, setPaso] = useState(pasoInicio ?? pasoInicial(evaluacion, bloques));
  const [notas, setNotas] = useState(evaluacion.puntuaciones);
  const [abierto, setAbierto] = useState(false);
  const [texto, setTexto] = useState("");
  const [pulido, setPulido] = useState("");
  const [revisando, setRevisando] = useState(false);
  const [fortalezas, setFortalezas] = useState(["", "", ""]);
  const [mejoras, setMejoras] = useState(["", "", ""]);
  const [misFortalezas, setMisFortalezas] = useState(["", "", ""]);
  const [misMejoras, setMisMejoras] = useState(["", "", ""]);
  const [ocupado, setOcupado] = useState("");
  const [error, setError] = useState("");
  const [avisos, setAvisos] = useState([]);
  const [hecho, setHecho] = useState("");

  const bloque = paso >= 1 && paso <= bloques.length ? bloques[paso - 1] : null;
  const clave = bloque ? bloque.clave : paso === PASO_COMPETICION ? COMPETICION : null;

  const actualizar = (nuevo) => { setEv(nuevo); onCambio?.(nuevo); };

  // Al entrar en un paso se carga lo que ya hubiera guardado de él.
  useEffect(() => {
    setError("");
    const com = clave ? ev.comentarios[clave] || {} : {};
    setTexto(com.original || "");
    setPulido(com.pulido || "");
    setRevisando(Boolean(com.pulido));
    setAbierto(Boolean(com.original) || paso === PASO_COMPETICION);
    const tres = (xs) => [0, 1, 2].map((i) => (xs || [])[i] || "");
    if (paso === PASO_FRASES) {
      setMisFortalezas(tres(ev.fortalezas_original));
      setMisMejoras(tres(ev.mejoras_original));
    }
    if (paso === PASO_RESUMEN) {
      setFortalezas(tres(ev.fortalezas));
      setMejoras(tres(ev.mejoras));
    }
    if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paso]);

  useEffect(() => {
    if (!hecho) return undefined;
    const t = setTimeout(() => setHecho(""), 2500);
    return () => clearTimeout(t);
  }, [hecho]);

  async function trabajo(etiqueta, fn) {
    setOcupado(etiqueta); setError("");
    try { return await fn(); } catch (e) { setError(e.message); return null; } finally { setOcupado(""); }
  }

  /** Guarda el comentario del paso. Devuelve true si se puede avanzar ya y
   *  false si hay que enseñar primero cómo lo ha dejado Claude. */
  async function guardarComentario(actual) {
    const com = actual.comentarios[clave] || {};
    const t = abierto ? texto.trim() : "";
    if (t && t !== (com.original || "").trim()) {
      const r = await pulirComentario(actual.id, clave, t);
      const nuevo = { ...actual, comentarios: { ...actual.comentarios, [clave]: r.comentario } };
      actualizar(nuevo);
      if (r.aviso) setAvisos([r.aviso]);
      if (!r.comentario.pulido) return true; // «No», «nada»…: sin observaciones
      if (!ia) return true; // sin IA no hay nada nuevo que revisar: se queda tal cual
      setPulido(r.comentario.pulido);
      setRevisando(true);
      return false;
    }
    if (!t && (com.original || com.pulido)) {
      actualizar(await guardarEvaluacion(actual.id, { comentarios: { [clave]: { original: "", pulido: "", idioma: "" } } }));
    } else if (t && revisando && pulido.trim() !== (com.pulido || "")) {
      actualizar(await guardarEvaluacion(actual.id, { comentarios: { [clave]: { pulido: pulido.trim() } } }));
    }
    return true;
  }

  async function siguienteBloque() {
    const faltan = bloque.criterios.filter((c) => !notas[c.clave]).map((c) => c.etiqueta);
    if (faltan.length) { setError(`Falta puntuar: ${faltan.join(", ")}.`); return; }
    await trabajo(ia && abierto && texto.trim() && !revisando ? "Puliendo el comentario…" : "Guardando…", async () => {
      const suyas = Object.fromEntries(bloque.criterios.map((c) => [c.clave, notas[c.clave]]));
      const actual = await guardarEvaluacion(ev.id, { puntuaciones: suyas });
      actualizar(actual);
      if (!(await guardarComentario(actual))) return;
      setHecho(`✅ ${bloque.confirmacion}`);
      setAvisos([]);
      setPaso(paso + 1);
    });
  }

  async function acabarCompeticion() {
    await trabajo(ia && abierto && texto.trim() && !revisando ? "Puliendo el comentario…" : "Guardando…", async () => {
      if (!(await guardarComentario(ev))) return;
      setAvisos([]);
      setPaso(PASO_FRASES);
    });
  }

  async function generar() {
    const limpias = (xs) => xs.map((x) => x.trim()).filter(Boolean);
    if (!limpias(misFortalezas).length || !limpias(misMejoras).length) {
      setError("Escribe al menos una fortaleza y un área de mejora.");
      return;
    }
    await trabajo(ia ? "Pasándolas a limpio…" : "Generando el informe…", async () => {
      const r = await terminarEvaluacion(ev.id, {
        fortalezas_original: limpias(misFortalezas), mejoras_original: limpias(misMejoras),
      });
      const { avisos: nuevos, ...nuevo } = r;
      actualizar(nuevo);
      setAvisos(nuevos || []);
      setPaso(PASO_RESUMEN);
    });
  }

  async function guardarResumen() {
    await trabajo("Guardando…", async () => {
      const nuevo = await guardarEvaluacion(ev.id, {
        fortalezas: fortalezas.map((f) => f.trim()).filter(Boolean),
        mejoras: mejoras.map((m) => m.trim()).filter(Boolean),
      });
      actualizar(nuevo);
      onTerminada?.(nuevo);
    });
  }

  const comentario = (habilidad) => (
    <div className="eval-comentario">
      {!abierto ? (
        <button type="button" className="btn ghost sm" onClick={() => setAbierto(true)}>
          + Añadir un comentario sobre {habilidad}
        </button>
      ) : (
        <>
          <label htmlFor="eval-texto">
            {paso === PASO_COMPETICION
              ? "¿Algún resultado en torneos recientes que quieras destacar? (opcional)"
              : `Comentario sobre ${habilidad} (opcional)`}
          </label>
          <textarea id="eval-texto" rows={4} value={texto}
            placeholder="Escribe o dicta con el micrófono del teclado…"
            onChange={(e) => { setTexto(e.target.value); setRevisando(false); }} />
          {revisando && (
            <div className="eval-pulido">
              <label htmlFor="eval-pulido">Así queda en el informe (puedes retocarlo):</label>
              <textarea id="eval-pulido" rows={4} value={pulido} onChange={(e) => setPulido(e.target.value)} />
            </div>
          )}
          {!ia && texto.trim() && !revisando && (
            <p className="eval-nota">La IA no está activada: el comentario se guardará tal como lo escribas.</p>
          )}
        </>
      )}
    </div>
  );

  const cabecera = (
    <p className="eval-cabecera">
      Informe: <b>{ev.jugador_nombre}</b> — {fmtLarga(ev.fecha)}
    </p>
  );

  // Avisos y errores pegados a los botones: en el móvil, debajo de la tarjeta no se ven.
  const mensajes = (
    <>
      {avisos.map((a) => <p key={a} className="eval-nota">{a}</p>)}
      {error && <p className="err" role="alert">{error}</p>}
    </>
  );

  const pie = (children) => (
    <div className="eval-pie">
      {paso > 1 && paso < PASO_RESUMEN && (
        <button type="button" className="btn ghost" disabled={!!ocupado} onClick={() => setPaso(paso - 1)}>Atrás</button>
      )}
      {children}
    </div>
  );

  return (
    <div className="eval-asistente">
      {cabecera}
      {paso >= 1 && paso <= PASO_FRASES && (
        <div className="eval-progreso" aria-label={`Paso ${paso} de ${PASO_FRASES}`}>
          {Array.from({ length: PASO_FRASES }, (_, i) => (
            <span key={i} className={i + 1 < paso ? "hecho" : i + 1 === paso ? "actual" : ""} />
          ))}
        </div>
      )}
      {hecho && <p className="eval-hecho" role="status">{hecho}</p>}

      {bloque && (
        <div className="card eval-paso">
          <h2>{bloque.titulo}</h2>
          <p className="eval-nota">Puntúa del 1 al 5.</p>
          <Notas bloque={bloque} notas={notas} onNota={(k, n) => setNotas((prev) => ({ ...prev, [k]: n }))} />
          {comentario(bloque.habilidad)}
          {mensajes}
          {pie(
            <button type="button" className="btn" disabled={!!ocupado} onClick={siguienteBloque}>
              {ocupado || (ia && abierto && texto.trim() && !revisando ? "Pulir y revisar" : "Siguiente")}
            </button>
          )}
        </div>
      )}

      {paso === PASO_COMPETICION && (
        <div className="card eval-paso">
          <h2>Último bloque 🏆</h2>
          {comentario("los torneos")}
          {mensajes}
          {pie(
            <button type="button" className="btn" disabled={!!ocupado} onClick={acabarCompeticion}>
              {ocupado || (ia && abierto && texto.trim() && !revisando ? "Pulir y revisar" : "Siguiente")}
            </button>
          )}
        </div>
      )}

      {paso === PASO_FRASES && (
        <div className="card eval-paso">
          <h2>Fortalezas y áreas de mejora</h2>
          <p className="eval-nota">
            Escribe hasta tres de cada (al menos una). Puedes dictarlas con el micrófono del teclado.
            {ia && " Al generar el informe, Claude las pasa a limpio sin cambiar lo que dices."}
          </p>
          {[["Fortalezas", misFortalezas, setMisFortalezas], ["Áreas de mejora", misMejoras, setMisMejoras]].map(([titulo, lista, set]) => (
            <fieldset key={titulo} className="eval-frases">
              <legend>{titulo}</legend>
              {lista.map((f, i) => (
                <input key={i} type="text" value={f} aria-label={`${titulo} ${i + 1}`}
                  onChange={(e) => set(lista.map((x, j) => (j === i ? e.target.value : x)))} />
              ))}
            </fieldset>
          ))}
          {mensajes}
          {pie(
            <button type="button" className="btn" disabled={!!ocupado} onClick={generar}>
              {ocupado || "Generar informe"}
            </button>
          )}
        </div>
      )}

      {paso === PASO_RESUMEN && (
        <div className="card eval-paso">
          <h2>Así quedan en el informe</h2>
          <p className="eval-nota">Tus fortalezas y áreas de mejora pasadas a limpio. Retócalas si hace falta.</p>
          {[["Fortalezas", fortalezas, setFortalezas], ["Áreas de mejora", mejoras, setMejoras]].map(([titulo, lista, set]) => (
            <fieldset key={titulo} className="eval-frases">
              <legend>{titulo}</legend>
              {lista.map((f, i) => (
                <input key={i} type="text" value={f} aria-label={`${titulo} ${i + 1}`}
                  onChange={(e) => set(lista.map((x, j) => (j === i ? e.target.value : x)))} />
              ))}
            </fieldset>
          ))}
          {mensajes}
          <div className="eval-pie">
            <button type="button" className="btn ghost" disabled={!!ocupado} onClick={() => setPaso(PASO_FRASES)}>Atrás</button>
            <button type="button" className="btn" disabled={!!ocupado} onClick={guardarResumen}>
              {ocupado || "Guardar informe"}
            </button>
          </div>
        </div>
      )}

    </div>
  );
}
