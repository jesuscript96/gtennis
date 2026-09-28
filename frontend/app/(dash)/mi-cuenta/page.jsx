"use client";

import { useState } from "react";
import { cambiarPassword, getUser } from "../../../lib/api";

export default function MiCuenta() {
  const user = getUser();
  const [actual, setActual] = useState("");
  const [nueva, setNueva] = useState("");
  const [repetida, setRepetida] = useState("");
  const [estado, setEstado] = useState(null);
  const [error, setError] = useState(null);
  const [guardando, setGuardando] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setError(null);
    setEstado(null);
    if (nueva !== repetida) {
      setError("Las dos contraseñas nuevas no coinciden.");
      return;
    }
    setGuardando(true);
    try {
      await cambiarPassword(actual, nueva);
      setEstado("Contraseña cambiada. Apúntala donde la tengas a mano.");
      setActual(""); setNueva(""); setRepetida("");
    } catch (e) {
      // La API manda {actual: "..."} o {nueva: "..."}.
      let msg = String(e.message || e);
      try {
        const d = JSON.parse(msg);
        msg = d.actual || d.nueva || d.detail || msg;
        if (Array.isArray(msg)) msg = msg[0];
      } catch {}
      setError(msg);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <div>
      <div className="page-head"><h1>Mi cuenta</h1></div>

      <div className="card" style={{ maxWidth: 480 }}>
        <p style={{ marginTop: 0, color: "var(--muted)" }}>
          Usuario <b>{user?.username}</b>
        </p>

        <form onSubmit={onSubmit}>
          <label>
            Contraseña actual
            <input type="password" value={actual} autoComplete="current-password"
                   onChange={(e) => setActual(e.target.value)} required />
          </label>
          <label>
            Contraseña nueva
            <input type="password" value={nueva} autoComplete="new-password"
                   minLength={8} onChange={(e) => setNueva(e.target.value)} required />
          </label>
          <label>
            Repite la nueva
            <input type="password" value={repetida} autoComplete="new-password"
                   minLength={8} onChange={(e) => setRepetida(e.target.value)} required />
          </label>
          <p style={{ fontSize: 13, color: "var(--muted)" }}>
            Mínimo 8 caracteres. Al cambiarla se cierran las sesiones que tengas
            abiertas en otros dispositivos.
          </p>

          {error && <div className="alert error">{error}</div>}
          {estado && <div className="alert ok">{estado}</div>}

          <button className="btn" type="submit" disabled={guardando}>
            {guardando ? "Guardando…" : "Cambiar contraseña"}
          </button>
        </form>
      </div>
    </div>
  );
}
