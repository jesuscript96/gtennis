"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  aprobarInforme, descargarPdfInforme, devolverInforme, enviarInforme, getFotoJugador, getInforme, getUser,
  guardarInformeEnDrive, reabrirInforme, subirFotoJugador,
} from "../../../../lib/api";
import { ESTADO_INFORME, abrirParte, textoParte } from "../../../../lib/informes";
import { fmtLarga } from "../../../../lib/torneos";

const fecha = (iso) => (iso ? fmtLarga(iso.slice(0, 10)) : "");

function Foto({ inf }) {
  const [url, setUrl] = useState(null);
  const [estado, setEstado] = useState("");
  const input = useRef(null);

  function cargar() {
    getFotoJugador(inf.jugador).then((f) => setUrl(f ? URL.createObjectURL(f.blob) : null)).catch(() => {});
  }
  useEffect(cargar, [inf.jugador]);

  async function subir(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setEstado("Subiendo…");
    try { await subirFotoJugador(inf.jugador, file); cargar(); setEstado(""); }
    catch (err) { setEstado(err.message); }
  }

  return (
    <div className="inf-foto">
      {url ? <img src={url} alt={`Foto de ${inf.jugador_nombre}`} />
        : <div className="inf-foto-vacia">Sin foto</div>}
      <input ref={input} type="file" accept="image/*" hidden onChange={subir} />
      <button type="button" className="btn ghost sm" onClick={() => input.current?.click()}>
        {url ? "Cambiar foto" : "Subir foto"}
      </button>
      {estado && <p className="eval-nota" role="status">{estado}</p>}
    </div>
  );
}

function Partes({ inf, user }) {
  const router = useRouter();
  const [error, setError] = useState("");
  // Alto rendimiento: solo tenis (10/11/2026, decisión 12).
  const filas = [
    ["tenis", "Tenis", inf.tenis, user?.evalua_tenis_informes],
    ...(inf.circuito === "alto_rendimiento" ? [] : [["fisico", "Preparación física", inf.fisica, user?.evalua_fisico]]),
  ];
  return (
    <div className="inf-partes">
      {filas.map(([clave, titulo, p, puede]) => {
        const [texto, pill] = textoParte(p, inf.devuelto_partes.includes(clave));
        return (
          <div key={clave} className="card inf-parte-card">
            <h2>{titulo}</h2>
            <span className={`pill ${pill}`}>{texto}</span>
            {p ? (
              <p className="eval-nota">
                {p.evaluador || "—"} · {p.puntuados}/{p.total} notas
                {p.terminada_en && ` · terminada el ${fecha(p.terminada_en)}`}
              </p>
            ) : <p className="eval-nota">Nadie la ha empezado todavía.</p>}
            {(p || puede) && (
              <button type="button" className="btn ghost sm"
                onClick={() => abrirParte(router, inf.jugador, clave, p?.id).catch((e) => setError(e.message))}>
                {p ? "Abrir evaluación" : "Evaluar"}
              </button>
            )}
          </div>
        );
      })}
      {error && <p className="err">{error}</p>}
    </div>
  );
}

function Validar({ inf, onCambio }) {
  const [modo, setModo] = useState(null); // null | "aprobar" | "devolver"
  const [dest, setDest] = useState(() =>
    inf.destinatarios.length ? inf.destinatarios
      : inf.destinatarios_propuestos.length ? inf.destinatarios_propuestos : [{ email: "", quien: "Familia" }]);
  const [partes, setPartes] = useState([]);
  const [nota, setNota] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState("");

  const cambia = (i, k, v) => setDest((d) => d.map((x, j) => (j === i ? { ...x, [k]: v } : x)));
  const marca = (p) => setPartes((ps) => (ps.includes(p) ? ps.filter((x) => x !== p) : [...ps, p]));

  async function hacer(fn) {
    setEnviando(true); setError("");
    try { const { aviso, ...nuevo } = await fn(); onCambio(nuevo, aviso); setModo(null); }
    catch (e) { setError(e.message); }
    setEnviando(false);
  }

  return (
    <section className="card inf-validar">
      <h2>Validación</h2>
      <p className="eval-nota">
        Revisa el PDF. Si hay que cambiar algo pequeño, puedes corregirlo tú: abre la evaluación
        {inf.circuito === "alto_rendimiento" ? "" : " (las dos partes)"}. Si no, devuélvelo a quien la hizo con una nota.
      </p>
      {!modo && (
        <div className="eval-acciones">
          <button type="button" className="btn" onClick={() => setModo("aprobar")}>Aprobar</button>
          <button type="button" className="btn ghost" onClick={() => setModo("devolver")}>Devolver</button>
        </div>
      )}
      {modo === "aprobar" && (
        <div className="inf-form">
          <label>A quién se enviará</label>
          {dest.map((d, i) => (
            <div key={i} className="inf-dest">
              <input type="email" placeholder="correo@ejemplo.com" value={d.email}
                onChange={(e) => cambia(i, "email", e.target.value)} />
              <input type="text" placeholder="Quién (madre, padre…)" value={d.quien}
                onChange={(e) => cambia(i, "quien", e.target.value)} />
              <button type="button" className="btn ghost sm" aria-label="Quitar"
                onClick={() => setDest((x) => x.filter((_, j) => j !== i))}>Quitar</button>
            </div>
          ))}
          <button type="button" className="btn ghost sm" onClick={() => setDest((x) => [...x, { email: "", quien: "" }])}>
            Añadir destinatario
          </button>
          <p className="eval-nota">
            {inf.correo_activo
              ? "Con «Aprobar y enviar» le llega a la familia por correo, con el PDF en su idioma."
              : "El correo aún no está configurado en el servidor: al aprobar no se envía; se podrá enviar después."}
            {" "}Al aprobar, el PDF pasa a la carpeta de validados en Drive.
          </p>
          <div className="eval-pie">
            <button type="button" className="btn ghost" onClick={() => setModo(null)}>Cancelar</button>
            <button type="button" className={inf.puede_enviar && inf.correo_activo ? "btn ghost" : "btn"} disabled={enviando}
              onClick={() => hacer(() => aprobarInforme(inf.id, dest.filter((d) => d.email.trim())))}>
              {enviando ? "Aprobando…" : "Aprobar"}
            </button>
            {inf.puede_enviar && inf.correo_activo && (
              <button type="button" className="btn" disabled={enviando || !dest.some((d) => d.email.trim())}
                onClick={() => hacer(() => aprobarInforme(inf.id, dest.filter((d) => d.email.trim()), true))}>
                {enviando ? "Enviando…" : "Aprobar y enviar"}
              </button>
            )}
          </div>
        </div>
      )}
      {modo === "devolver" && (
        <div className="inf-form">
          <label>Qué parte hay que corregir</label>
          <div className="inf-checks">
            {[["tenis", "Tenis"], ["fisico", "Preparación física"]].map(([k, t]) => (
              <label key={k}><input type="checkbox" checked={partes.includes(k)} onChange={() => marca(k)} /> {t}</label>
            ))}
          </div>
          <label htmlFor="inf-nota">Qué hay que cambiar</label>
          <textarea id="inf-nota" rows={4} value={nota} onChange={(e) => setNota(e.target.value)}
            placeholder="Le llega como aviso a quien hizo esa parte." />
          <div className="eval-pie">
            <button type="button" className="btn ghost" onClick={() => setModo(null)}>Cancelar</button>
            <button type="button" className="btn danger" disabled={enviando || !partes.length || !nota.trim()}
              onClick={() => hacer(() => devolverInforme(inf.id, partes, nota))}>
              {enviando ? "Devolviendo…" : "Devolver"}
            </button>
          </div>
        </div>
      )}
      {error && <p className="err">{error}</p>}
    </section>
  );
}

/** Validado: si ya se envió a la familia, a quién y cuándo; si no, enviarlo.
 * Para corregirlo, primero se reabre (10/11/2026). */
function Enviado({ inf, onCambio }) {
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState("");
  async function hacer(fn) {
    setOcupado(true); setError("");
    try { onCambio(await fn()); } catch (e) { setError(e.message); }
    setOcupado(false);
  }
  const para = inf.destinatarios.map((d) => d.email).join(", ");
  return (
    <>
      <p className="eval-nota">
        Validado por <b>{inf.validado_por_nombre}</b> el {fecha(inf.validado_en)}.
        {inf.enviado_en
          ? <> Enviado a la familia ({para}) el {fecha(inf.enviado_en)} por {inf.enviado_por_nombre}.</>
          : para ? <> Aún no se ha enviado a {para}.</> : <> Falta el correo de la familia.</>}
      </p>
      {inf.envio_error && !inf.enviado_en && <p className="err">Último intento de envío: {inf.envio_error}</p>}
      <div className="eval-acciones">
        {inf.puede_enviar && inf.correo_activo && para && (
          <button type="button" className="btn" disabled={ocupado} onClick={() => hacer(() => enviarInforme(inf.id))}>
            {inf.enviado_en ? "Volver a enviar" : "Enviar a la familia"}
          </button>
        )}
        {inf.puede_validar && (
          <button type="button" className="btn ghost" disabled={ocupado}
            onClick={() => window.confirm("¿Reabrir el informe para corregirlo? Después de corregir, vuelve a validar.") && hacer(() => reabrirInforme(inf.id))}>
            Reabrir para corregir
          </button>
        )}
      </div>
      {error && <p className="err">{error}</p>}
    </>
  );
}

export default function InformePage() {
  const { id } = useParams();
  const user = getUser();
  const [inf, setInf] = useState(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [pdf, setPdf] = useState(null); // {url, nombre}
  const [cargandoPdf, setCargandoPdf] = useState(false);

  useEffect(() => { getInforme(id).then(setInf).catch((e) => setError(e.message)); }, [id]);
  useEffect(() => () => { if (pdf) URL.revokeObjectURL(pdf.url); }, [pdf]);

  async function verPdf(idioma = "ES") {
    setCargandoPdf(true); setError("");
    try {
      const f = await descargarPdfInforme(id, idioma);
      setPdf({ url: URL.createObjectURL(f.blob), nombre: f.nombre });
    } catch (e) { setError(e.message); }
    setCargandoPdf(false);
  }

  async function reintentarDrive() {
    try { const { aviso: a, ...nuevo } = await guardarInformeEnDrive(id); setInf(nuevo); setAviso(a || ""); }
    catch (e) { setAviso(e.message); }
  }

  if (error && !inf) return <p className="err">{error}</p>;
  if (!inf) return <p className="msg">Cargando…</p>;
  const [estado, pill] = ESTADO_INFORME[inf.estado];

  return (
    <div>
      <div className="page-head">
        <h1>{inf.jugador_nombre}<span className="h1-sub"> · informe{inf.version > 1 ? ` v${inf.version}` : ""}</span></h1>
        <Link href="/informes" className="btn ghost sm">Todos los informes</Link>
      </div>

      <div className="inf-cabecera">
        <Foto inf={inf} />
        <div className="inf-resumen">
          <p><span className={`pill ${pill}`}>{estado}</span>
            {inf.idioma === "EN" && <span className="eval-nota"> · a la familia se le envía en inglés</span>}
          </p>
          {inf.estado === "EN_CURSO" && (
            <p className="eval-nota">{inf.circuito === "alto_rendimiento"
              ? "Cuando la evaluación de tenis esté terminada, pasa a validar."
              : "Cuando tenis y preparación física estén terminadas, pasa a validar."}</p>
          )}
          {inf.estado === "DEVUELTO" && (
            <p className="informe-nota">
              <b>Devuelto por {inf.devuelto_por_nombre} el {fecha(inf.devuelto_en)}:</b> {inf.nota_devolucion}
            </p>
          )}
          {inf.estado === "VALIDADO" && (
            <Enviado inf={inf} onCambio={(nuevo, a) => { setInf(nuevo); setAviso(a || ""); }} />
          )}
          <div className="eval-acciones">
            {inf.tenis && (
              <button type="button" className="btn ghost" disabled={cargandoPdf} onClick={() => verPdf("ES")}>
                {cargandoPdf ? "Generando PDF…" : "Ver PDF"}
              </button>
            )}
            {inf.tenis && inf.idioma === "EN" && (
              <button type="button" className="btn ghost" disabled={cargandoPdf} onClick={() => verPdf("EN")}>
                PDF para la familia (inglés)
              </button>
            )}
            {pdf && <a className="btn ghost" href={pdf.url} download={pdf.nombre}>Descargar PDF</a>}
            {inf.drive_url && <a className="btn ghost" href={inf.drive_url} target="_blank" rel="noreferrer">Abrir en Drive</a>}
            {inf.completo && !inf.drive_url && inf.puede_validar && (
              <button type="button" className="btn ghost" onClick={reintentarDrive}>Guardar en Drive</button>
            )}
          </div>
          {aviso && <p className="err" role="alert">{aviso}</p>}
          {error && <p className="err">{error}</p>}
        </div>
      </div>

      <Partes inf={inf} user={user} />

      {inf.puede_validar && inf.estado === "PENDIENTE" && (
        <Validar inf={inf} onCambio={(nuevo, a) => { setInf(nuevo); setAviso(a || ""); }} />
      )}

      {pdf && <iframe className="inf-pdf" src={pdf.url} title={`Informe de ${inf.jugador_nombre}`} />}
    </div>
  );
}
