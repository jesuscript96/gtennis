"use client";
import { useEffect, useState } from "react";
import { getAvisos, marcarAvisoLeido } from "../../../lib/api";

const TIPO_LABEL = { MOVIMIENTO: "Movimiento", INVITADO: "Invitado", MANTENIMIENTO: "Mantenimiento", GENERAL: "General" };

export default function AvisosPage() {
  const [avisos, setAvisos] = useState(null);
  const [error, setError] = useState(null);

  async function load() {
    try { setAvisos(await getAvisos()); } catch (e) { setError(String(e.message || e)); }
  }
  useEffect(() => { load(); }, []);

  async function marcar(id) {
    try { await marcarAvisoLeido(id); await load(); } catch (e) { alert(String(e.message || e)); }
  }

  if (error) return <p className="err">{error}</p>;
  if (!avisos) return <p className="msg">Cargando avisos…</p>;

  const noleidos = avisos.filter((a) => !a.leido).length;
  return (
    <div>
      <div className="page-head">
        <h1>Avisos {noleidos > 0 && <span className="badge">{noleidos} sin leer</span>}</h1>
      </div>
      <p className="help">Avisos internos de la web (movimientos de escuela, invitados, mantenimiento). No se envían notificaciones al móvil.</p>
      {avisos.length === 0 ? (
        <p className="msg">No tienes avisos.</p>
      ) : (
        <div className="aviso-list">
          {avisos.map((a) => (
            <div key={a.id} className={`aviso ${a.leido ? "leido" : ""}`}>
              <div className="aviso-main">
                <div className="aviso-top">
                  <span className="aviso-tipo">{TIPO_LABEL[a.tipo] || a.tipo}</span>
                  {a.para_direccion && <span className="aviso-dir">Dirección</span>}
                  <span className="aviso-fecha">{new Date(a.created_at).toLocaleString("es-ES")}</span>
                </div>
                <div className="aviso-titulo">{a.titulo}</div>
                {a.mensaje && <div className="aviso-msg">{a.mensaje}</div>}
              </div>
              {!a.leido && <button className="btn ghost sm" onClick={() => marcar(a.id)}>Marcar leído</button>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
