"use client";

import { useEffect, useState } from "react";
import { deshacerTorneos, getCambiosTorneos } from "../lib/api";

// «↩︎ Deshacer» del calendario de torneos: deshace el último cambio de quien
// lo pulsa (borrar, mover, acompañante, fusionar…) y dice cuál. `tick` cambia
// cada vez que la página hace un cambio, para volver a preguntar cuál es el
// último; `onDeshecho` recibe la respuesta para recargar lo que se ve.
export default function DeshacerTorneos({ tick, onDeshecho }) {
  const [ultimo, setUltimo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [aviso, setAviso] = useState("");

  const cargar = () => getCambiosTorneos().then((xs) => setUltimo(xs[0] || null)).catch(() => {});
  useEffect(() => { cargar(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps

  async function deshacer() {
    setBusy(true); setAviso("");
    try {
      const r = await deshacerTorneos();
      setAviso(`Deshecho: ${r.deshecho}`);
      await cargar();
      onDeshecho?.(r);
    } catch (e) {
      setAviso(e.message);
    } finally { setBusy(false); }
  }

  if (!ultimo && !aviso) return null;
  return (
    <span className="deshacer-torneos">
      {ultimo && (
        <button type="button" className="btn ghost" onClick={deshacer} disabled={busy}
          title={`Deshacer: ${ultimo.descripcion}`}>
          {busy ? "…" : "↩︎ Deshacer"}
          <span className="deshacer-que">{ultimo.descripcion}</span>
        </button>
      )}
      {aviso && <span className="deshacer-aviso" role="status">{aviso}</span>}
    </span>
  );
}
