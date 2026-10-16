"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { crearEvaluacion, getEvaluaciones, resource } from "../../../lib/api";
import { fmtLarga } from "../../../lib/torneos";

function Evaluaciones() {
  const router = useRouter();
  const params = useSearchParams();
  const [evaluaciones, setEvaluaciones] = useState(null);
  const [jugadores, setJugadores] = useState([]);
  const [elegido, setElegido] = useState(params.get("jugador") || "");
  const [busca, setBusca] = useState("");
  const [creando, setCreando] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getEvaluaciones().then(setEvaluaciones).catch((e) => setError(e.message));
    resource("jugadores").list().then(setJugadores).catch(() => {});
  }, []);

  async function empezar() {
    setCreando(true); setError("");
    try {
      const ev = await crearEvaluacion({ jugador: Number(elegido) });
      router.push(`/evaluaciones/${ev.id}`);
    } catch (e) { setError(e.message); setCreando(false); }
  }

  const q = busca.trim().toLowerCase();
  const lista = (evaluaciones || []).filter((e) =>
    !q || e.jugador_nombre.toLowerCase().includes(q) || e.nombre_evaluador.toLowerCase().includes(q));
  const ordenados = [...jugadores].sort((a, b) => a.nombre.localeCompare(b.nombre, "es"));

  return (
    <div>
      <div className="page-head"><h1>Evaluaciones</h1></div>
      <p className="help">
        El <b>Informe de Rendimiento</b> de un jugador: notas del 1 al 5 por bloque y, si quieres, un
        comentario, escrito o dictado con el micrófono del teclado. Claude deja el comentario bien
        redactado sin cambiarle el sentido y, al final, propone tres fortalezas y tres mejoras que
        puedes retocar.
      </p>

      <div className="card eval-nueva">
        <label htmlFor="eval-jugador">Nueva evaluación</label>
        <div className="eval-nueva-fila">
          <select id="eval-jugador" value={elegido} onChange={(e) => setElegido(e.target.value)}>
            <option value="">Elige jugador…</option>
            {ordenados.map((j) => <option key={j.id} value={j.id}>{j.nombre}</option>)}
          </select>
          <button type="button" className="btn" disabled={!elegido || creando} onClick={empezar}>
            {creando ? "Creando…" : "Empezar"}
          </button>
        </div>
      </div>

      {error && <p className="err">{error}</p>}

      {evaluaciones === null ? <p className="msg">Cargando…</p> : (
        <>
          {evaluaciones.length > 0 && (
            <input className="eval-busca" type="search" placeholder="Buscar jugador o entrenador"
              value={busca} onChange={(e) => setBusca(e.target.value)} />
          )}
          {lista.length === 0 ? <p className="msg">Todavía no hay evaluaciones.</p> : (
            <ul className="eval-lista">
              {lista.map((e) => (
                <li key={e.id}>
                  <Link href={`/evaluaciones/${e.id}`} className="card">
                    <span className="eval-lista-nombre">{e.jugador_nombre}</span>
                    <span className="eval-lista-meta">
                      {fmtLarga(e.fecha)} · {e.nombre_evaluador} · {e.idioma}
                    </span>
                    {e.estado === "BORRADOR"
                      ? <span className="pill pend">A medias · {e.puntuados}/34</span>
                      : <span className="pill ok">Terminada</span>}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

export default function EvaluacionesPage() {
  return <Suspense fallback={<p className="msg">Cargando…</p>}><Evaluaciones /></Suspense>;
}
