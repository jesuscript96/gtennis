"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { getTorneosPorJugador } from "../../../../lib/api";
import { fmtCorta, fmtRango, hoyISO } from "../../../../lib/torneos";

export default function TorneosPorJugadorPage() {
  const hoy = hoyISO();
  const [filas, setFilas] = useState(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [soloAcademia, setSoloAcademia] = useState(false);
  const [abierto, setAbierto] = useState(null);

  useEffect(() => { getTorneosPorJugador().then(setFilas).catch((e) => setError(e.message)); }, []);

  const vis = useMemo(() => (filas || []).filter((f) =>
    (!soloAcademia || f.en_academia) && f.nombre.toLowerCase().includes(q.toLowerCase())), [filas, q, soloAcademia]);

  if (error) return <p className="err">{error}</p>;
  if (!filas) return <p className="msg">Cargando…</p>;

  return (
    <div>
      <div className="page-head"><h1>Torneos por jugador</h1></div>
      <p className="help">
        Cuántos torneos tiene cada jugador en la temporada, cuál es el siguiente y cuándo cierra su inscripción.
        Pulsa una fila para desplegar todos sus torneos.
      </p>
      <div className="toolbar">
        <input className="search" placeholder="Buscar jugador…" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="check filtro-check">
          <input type="checkbox" checked={soloAcademia} onChange={(e) => setSoloAcademia(e.target.checked)} />
          Solo jugadores con ficha en la academia
        </label>
        <span className="muted">{vis.length} jugadores</span>
      </div>
      <div className="card">
        <table className="data tabla-por-jugador">
          <thead><tr><th>Jugador</th><th>Torneos</th><th>Jugados</th><th>Próximo torneo</th><th>Próximo cierre</th></tr></thead>
          <tbody>
            {vis.map((f) => {
              const clave = f.jugador || f.nombre;
              const futuros = f.torneos.filter((t) => t.fecha_fin >= hoy);
              const prox = futuros[0];
              const cierre = futuros.map((t) => t.cierre_inscripcion).filter((c) => c && c >= hoy).sort()[0];
              const jugados = f.torneos.length - futuros.length;
              return (
                <Fragment key={clave}>
                  <tr className="fila-click" onClick={() => setAbierto(abierto === clave ? null : clave)}>
                    <td><b>{f.nombre}</b>{!f.en_academia && <span className="pill gris">sin ficha</span>}</td>
                    <td>{f.torneos.length}</td>
                    <td className="muted">{jugados}</td>
                    <td>{prox ? <><Link href={`/torneos/${prox.id}`} onClick={(e) => e.stopPropagation()}>{prox.nombre}</Link> <span className="muted">· {fmtRango(prox.fecha_inicio, prox.fecha_fin)}</span></> : <span className="muted">—</span>}</td>
                    <td>{cierre ? fmtCorta(cierre) : <span className="muted">—</span>}</td>
                  </tr>
                  {abierto === clave && (
                    <tr className="fila-detalle">
                      <td colSpan={5}>
                        <ul className="lista-torneos-jugador">
                          {f.torneos.map((t, i) => (
                            <li key={i} className={t.fecha_fin < hoy ? "pasado" : ""}>
                              <span className="td-fechas">{fmtRango(t.fecha_inicio, t.fecha_fin)}</span>
                              <Link href={`/torneos/${t.id}`}>{t.nombre}</Link>
                              {t.circuito && <span className="pill circ">{t.circuito}</span>}
                              {t.certeza !== "CONFIRMADO" && <span className="pill pend">{t.certeza === "DEDUCIDO" ? "deducido" : "pendiente"}</span>}
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
