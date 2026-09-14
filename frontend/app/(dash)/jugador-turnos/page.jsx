"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
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

  if (!id) {
    return (
      <div className="page">
        <h1>Turnos del alumno</h1>
        <p className="help">
          Ábrelo desde <Link href="/jugadores">Jugadores</Link>, con el botón
          «Turnos» de la fila del alumno.
        </p>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-head">
        <h1>Turnos · {jugador ? jugador.nombre : "…"}</h1>
        <Link className="btn ghost sm" href="/jugadores">Volver a jugadores</Link>
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
