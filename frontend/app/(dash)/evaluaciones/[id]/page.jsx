"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import AsistenteEvaluacion from "../../../../components/AsistenteEvaluacion";
import InformeDeLaEvaluacion from "../../../../components/InformeDeLaEvaluacion";
import {
  borrarEvaluacion, descargarPdfEvaluacion, getCatalogoEvaluacion, getEvaluacion, guardarEvaluacionEnDrive,
} from "../../../../lib/api";
import { fmtLarga } from "../../../../lib/torneos";

function Informe({ ev, bloques }) {
  const com = (clave) => (ev.comentarios[clave] || {}).pulido;
  return (
    <div className="eval-informe">
      {bloques.map((b) => (
        <section key={b.clave} className="card eval-informe-bloque">
          <h2>{b.titulo}</h2>
          <ul>
            {b.criterios.map((c) => (
              <li key={c.clave}>
                <span>{c.etiqueta}</span>
                <span className="eval-puntos" aria-label={`${ev.puntuaciones[c.clave] ?? "—"} de 5`}>
                  {[1, 2, 3, 4, 5].map((n) => <i key={n} className={n <= (ev.puntuaciones[c.clave] || 0) ? "on" : ""} />)}
                  <b>{ev.puntuaciones[c.clave] ?? "—"}</b>
                </span>
              </li>
            ))}
          </ul>
          <p className={com(b.clave) ? "" : "eval-nota"}>{com(b.clave) || "Sin observaciones"}</p>
        </section>
      ))}
      <section className="card eval-informe-bloque">
        <h2>Fortalezas</h2>
        {ev.fortalezas.length ? <ul className="eval-frases-lista">{ev.fortalezas.map((f) => <li key={f}>{f}</li>)}</ul>
          : <p className="eval-nota">Sin escribir.</p>}
        <h2>Áreas de mejora</h2>
        {ev.mejoras.length ? <ul className="eval-frases-lista">{ev.mejoras.map((m) => <li key={m}>{m}</li>)}</ul>
          : <p className="eval-nota">Sin escribir.</p>}
        <h2>Competición</h2>
        <p className={com("competicion") ? "" : "eval-nota"}>{com("competicion") || "Sin resultados registrados"}</p>
      </section>
    </div>
  );
}

export default function EvaluacionPage() {
  const { id } = useParams();
  const router = useRouter();
  const [ev, setEv] = useState(null);
  const [catalogo, setCatalogo] = useState(null);
  const [editando, setEditando] = useState(false);
  const [error, setError] = useState("");
  // null · "subiendo" · {aviso}: estado de la copia en la carpeta del jugador.
  const [drive, setDrive] = useState(null);

  useEffect(() => {
    Promise.all([getEvaluacion(id), getCatalogoEvaluacion()])
      .then(([e, c]) => {
        setEv(e); setCatalogo(c);
        setEditando(e.estado === "BORRADOR" && e.puede_editar);
      })
      .catch((e) => setError(e.message));
  }, [id]);

  async function descargar() {
    try {
      const f = await descargarPdfEvaluacion(id);
      const url = URL.createObjectURL(f.blob);
      const a = Object.assign(document.createElement("a"), { href: url, download: f.nombre });
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setError(e.message); }
  }

  async function subirADrive() {
    setDrive("subiendo");
    try {
      const { aviso, ...nuevo } = await guardarEvaluacionEnDrive(id);
      setEv(nuevo);
      setDrive(aviso ? { aviso } : null);
    } catch (e) { setDrive({ aviso: e.message }); }
  }

  async function borrar() {
    if (!window.confirm(`¿Borrar la evaluación de ${ev.jugador_nombre} del ${fmtLarga(ev.fecha)}?`)) return;
    try { await borrarEvaluacion(id); router.push("/evaluaciones"); } catch (e) { setError(e.message); }
  }

  if (error && !ev) return <p className="err">{error}</p>;
  if (!ev || !catalogo) return <p className="msg">Cargando…</p>;

  return (
    <div>
      <div className="page-head">
        <h1>{ev.jugador_nombre}<span className="h1-sub"> · evaluación</span></h1>
        <Link href="/evaluaciones" className="btn ghost sm">Todas las evaluaciones</Link>
      </div>

      {editando ? (
        <AsistenteEvaluacion evaluacion={ev} bloques={catalogo.bloques} ia={catalogo.ia}
          pasoInicio={ev.estado === "TERMINADA" ? 1 : undefined}
          onCambio={setEv} onTerminada={(e) => { setEv(e); setEditando(false); if (catalogo.drive && !e.informe) subirADrive(); }} />
      ) : (
        <>
          <p className="eval-cabecera">
            {fmtLarga(ev.fecha)} · evaluado por <b>{ev.nombre_evaluador}</b> · {ev.idioma === "EN" ? "en inglés" : "en español"}
            {ev.estado === "BORRADOR" && <span className="pill pend"> A medias · {ev.puntuados}/34</span>}
          </p>
          <InformeDeLaEvaluacion informe={ev.informe} parte="tenis" />
          <div className="eval-acciones">
            {ev.puede_editar && <button type="button" className="btn" onClick={() => setEditando(true)}>
              {ev.estado === "BORRADOR" ? "Seguir" : "Editar"}</button>}
            {ev.drive_url && <a className="btn ghost" href={ev.drive_url} target="_blank" rel="noreferrer">Abrir en Drive</a>}
            {ev.estado === "TERMINADA" && catalogo.drive && ev.puede_editar && !ev.drive_url && !ev.informe && (
              <button type="button" className="btn ghost" disabled={drive === "subiendo"} onClick={subirADrive}>Guardar en Drive</button>
            )}
            {ev.estado === "TERMINADA" && <button type="button" className="btn ghost" onClick={descargar}>Descargar PDF</button>}
            {ev.puede_editar && <button type="button" className="btn danger" onClick={borrar}>Borrar</button>}
          </div>
          {drive === "subiendo" && <p className="eval-nota" role="status">Guardando en la carpeta del jugador en Drive…</p>}
          {drive?.aviso && <p className="err" role="alert">{drive.aviso}</p>}
          {error && <p className="err">{error}</p>}
          <Informe ev={ev} bloques={catalogo.bloques} />
        </>
      )}
    </div>
  );
}
