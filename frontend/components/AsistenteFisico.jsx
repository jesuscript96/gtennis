"use client";

import { useEffect, useState } from "react";
import { getEvaluacionFisicaAnterior, guardarEvaluacionFisica, terminarEvaluacionFisica } from "../lib/api";
import { leyendaFisico, tramoFisico } from "../lib/informes";
import { fmtLarga } from "../lib/torneos";

/**
 * La evaluación física paso a paso: un paso por bloque (notas con la escala
 * del club: del 1 al 10 en Alto rendimiento desde el 25/11/2026, del 1 al 5 en
 * tardes) y un último paso con las observaciones del preparador.
 * Cada «Siguiente» guarda en el servidor, así que se puede dejar a medias.
 */
export default function AsistenteFisico({ evaluacion, catalogo, pasoInicio, onCambio, onTerminada }) {
  const { bloques, textos } = catalogo;
  const maximo = evaluacion.escala || 5;
  const valores = Array.from({ length: maximo }, (_, i) => i + 1);
  const pasoTextos = bloques.length;
  const primerIncompleto = bloques.findIndex((b) => b.criterios.some((c) => !(c.clave in evaluacion.puntuaciones)));
  const [ev, setEv] = useState(evaluacion);
  const [paso, setPaso] = useState(pasoInicio ?? (primerIncompleto === -1 ? pasoTextos : primerIncompleto));
  const [notas, setNotas] = useState(evaluacion.puntuaciones);
  const [obs, setObs] = useState(() => Object.fromEntries(textos.map((t) => [t.clave, evaluacion.textos[t.clave] || ""])));
  const [ocupado, setOcupado] = useState("");
  const [error, setError] = useState("");
  const [hecho, setHecho] = useState("");
  // Lo evaluado antes de «empezar de cero» (19/11/2026): se enseña para consultarlo, nunca se aplica solo.
  const [antes, setAntes] = useState(null);
  useEffect(() => {
    getEvaluacionFisicaAnterior(evaluacion.jugador).then((r) => setAntes(r.anterior)).catch(() => {});
  }, [evaluacion.jugador]);

  const etiqueta = (n, esc = maximo) => tramoFisico(catalogo, n, esc);
  const actualizar = (nuevo) => { setEv(nuevo); onCambio?.(nuevo); };

  useEffect(() => {
    setError("");
    if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" });
  }, [paso]);
  useEffect(() => {
    if (!hecho) return undefined;
    const t = setTimeout(() => setHecho(""), 2500);
    return () => clearTimeout(t);
  }, [hecho]);

  async function trabajo(fn) {
    setOcupado("Guardando…"); setError("");
    try { return await fn(); } catch (e) { setError(e.message); return null; } finally { setOcupado(""); }
  }

  async function siguiente() {
    const b = bloques[paso];
    const faltan = b.criterios.filter((c) => !notas[c.clave]).map((c) => c.etiqueta);
    if (faltan.length) { setError(`Falta puntuar: ${faltan.join(", ")}.`); return; }
    await trabajo(async () => {
      const suyas = Object.fromEntries(b.criterios.map((c) => [c.clave, notas[c.clave]]));
      actualizar(await guardarEvaluacionFisica(ev.id, { puntuaciones: suyas }));
      setHecho(`✅ ${b.titulo}: guardado.`);
      setPaso(paso + 1);
    });
  }

  async function guardarTodo() {
    await trabajo(async () => {
      await guardarEvaluacionFisica(ev.id, { textos: obs });
      const fin = await terminarEvaluacionFisica(ev.id);
      actualizar(fin);
      onTerminada?.(fin);
    });
  }

  const mensajes = error && <p className="err" role="alert">{error}</p>;

  return (
    <div className="eval-asistente">
      <p className="eval-cabecera">
        Evaluación física: <b>{ev.jugador_nombre}</b> — {fmtLarga(ev.fecha)}
      </p>
      <div className="eval-progreso" aria-label={`Paso ${paso + 1} de ${pasoTextos + 1}`}>
        {Array.from({ length: pasoTextos + 1 }, (_, i) => (
          <span key={i} className={i < paso ? "hecho" : i === paso ? "actual" : ""} />
        ))}
      </div>
      {hecho && <p className="eval-hecho" role="status">{hecho}</p>}

      {paso < pasoTextos && (
        <div className="card eval-paso">
          <h2>{bloques[paso].titulo}</h2>
          <p className="eval-nota fis-escala">
            {leyendaFisico(catalogo, maximo).map((e) => <span key={e.valor}><b>{e.valor}</b> {e.etiqueta}</span>)}
          </p>
          <div className="eval-criterios">
            {bloques[paso].criterios.map((c) => (
              <div key={c.clave} className="eval-criterio fis-criterio">
                <div className="fis-texto">
                  <span className="eval-criterio-nombre" id={`lbl-${c.clave}`}>{c.etiqueta}
                    {antes?.puntuaciones?.[c.clave] ? (
                      <span className="eval-antes-nota" title={`Nota de la evaluación anterior (${fmtLarga(antes.fecha)})`}>
                        antes: {antes.puntuaciones[c.clave]}/{antes.escala || 5} · {etiqueta(antes.puntuaciones[c.clave], antes.escala || 5)}
                      </span>
                    ) : null}
                  </span>
                  <span className="fis-pregunta">{c.pregunta}</span>
                </div>
                <div className="fis-respuesta">
                  <div className={`eval-notas${maximo > 5 ? " diez" : ""}`} role="radiogroup" aria-labelledby={`lbl-${c.clave}`}>
                    {valores.map((n) => (
                      <button key={n} type="button" role="radio" aria-checked={notas[c.clave] === n}
                        title={etiqueta(n)} className={notas[c.clave] === n ? "activa" : ""}
                        onClick={() => setNotas((prev) => ({ ...prev, [c.clave]: n }))}>{n}</button>
                    ))}
                  </div>
                  <span className="fis-elegida">{notas[c.clave] ? etiqueta(notas[c.clave]) : "Sin puntuar"}</span>
                </div>
              </div>
            ))}
          </div>
          {mensajes}
          <div className="eval-pie">
            {paso > 0 && <button type="button" className="btn ghost" disabled={!!ocupado} onClick={() => setPaso(paso - 1)}>Atrás</button>}
            <button type="button" className="btn" disabled={!!ocupado} onClick={siguiente}>{ocupado || "Siguiente"}</button>
          </div>
        </div>
      )}

      {paso === pasoTextos && (
        <div className="card eval-paso">
          <h2>Observaciones del preparador físico</h2>
          <p className="eval-nota">Escríbelas o díctalas con el micrófono del teclado. Puedes dejar alguna en blanco.</p>
          {textos.map((t) => (
            <div key={t.clave} className="eval-comentario">
              {antes?.textos?.[t.clave]?.trim() && (
                <div className="eval-antes">
                  <span className="eval-antes-cab">Lo que se escribió antes ({fmtLarga(antes.fecha)} · {antes.evaluador})</span>
                  <p>{antes.textos[t.clave]}</p>
                  <button type="button" className="btn ghost sm"
                    onClick={() => setObs((o) => ({ ...o, [t.clave]: o[t.clave].trim() ? `${o[t.clave].trim()}\n${antes.textos[t.clave]}` : antes.textos[t.clave] }))}>
                    Copiar a mis observaciones
                  </button>
                </div>
              )}
              <label htmlFor={`fis-${t.clave}`}>{t.etiqueta}</label>
              <textarea id={`fis-${t.clave}`} rows={3} value={obs[t.clave]}
                onChange={(e) => setObs({ ...obs, [t.clave]: e.target.value })} />
            </div>
          ))}
          {mensajes}
          <div className="eval-pie">
            <button type="button" className="btn ghost" disabled={!!ocupado} onClick={() => setPaso(paso - 1)}>Atrás</button>
            <button type="button" className="btn" disabled={!!ocupado} onClick={guardarTodo}>{ocupado || "Guardar evaluación"}</button>
          </div>
        </div>
      )}
    </div>
  );
}
