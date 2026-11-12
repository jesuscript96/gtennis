"use client";

import { useEffect, useRef, useState } from "react";
import { getFotoJugador, subirFotoJugador } from "../lib/api";

/** La foto del jugador para su informe: la ve y la cambia quien le evalúa
 *  (en Alto rendimiento, su entrenador, el head coach de su color y
 *  dirección). Si el servidor no deja verla, no se pinta nada. */
export default function FotoJugador({ jugadorId, nombre }) {
  const [url, setUrl] = useState(null);
  const [puede, setPuede] = useState(true);
  const [estado, setEstado] = useState("");
  const input = useRef(null);

  function cargar() {
    getFotoJugador(jugadorId)
      .then((f) => setUrl(f ? URL.createObjectURL(f.blob) : null))
      .catch(() => setPuede(false));
  }
  useEffect(cargar, [jugadorId]);

  async function subir(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setEstado("Subiendo…");
    try { await subirFotoJugador(jugadorId, file); cargar(); setEstado(""); }
    catch (err) { setEstado(err.message); }
  }

  if (!puede) return null;
  return (
    <div className="inf-foto">
      {url ? <img src={url} alt={`Foto de ${nombre}`} />
        : <div className="inf-foto-vacia">Sin foto</div>}
      <input ref={input} type="file" accept="image/*" hidden onChange={subir} />
      <button type="button" className="btn ghost sm" onClick={() => input.current?.click()}>
        {url ? "Cambiar foto" : "Subir foto"}
      </button>
      {estado && <p className="eval-nota" role="status">{estado}</p>}
    </div>
  );
}
