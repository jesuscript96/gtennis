"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import TorneoForm from "../../../../components/TorneoForm";
import {
  addParticipante, borrarTorneo, delParticipante, fusionarTorneo, getTorneo, getTorneos,
  getTorneosResumen, guardarTorneo, resource, updParticipante,
} from "../../../../lib/api";
import { canWrite } from "../../../../lib/perms";
import DeshacerTorneos from "../../../../components/DeshacerTorneos";
import { CERTEZA_CLASS, CERTEZA_LABEL, ESTADO_CLASS, diasHasta, fmtLarga, fmtRango, sumaDias } from "../../../../lib/torneos";

export default function TorneoDetallePage() {
  const { id } = useParams();
  const router = useRouter();
  const [t, setT] = useState(null);
  const [error, setError] = useState("");
  const [editando, setEditando] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [circuitos, setCircuitos] = useState([]);
  const [jugadores, setJugadores] = useState([]);
  const [nuevo, setNuevo] = useState({ jugador: "", nombre: "" });
  const [verFuente, setVerFuente] = useState(false);
  const [vecinos, setVecinos] = useState([]);
  const [dup, setDup] = useState("");
  const [tick, setTick] = useState(0);
  const hecho = () => setTick((n) => n + 1);
  const puedeEditar = canWrite("torneos");

  const cargar = useCallback(() => getTorneo(id).then(setT).catch((e) => setError(e.message)), [id]);
  useEffect(() => { cargar(); }, [cargar]);
  // Posibles duplicados: torneos a ±2 semanas, para fusionarlos si son el mismo.
  useEffect(() => {
    if (!t) return;
    getTorneos({ desde: sumaDias(t.fecha_inicio, -14), hasta: sumaDias(t.fecha_fin, 14) })
      .then((xs) => setVecinos(xs.filter((x) => x.id !== t.id))).catch(() => {});
  }, [t?.id, t?.fecha_inicio, t?.fecha_fin]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    getTorneosResumen().then((r) => setCircuitos(r.circuitos.map((c) => c.nombre))).catch(() => {});
    resource("jugadores").list().then(setJugadores).catch(() => {});
  }, []);

  async function guardar(body) {
    setGuardando(true); setError("");
    try { setT(await guardarTorneo(id, body)); setEditando(false); hecho(); }
    catch (e) { setError(e.message); }
    finally { setGuardando(false); }
  }
  async function borrar() {
    if (!window.confirm(`¿Borrar «${t.nombre}» del calendario? Se quitan también sus ${t.participantes.length} jugadores apuntados.`)) return;
    try { await borrarTorneo(id); router.push("/torneos"); } catch (e) { setError(e.message); }
  }
  async function apuntar(e) {
    e.preventDefault();
    if (!nuevo.jugador && !nuevo.nombre.trim()) return;
    try {
      await addParticipante({ torneo: Number(id), jugador: nuevo.jugador ? Number(nuevo.jugador) : null, nombre: nuevo.nombre.trim() });
      setNuevo({ jugador: "", nombre: "" });
      await cargar();
      hecho();
    } catch (e) { setError(e.message); }
  }
  async function fusionar() {
    const otro = vecinos.find((x) => String(x.id) === dup);
    if (!otro) return;
    if (!window.confirm(`«${otro.nombre}» se fundirá en «${t.nombre}»: sus ${otro.n_jugadores} jugadores pasan aquí y esa fila desaparece. ¿Seguir?`)) return;
    try { setT(await fusionarTorneo(id, otro.id)); setDup(""); hecho(); }
    catch (e) { setError(e.message); }
  }
  async function accion(fn) {
    setError("");
    try { await fn(); await cargar(); hecho(); } catch (e) { setError(e.message); }
  }

  if (error && !t) return <p className="err">{error}</p>;
  if (!t) return <p className="msg">Cargando torneo…</p>;

  const dCierre = diasHasta(t.cierre_inscripcion);
  const yaApuntados = new Set(t.participantes.map((p) => p.jugador).filter(Boolean));

  return (
    <div>
      <p className="volver"><Link href="/torneos">← Calendario de torneos</Link></p>
      <div className="page-head">
        <div>
          <h1>{t.nombre}</h1>
          <div className="torneo-sub grande">
            {t.circuito && <span className="pill circ">{t.circuito}</span>}
            {t.nivel && <span className="muted">{t.nivel}</span>}
            {t.estado !== "VALIDADO" && <span className={`pill ${ESTADO_CLASS[t.estado]}`}>{t.estado_display}</span>}
          </div>
        </div>
        {puedeEditar && !editando && (
          <div className="row-actions">
            <DeshacerTorneos tick={tick} onDeshecho={(r) => {
              // Si lo deshecho era el alta de este torneo, ya no existe.
              if (r.torneos.includes(Number(id)) && !r.existen.includes(Number(id))) router.push("/torneos");
              else cargar();
            }} />
            <button className="btn ghost" onClick={() => setEditando(true)}>Editar</button>
            <button className="btn danger" onClick={borrar}>Borrar</button>
          </div>
        )}
      </div>

      {editando ? (
        <TorneoForm inicial={t} circuitos={circuitos} onGuardar={guardar} onCancelar={() => setEditando(false)}
          guardando={guardando} error={error} />
      ) : (
        <div className="ficha-torneo">
          <div className="dato"><span>Fechas</span><b>{fmtRango(t.fecha_inicio, t.fecha_fin)}</b><small>{fmtLarga(t.fecha_inicio)}{t.fecha_fin !== t.fecha_inicio ? ` → ${fmtLarga(t.fecha_fin)}` : ""}</small></div>
          <div className="dato"><span>Cierre de inscripción</span>
            <b>{t.cierre_inscripcion ? fmtLarga(t.cierre_inscripcion) : "Sin fecha"}</b>
            {dCierre !== null && <small className={dCierre >= 0 && dCierre <= 7 ? "aviso" : ""}>
              {dCierre < 0 ? "cerrado" : dCierre === 0 ? "¡cierra hoy!" : `faltan ${dCierre} días`}</small>}
          </div>
          <div className="dato"><span>Lugar</span><b>{t.lugar || "—"}</b></div>
          <div className="dato"><span>Coach que acompaña</span>
            <b>{t.acompanantes_detalle.map((e) => e.nombre).join(", ") || (t.acompanante_nota ? "" : "Sin decidir")}</b>
            {t.acompanante_nota && <small>{t.acompanante_nota}</small>}
          </div>
          {t.notas && <div className="dato col-todo"><span>Notas</span><b className="normal">{t.notas}</b></div>}
        </div>
      )}
      {error && !editando && <p className="err">{error}</p>}

      <div className="card bloque-participantes">
        <div className="bloque-head"><h2>Jugadores apuntados <span className="muted">({t.participantes.length})</span></h2></div>
        {t.participantes.length === 0 ? (
          <p className="msg sin-margen">Todavía no hay nadie apuntado.</p>
        ) : (
          <table className="data">
            <thead><tr><th>Jugador</th><th>Certeza</th><th>Entrenador de referencia</th><th>Detalle</th>{puedeEditar && <th></th>}</tr></thead>
            <tbody>
              {t.participantes.map((p) => (
                <tr key={p.id}>
                  <td>
                    {p.nombre}
                    {!p.jugador && <span className="pill gris" title="No está en las fichas de la academia">sin ficha</span>}
                  </td>
                  <td><span className={`pill ${CERTEZA_CLASS[p.certeza]}`}>{CERTEZA_LABEL[p.certeza]}</span></td>
                  <td className="muted">{p.entrenador_ref || "—"}</td>
                  <td className="muted">{p.detalle || "—"}</td>
                  {puedeEditar && (
                    <td>
                      <div className="row-actions">
                        {p.certeza !== "CONFIRMADO" && (
                          <button className="btn sm ghost" onClick={() => accion(() => updParticipante(p.id, { certeza: "CONFIRMADO" }))}>Confirmar</button>
                        )}
                        <button className="btn sm danger" onClick={() => accion(() => delParticipante(p.id))}>Quitar</button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {puedeEditar && (
          <form className="apuntar" onSubmit={apuntar}>
            <select value={nuevo.jugador} onChange={(e) => setNuevo({ jugador: e.target.value, nombre: "" })}>
              <option value="">Jugador de la academia…</option>
              {jugadores.filter((j) => !yaApuntados.has(j.id)).map((j) => <option key={j.id} value={j.id}>{j.nombre}</option>)}
            </select>
            <span className="muted">o</span>
            <input placeholder="Nombre de alguien que no está en las fichas" value={nuevo.nombre}
              onChange={(e) => setNuevo({ jugador: "", nombre: e.target.value })} />
            <button className="btn" disabled={!nuevo.jugador && !nuevo.nombre.trim()}>Apuntar</button>
          </form>
        )}
      </div>

      {puedeEditar && vecinos.length > 0 && (
        <div className="card dup-card">
          <div>
            <b>¿Está repetido?</b>
            <span className="muted"> Si otra fila de estas fechas es este mismo torneo, fúndela aquí: sus jugadores pasan a esta ficha y la otra desaparece.</span>
          </div>
          <div className="dup-row">
            <select value={dup} onChange={(e) => setDup(e.target.value)}>
              <option value="">Elegir el torneo repetido…</option>
              {vecinos.map((x) => (
                <option key={x.id} value={x.id}>{x.nombre} · {fmtRango(x.fecha_inicio, x.fecha_fin)} · {x.n_jugadores} jug.</option>
              ))}
            </select>
            <button type="button" className="btn ghost" disabled={!dup} onClick={fusionar}>Fusionar aquí</button>
          </div>
        </div>
      )}

      {(t.fuente || t.alias) && (
        <p className="fuente-excel">
          <button type="button" className="link-mas" onClick={() => setVerFuente((v) => !v)}>
            {verFuente ? "Ocultar" : "Ver"} de dónde sale este dato
          </button>
          {verFuente && (
            <span>
              {t.alias && <><br />También escrito como: {t.alias}</>}
              {t.fuente && <><br />Excel CALENDARIO 2026: {t.fuente}</>}
            </span>
          )}
        </p>
      )}
    </div>
  );
}
