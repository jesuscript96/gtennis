"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { login } from "../../../lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showHint, setShowHint] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(username, password);
      router.push("/");
    } catch {
      setError("Usuario o contraseña incorrectos.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="login-bg" />
      <div className="login-scrim" />
      <div className="login-stage">
        <div className="login-top">
          <h1 className="login-brand">GTennis</h1>
          <p className="login-tagline">Tenis de Élite · by Club de Tenis Valencia</p>
        </div>

        <form className="login-cluster" onSubmit={onSubmit}>
          <div className="mac-avatar">G</div>
          <div className="mac-form">
            <input
              className="mac-field"
              placeholder="Usuario"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
            />
            <div className="mac-row">
              <input
                className="mac-field"
                type="password"
                placeholder="Contraseña"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <button
                type="button"
                className="mac-help-btn"
                aria-label="Ayuda"
                onClick={() => setShowHint((s) => !s)}
              >
                ?
              </button>
            </div>
            {error ? (
              <p className="login-error">{error}</p>
            ) : (
              <p className="login-hint">
                {showHint
                  ? "Usa el usuario y la contraseña que te dio el club. ¿Problemas? Contacta con administración."
                  : loading
                    ? "Iniciando sesión…"
                    : "Para iniciar sesión, se requiere la contraseña."}
              </p>
            )}
            <button type="submit" aria-hidden="true" style={{ position: "absolute", left: "-9999px" }}>
              Entrar
            </button>
          </div>
        </form>
      </div>
    </>
  );
}
