"use client";

// La página de un jugador en Torneos (25/11/2026): los torneos que tiene por
// delante, confirmados y por confirmar, cada uno con su fecha de inscripción
// (destacada si sigue abierta), y el mismo contenido en un PDF para la familia.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { descargarPdfTorneosJugador, getTorneosDeJugador } from "../../../../../lib/api";
import {
  CERTEZA_AYUDA, CERTEZA_CLASS, CERTEZA_LABEL, MES3, MESES, diasHasta, fmtCorta, fmtRango,
} from "../../../../../lib/torneos";

function SelloFecha({ t }) {
  const [, m1, d1] = t.fecha_inicio.split("-");
  const [, m2, d2] = t.fecha_fin.split("-");
  if (m1 === m2) {
    return (
      <div className="tj-sello">
        <div className="tj-dias">{d1 === d2 ? Number(d1) : `${Number(d1)}–${Number(d2)}`}</div>
        <div className="tj-mes">{MES3[Number(m1) - 1]}</div>
      </div>
    );
  }
  return (
    <div className="tj-sello">
      <div className="tj-dias largo">{fmtCorta(t.fecha_inicio)}</div>
      <div className="tj-mes">– {fmtCorta(t.fecha_fin)}</div>
    </div>
  );
}

function Inscripcion({ t }) {
  if (!t.cierre_inscripcion) return <div className="tj-insc sin">Inscripción: sin fecha</div>;
  const d = diasHasta(t.cierre_inscripcion);
  if (d < 0) {
    return (
      <div className="tj-insc cerrada">
        <span className="tj-insc-etq">Inscripción cerrada</span>
        <span className="tj-insc-f">{fmtCorta(t.cierre_inscripcion)}</span>
      </div>
    );
  }
  return (
    <div className={`tj-insc abierta${d <= 7 ? " urge" : ""}`}>
      <span className="tj-insc-etq">Inscripción hasta</span>
      <span className="tj-insc-f">{fmtCorta(t.cierre_inscripcion)}</span>
      <span className="tj-insc-q">{d === 0 ? "cierra hoy" : d === 1 ? "queda 1 día" : `quedan ${d} días`}</span>
    </div>
  );
}

export default function TorneosDeJugadorPage() {
  const { id } = useParams();
  const [d, setD] = useState(null);
  const [error, setError] = useState("");
  const [bajando, setBajando] = useState("");

  useEffect(() => { getTorneosDeJugador(id).then(setD).catch((e) => setError(e.message)); }, [id]);

  const meses = useMemo(() => {
    const out = [];
    for (const t of d?.torneos || []) {
      const clave = t.fecha_inicio.slice(0, 7);
      if (!out.length || out[out.length - 1].clave !== clave) {
        const [a, m] = clave.split("-");
        out.push({ clave, nombre: `${MESES[Number(m) - 1]} ${a}`, torneos: [] });
      }
      out[out.length - 1].torneos.push(t);
    }
    return out;
  }, [d]);

  async function pdf(idioma) {
    setBajando(idioma); setError("");
    try {
      const f = await descargarPdfTorneosJugador(id, idioma);
      const url = URL.createObjectURL(f.blob);
      Object.assign(document.createElement("a"), { href: url, download: f.nombre }).click();
      URL.revokeObjectURL(url);
    } catch (e) { setError(e.message); }
    finally { setBajando(""); }
  }

  if (error && !d) return <p className="err">{error}</p>;
  if (!d) return <p className="msg">Cargando…</p>;
  const { jugador: j, resumen: r } = d;

  return (
    <div className="tj">
      <p className="volver"><Link href="/torneos/jugadores">← Torneos por jugador</Link></p>
      <div className="page-head tj-cab">
        <div>
          <h1>{j.nombre}</h1>
          <p className="muted tj-meta">
            {[j.entrenador && `Entrenador: ${j.entrenador}`, j.categoria && `Categoría: ${j.categoria}`].filter(Boolean).join(" · ")}
            {j.de_baja && <span className="pill no">de baja</span>}
          </p>
        </div>
        <div className="tj-botones">
          <button className="btn" onClick={() => pdf("ES")} disabled={!!bajando}>
            {bajando === "ES" ? "Generando…" : "Descargar PDF"}
          </button>
          <button className="btn ghost" onClick={() => pdf("EN")} disabled={!!bajando} title="El mismo PDF, en inglés">
            {bajando === "EN" ? "Generando…" : "PDF en inglés"}
          </button>
        </div>
      </div>
      {error && <p className="err">{error}</p>}

      <div className="metrics tj-cifras">
        <div className="metric"><div className="label">Torneos por delante</div><div className="value">{r.total}</div></div>
        <div className="metric"><div className="label">Confirmados</div><div className="value">{r.confirmados}</div></div>
        <div className="metric"><div className="label">Por confirmar</div><div className="value">{r.por_confirmar}</div></div>
        <div className={`metric${r.proximo_cierre ? " tj-destacada" : ""}`}>
          <div className="label">Próximo cierre de inscripción</div>
          <div className="value">{r.proximo_cierre ? fmtCorta(r.proximo_cierre) : "—"}</div>
          {r.proximo_cierre_torneo && <div className="tj-cual">{r.proximo_cierre_torneo}</div>}
        </div>
      </div>
      <p className="muted tj-jugados">Ya jugados esta temporada: {d.jugados}.</p>

      {!meses.length && <div className="card tj-vacio">No tiene torneos por delante. Se le apunta desde la ficha de cada torneo.</div>}

      {meses.map((m) => (
        <section key={m.clave} className="tj-mes-bloque">
          <h2 className="tj-mes-titulo">{m.nombre}</h2>
          {m.torneos.map((t) => (
            <article key={t.participante} className={`tj-torneo${t.confirmado ? "" : " pend"}${t.cancelado ? " cancelado" : ""}`}>
              <SelloFecha t={t} />
              <div className="tj-que">
                <Link href={`/torneos/${t.id}`} className="tj-nombre">{t.nombre}</Link>
                {t.lugar && <div className="muted">{t.lugar}</div>}
                <div className="tj-chips">
                  {t.cancelado && <span className="pill no">Cancelado</span>}
                  {t.circuito && <span className="pill circ">{t.circuito}</span>}
                  {t.categorias.map((c) => <span key={c} className="pill cat">{c}</span>)}
                  {t.qualy_inicio && <span className="pill gris">Previa {fmtRango(t.qualy_inicio, t.qualy_fin || t.qualy_inicio)}</span>}
                  {t.solo_fines_semana && <span className="pill finde">Solo fines de semana</span>}
                </div>
                {(t.acompanantes.length > 0 || t.acompanante_nota) && (
                  <div className="tj-acomp">Acompaña: <b>{t.acompanantes.join(", ") || t.acompanante_nota}</b></div>
                )}
                {t.detalle && <div className="tj-notas">Notas: {t.detalle}</div>}
              </div>
              <div className="tj-lado">
                <span className={`pill ${CERTEZA_CLASS[t.certeza]}`} title={CERTEZA_AYUDA[t.certeza]}>
                  {t.confirmado ? "Confirmado" : `Por confirmar · ${CERTEZA_LABEL[t.certeza].toLowerCase()}`}
                </span>
                <Inscripcion t={t} />
                {t.fecha_borrado && diasHasta(t.fecha_borrado) >= 0 && (
                  <div className="muted tj-borrado">Retirarse sin coste hasta el {fmtCorta(t.fecha_borrado)}</div>
                )}
              </div>
            </article>
          ))}
        </section>
      ))}
      <p className="muted tj-pie">
        El PDF lleva lo mismo salvo las notas internas y los torneos cancelados: se puede dar a la familia.
      </p>
    </div>
  );
}
