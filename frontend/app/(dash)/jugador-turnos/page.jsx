"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import PanelTurnos from "../../../components/PanelTurnos";
import { resource } from "../../../lib/api";

/**
 * Cuándo entrena un alumno, desde el lado de dirección.
 *
 * Las dos franjas fijas están también en su ficha, pero los días que se salen
 * de lo habitual ("los miércoles solo por la mañana") necesitan una rejilla, y
 * eso no cabe en el formulario. Se abre desde la tabla de jugadores y usa el
 * mismo panel que ve el entrenador: el dato es el mismo.
 */
// La pestaña «Horario habitual» llega sin jugador (11/11/2026): se elige aquí,
// entre los que ve cada uno (head coach, los de su grupo; dirección, todos).
function ElegirJugador() {
  const router = useRouter();
  const [lista, setLista] = useState(null);
  const [busca, setBusca] = useState("");
  useEffect(() => {
    resource("jugadores").list().then((l) => setLista([...l].sort((a, b) => a.nombre.localeCompare(b.nombre, "es"))))
      .catch(() => setLista([]));
  }, []);
  const t = busca.trim().toLowerCase();
  const visibles = (lista || []).filter((j) => !t || j.nombre.toLowerCase().includes(t)).slice(0, 40);
  return (
    <div className="page">
      <h1>Horario habitual</h1>
      <p className="help">
        Elige un alumno para ver o cambiar en qué franja entrena y qué días se salen de lo habitual.
      </p>
      <input className="search" placeholder="Buscar alumno…" value={busca} autoFocus
             onChange={(e) => setBusca(e.target.value)} style={{ maxWidth: 320, marginBottom: 12 }} />
      {!lista ? <p className="msg">Cargando…</p> : (
        <div className="faltas-sugeridos">
          {visibles.map((j) => (
            <button key={j.id} type="button" className="chip"
                    onClick={() => router.push(`/jugador-turnos?jugador=${j.id}`)}>{j.nombre}</button>
          ))}
          {visibles.length === 0 && <p className="msg">Ninguno con ese nombre.</p>}
        </div>
      )}
    </div>
  );
}

function Contenido() {
  const params = useSearchParams();
  const id = params.get("jugador");
  const [jugador, setJugador] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    resource("jugadores").get(id)
      .then(setJugador)
      .catch((e) => setError(e.message));
  }, [id]);

  if (!id) return <ElegirJugador />;

  return (
    <div className="page">
      <div className="page-head">
        <h1>Turnos · {jugador ? jugador.nombre : "…"}</h1>
        <Link className="btn ghost sm" href="/jugador-turnos">Otro alumno</Link>
      </div>
      <p className="help">
        En qué franja entrena y qué días se salen de lo habitual. Sin franja
        elegida, el motor le pone en la que encaje — una sola de las dos al día.
      </p>
      {error && <p className="err">{error}</p>}
      {jugador
        ? <div className="card"><PanelTurnos jugador={jugador} /></div>
        : !error && <p className="msg">Cargando…</p>}
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<div className="page"><h1>Turnos del alumno</h1></div>}>
      <Contenido />
    </Suspense>
  );
}
