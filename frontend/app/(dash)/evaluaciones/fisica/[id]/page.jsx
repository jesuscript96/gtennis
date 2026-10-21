"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import AsistenteFisico from "../../../../../components/AsistenteFisico";
import { borrarEvaluacionFisica, getCatalogoFisico, getEvaluacionFisica, getUser } from "../../../../../lib/api";
import { fmtLarga } from "../../../../../lib/torneos";

function Informe({ ev, catalogo }) {
  const etiqueta = (n) => catalogo.escala.find((e) => e.valor === n)?.etiqueta || "";
  return (
    <div className="eval-informe">
      {catalogo.bloques.map((b) => {
        const notas = b.criterios.map((c) => ev.puntuaciones[c.clave]).filter(Boolean);
        const media = notas.length ? (notas.reduce((a, x) => a + x, 0) / notas.length).toFixed(1).replace(".", ",") : "—";
        return (
          <section key={b.clave} className="card eval-informe-bloque">
            <h2>{b.titulo} <span className="fis-media">{media} / 5</span></h2>
            <ul>
              {b.criterios.map((c) => (
                <li key={c.clave}>
                  <span>{c.etiqueta}</span>
                  <span className="eval-puntos" aria-label={`${ev.puntuaciones[c.clave] ?? "—"} de 5, ${etiqueta(ev.puntuaciones[c.clave])}`}>
                    {[1, 2, 3, 4, 5].map((n) => <i key={n} className={n <= (ev.puntuaciones[c.clave] || 0) ? "on" : ""} />)}
                    <b>{ev.puntuaciones[c.clave] ?? "—"}</b>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
      <section className="card eval-informe-bloque">
        {catalogo.textos.map((t) => (
          <div key={t.clave} className="fis-obs">
            <h2>{t.etiqueta}</h2>
            <p className={ev.textos[t.clave] ? "" : "eval-nota"}>{ev.textos[t.clave] || "Sin observaciones"}</p>
          </div>
        ))}
      </section>
    </div>
  );
}

export default function EvaluacionFisicaPage() {
  const { id } = useParams();
  const router = useRouter();
  const [ev, setEv] = useState(null);
  const [catalogo, setCatalogo] = useState(null);
  const [editando, setEditando] = useState(false);
  const [confirmar, setConfirmar] = useState(false);
  const [error, setError] = useState("");
  const volver = getUser()?.is_preparador ? "/evaluaciones" : "/evaluaciones?tipo=fisico";

  useEffect(() => {
    Promise.all([getEvaluacionFisica(id), getCatalogoFisico()])
      .then(([e, c]) => { setEv(e); setCatalogo(c); setEditando(e.estado === "BORRADOR" && e.puede_editar); })
      .catch((e) => setError(e.message));
  }, [id]);

  async function borrar() {
    try { await borrarEvaluacionFisica(id); router.push(volver); } catch (e) { setError(e.message); }
  }

  if (error && !ev) return <p className="err">{error}</p>;
  if (!ev || !catalogo) return <p className="msg">Cargando…</p>;

  return (
    <div>
      <div className="page-head">
        <h1>{ev.jugador_nombre}<span className="h1-sub"> · físico</span></h1>
        <Link href={volver} className="btn ghost sm">Todas las evaluaciones</Link>
      </div>

      {editando ? (
        <AsistenteFisico evaluacion={ev} catalogo={catalogo}
          pasoInicio={ev.estado === "TERMINADA" ? 0 : undefined}
          onCambio={setEv} onTerminada={(e) => { setEv(e); setEditando(false); }} />
      ) : (
        <>
          <p className="eval-cabecera">
            {fmtLarga(ev.fecha)} · evaluado por <b>{ev.nombre_evaluador}</b>
            {ev.estado === "BORRADOR" && <span className="pill pend"> A medias · {ev.puntuados}/11</span>}
          </p>
          <div className="eval-acciones">
            {ev.puede_editar && <button type="button" className="btn" onClick={() => setEditando(true)}>
              {ev.estado === "BORRADOR" ? "Seguir" : "Editar"}</button>}
            {ev.puede_editar && !confirmar && (
              <button type="button" className="btn danger" onClick={() => setConfirmar(true)}>Borrar</button>
            )}
            {confirmar && (
              <span className="fis-confirmar">
                ¿Borrar esta evaluación?
                <button type="button" className="btn danger sm" onClick={borrar}>Sí, borrar</button>
                <button type="button" className="btn ghost sm" onClick={() => setConfirmar(false)}>No</button>
              </span>
            )}
          </div>
          {error && <p className="err">{error}</p>}
          <Informe ev={ev} catalogo={catalogo} />
        </>
      )}
    </div>
  );
}
