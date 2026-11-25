"use client";

// Correos del día 1 a las familias (25/11/2026). Cada mes, el día 1, se
// prepara uno por jugador con torneos ese mes o el siguiente. Sale en cuanto
// lo valida su head coach o dirección; hasta entonces se ve con los datos del
// momento. Las normas de torneos, al final de cada correo, las escribe dirección.

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  accionCorreoTorneos, descargarPdfCorreoTorneos, generarCorreosTorneos, getCorreoTorneos, getCorreosTorneos,
  getNormasTorneos, guardarNormasTorneos, validarCorreosTorneos,
} from "../../../../lib/api";
import { MESES, fmtCorta } from "../../../../lib/torneos";

const ESTADO_CLASS = { PENDIENTE: "pend", VALIDADO: "pend2", ENVIADO: "ok", DESCARTADO: "gris" };
const FILTROS = [
  { v: "", label: "Todos" }, { v: "PENDIENTE", label: "Por validar" }, { v: "VALIDADO", label: "Saliendo" },
  { v: "ENVIADO", label: "Enviados" }, { v: "DESCARTADO", label: "No se envían" },
];

const mesISO = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
const sumaMes = (iso, n) => { const [a, m] = iso.split("-").map(Number); return mesISO(new Date(a, m - 1 + n, 1)); };
const nombreMes = (iso) => { const [a, m] = iso.split("-").map(Number); return `${MESES[m - 1]} ${a}`; };
const hora = (iso) => (iso ? new Date(iso).toLocaleString("es-ES", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");

function Normas() {
  const [n, setN] = useState(null);
  const [editando, setEditando] = useState(false);
  const [txt, setTxt] = useState({ texto: "", texto_en: "" });
  const [error, setError] = useState("");
  useEffect(() => { getNormasTorneos().then(setN).catch(() => {}); }, []);
  if (!n) return null;
  async function guardar() {
    setError("");
    try { setN(await guardarNormasTorneos(txt.texto, txt.texto_en)); setEditando(false); }
    catch (e) { setError(e.message); }
  }
  return (
    <div className={`card normas-card${n.texto.trim() ? "" : " vacias"}`}>
      <div className="normas-cab">
        <b>Normas de torneos de G Tenis</b>
        <span className="muted">van al final de cada correo y del PDF adjunto</span>
        {n.puede_editar && !editando && (
          <button className="btn sm ghost" onClick={() => { setTxt({ texto: n.texto, texto_en: n.texto_en }); setEditando(true); }}>
            {n.texto.trim() ? "Editar" : "Escribirlas"}
          </button>
        )}
      </div>
      {editando ? (
        <>
          <label className="field"><span>En español. Una línea que empieza por «-» es un punto de una lista.</span>
            <textarea rows={8} value={txt.texto} onChange={(e) => setTxt({ ...txt, texto: e.target.value })} /></label>
          <label className="field"><span>En inglés, para las familias en inglés (si se deja vacío, va el de español)</span>
            <textarea rows={5} value={txt.texto_en} onChange={(e) => setTxt({ ...txt, texto_en: e.target.value })} /></label>
          {error && <p className="err">{error}</p>}
          <div className="row-actions">
            <button className="btn" onClick={guardar}>Guardar normas</button>
            <button className="btn ghost" onClick={() => setEditando(false)}>Cancelar</button>
          </div>
        </>
      ) : n.texto.trim() ? (
        <pre className="normas-texto">{n.texto}</pre>
      ) : (
        <p className="muted">
          Aún no hay normas escritas: los correos saldrían sin ellas.
          {!n.puede_editar && " Las escribe dirección."}
        </p>
      )}
    </div>
  );
}

function VistaPrevia({ id, onCerrar, onCambio }) {
  const [c, setC] = useState(null);
  const [para, setPara] = useState([]);
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(false);
  useEffect(() => {
    getCorreoTorneos(id).then((x) => {
      setC(x);
      setPara(x.destinatarios.length ? x.destinatarios : [{ email: "", quien: "Familia" }]);
    }).catch((e) => setError(e.message));
  }, [id]);

  async function hacer(fn) {
    setOcupado(true); setError("");
    try { await fn(); onCambio(); onCerrar(); }
    catch (e) { setError(e.message); }
    finally { setOcupado(false); }
  }
  async function pdf() {
    try {
      const f = await descargarPdfCorreoTorneos(id);
      const url = URL.createObjectURL(f.blob);
      Object.assign(document.createElement("a"), { href: url, download: f.nombre }).click();
      URL.revokeObjectURL(url);
    } catch (e) { setError(e.message); }
  }

  const editable = c && c.estado === "PENDIENTE" && c.puede_validar;
  return (
    <div className="overlay" onClick={onCerrar}>
      <div className="modal modal-correo" onClick={(e) => e.stopPropagation()}>
        {!c ? <p className="msg">{error || "Cargando…"}</p> : (
          <>
            <h2>{c.asunto}</h2>
            <div className="correo-meta">
              <div><span className="muted">Para</span>
                {editable ? (
                  <div className="correo-para">
                    {para.map((d, i) => (
                      <input key={i} type="email" placeholder="correo de la familia" value={d.email}
                        onChange={(e) => setPara(para.map((x, k) => (k === i ? { ...x, email: e.target.value } : x)))} />
                    ))}
                    {para.length < 2 && (
                      <button type="button" className="link-mas" onClick={() => setPara([...para, { email: "", quien: "Familia" }])}>+ otro correo</button>
                    )}
                  </div>
                ) : (
                  <span> {c.destinatarios.map((d) => d.email).join(", ") || "—"}</span>
                )}
              </div>
              <div><span className="muted">Respuestas a</span> {c.responder_a.join(", ")}</div>
              <div><span className="muted">Idioma</span> {c.idioma === "EN" ? "inglés" : "español"} · <span className="muted">Adjunto</span>{" "}
                <button type="button" className="link-mas" onClick={pdf}>PDF con el calendario</button></div>
            </div>
            {editable && c.por_confirmar > 0 && (
              <p className="aviso-correo">
                Lleva {c.por_confirmar === 1 ? "1 torneo" : `${c.por_confirmar} torneos`} sin el visto bueno final: saldrá{c.por_confirmar === 1 ? "" : "n"} como
                «Por confirmar». Si ya está decidido, valídalo antes en el calendario.
              </p>
            )}
            {c.envio_error && <p className="err">No salió: {c.envio_error}</p>}
            <iframe className="correo-html" title="Vista previa del correo" srcDoc={c.html} sandbox="" />
            {error && <p className="err">{error}</p>}
            <div className="actions">
              {editable && (
                <>
                  <button className="btn ghost" disabled={ocupado} onClick={() => hacer(() => accionCorreoTorneos(id, "descartar"))}>No enviar</button>
                  <button className="btn" disabled={ocupado} onClick={() => hacer(() => validarCorreosTorneos([id], para))}>Validar y enviar</button>
                </>
              )}
              {c.puede_validar && c.estado === "VALIDADO" && c.envio_error && (
                <button className="btn" disabled={ocupado} onClick={() => hacer(() => accionCorreoTorneos(id, "reintentar"))}>Volver a intentarlo</button>
              )}
              {c.puede_validar && (c.estado === "DESCARTADO" || (c.estado === "VALIDADO" && c.envio_error)) && (
                <button className="btn ghost" disabled={ocupado} onClick={() => hacer(() => accionCorreoTorneos(id, "recuperar"))}>Volver a «Por validar»</button>
              )}
              <button className="btn ghost" onClick={onCerrar}>Cerrar</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function CorreosTorneosPage() {
  const [mes, setMes] = useState(() => mesISO(new Date()));
  const [d, setD] = useState(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [filtro, setFiltro] = useState("");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(() => new Set());
  const [viendo, setViendo] = useState(null);
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(() => {
    getCorreosTorneos(mes).then((x) => { setD(x); setError(""); }).catch((e) => setError(e.message));
  }, [mes]);
  useEffect(() => { setD(null); setSel(new Set()); cargar(); }, [cargar]);

  const filas = useMemo(() => (d?.filas || []).filter((f) =>
    (!filtro || f.estado === filtro) && f.nombre.toLowerCase().includes(q.toLowerCase())), [d, filtro, q]);
  const listos = filas.filter((f) => f.estado === "PENDIENTE" && f.puede_validar && f.destinatarios.length);
  const cuenta = (e) => (d?.filas || []).filter((f) => f.estado === e).length;

  function alternar(id) {
    setSel((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  }
  async function validarSel() {
    setOcupado(true); setError(""); setAviso("");
    try {
      const r = await validarCorreosTorneos([...sel]);
      setAviso(`${r.validados} validado${r.validados === 1 ? "" : "s"}: salen en el próximo minuto.${r.saltados.length ? ` No se han podido validar: ${r.saltados.join(" · ")}` : ""}`);
      setSel(new Set()); cargar();
    } catch (e) { setError(e.message); }
    finally { setOcupado(false); }
  }
  async function generar() {
    setOcupado(true); setError(""); setAviso("");
    try {
      const r = await generarCorreosTorneos(mes);
      setAviso(r.creados ? `Preparados ${r.creados} correos nuevos.` : "No faltaba ninguno: todos los jugadores con torneos ya tienen el suyo.");
      cargar();
    } catch (e) { setError(e.message); }
    finally { setOcupado(false); }
  }

  return (
    <div>
      <div className="page-head"><h1>Correos a las familias</h1></div>
      <p className="help">
        El <b>día 1 de cada mes</b> se prepara un correo para la familia de cada jugador con torneos ese mes o el siguiente:
        sus torneos (los confirmados y los que faltan por confirmar, marcados), la fecha de inscripción de cada uno
        —destacada si aún no ha pasado— y las normas de torneos, con el calendario en PDF adjunto. Sale en cuanto lo valida
        su head coach o dirección. Hasta entonces se ve con los datos del momento; al validarlo, sale tal cual.
      </p>
      {d && !d.correo_activo && <p className="aviso-correo">El envío por correo no está configurado en este servidor: se puede validar, pero no saldrá.</p>}

      <Normas />

      <div className="toolbar correos-toolbar">
        <div className="mes-nav">
          <button className="btn sm ghost" onClick={() => setMes(sumaMes(mes, -1))} aria-label="Mes anterior">‹</button>
          <b className="mes-nombre">{nombreMes(mes)}</b>
          <button className="btn sm ghost" onClick={() => setMes(sumaMes(mes, 1))} aria-label="Mes siguiente">›</button>
        </div>
        <select value={filtro} onChange={(e) => setFiltro(e.target.value)}>
          {FILTROS.map((f) => <option key={f.v} value={f.v}>{f.label}{f.v && d ? ` (${cuenta(f.v)})` : ""}</option>)}
        </select>
        <input className="search" placeholder="Buscar jugador…" value={q} onChange={(e) => setQ(e.target.value)} />
        {d?.puede_generar && (
          <button className="btn ghost" disabled={ocupado} onClick={generar}
            title="Lo hace solo el programador el día 1; esto prepara los de quien se haya apuntado después">
            Preparar los que falten
          </button>
        )}
      </div>
      {error && <p className="err">{error}</p>}
      {aviso && <p className="ok-msg">{aviso}</p>}

      {!d ? <p className="msg">Cargando…</p> : !d.filas.length ? (
        <div className="card tj-vacio">
          No hay correos de {nombreMes(mes)}. Se preparan solos el día 1 a las 8:00
          {d.puede_generar ? "; también puedes prepararlos ahora con «Preparar los que falten»." : "."}
        </div>
      ) : (
        <>
          {listos.length > 0 && (
            <div className="correos-masivo">
              <label className="check">
                <input type="checkbox" checked={listos.every((f) => sel.has(f.id))}
                  onChange={(e) => setSel(e.target.checked ? new Set(listos.map((f) => f.id)) : new Set())} />
                Seleccionar los {listos.length} que están listos
              </label>
              <button className="btn" disabled={!sel.size || ocupado} onClick={validarSel}>
                Validar y enviar {sel.size || ""}
              </button>
            </div>
          )}
          <div className="card">
            <table className="data tabla-correos">
              <thead><tr><th /><th>Jugador</th><th>Torneos</th><th>Inscripción</th><th>Para</th><th>Estado</th><th /></tr></thead>
              <tbody>
                {filas.map((f) => (
                  <tr key={f.id}>
                    <td>{f.estado === "PENDIENTE" && f.puede_validar && f.destinatarios.length > 0 && (
                      <input type="checkbox" checked={sel.has(f.id)} onChange={() => alternar(f.id)} />
                    )}</td>
                    <td data-label="Jugador"><Link href={`/torneos/jugadores/${f.jugador}`}><b>{f.nombre}</b></Link>
                      {f.entrenador && <div className="muted">{f.entrenador}</div>}</td>
                    <td data-label="Torneos">{f.n_torneos}{f.por_confirmar > 0 && <span className="pill pend" title="Sin el visto bueno final de dirección">{f.por_confirmar} por confirmar</span>}</td>
                    <td data-label="Inscripción">{f.inscripciones_abiertas
                      ? <span className="pill insc-abierta">{f.inscripciones_abiertas} abierta{f.inscripciones_abiertas > 1 ? "s" : ""} · {fmtCorta(f.proximo_cierre)}</span>
                      : <span className="muted">—</span>}</td>
                    <td className="td-para" data-label="Para">{f.destinatarios.length
                      ? f.destinatarios.map((x) => x.email).join(", ")
                      : <span className="pill no">sin correo</span>}{f.idioma === "EN" && <span className="pill gris">EN</span>}</td>
                    <td data-label="Estado">
                      <span className={`pill ${ESTADO_CLASS[f.estado]}`}>{f.estado === "VALIDADO" && f.envio_error ? "No salió" : f.estado_display}</span>
                      <div className="muted correo-cuando">
                        {f.estado === "ENVIADO" ? hora(f.enviado_en) : f.validado_por_nombre ? `${f.validado_por_nombre} · ${hora(f.validado_en)}` : ""}
                      </div>
                    </td>
                    <td><button className="btn sm ghost" onClick={() => setViendo(f.id)}>{f.estado === "PENDIENTE" && f.puede_validar ? "Revisar" : "Ver"}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {viendo && <VistaPrevia id={viendo} onCerrar={() => setViendo(null)} onCambio={cargar} />}
    </div>
  );
}
