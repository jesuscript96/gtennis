"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { getFaltasDelDia } from "../../../../lib/api";

// Faltas del día (25/11/2026): quién falta un día concreto, por grupos. Por
// defecto, hoy. Pensada para mirarla en el móvil desde la pista.
//
// Lo que ve cada uno lo recorta el servidor (/grupos/faltas/), igual que en
// Grupos: dirección, todo el club; el head coach de un color, todas las
// columnas de su color; el entrenador, solo la suya.

const DIAS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
  "septiembre", "octubre", "noviembre", "diciembre"];
const MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const AMBITO = {
  DIA: "Todo el día", MANANA: "Mañana", TARDE: "Tarde", M1: "M1", M2: "M2",
  JP: "Junior Program", T1: "T1", T2: "T2",
};

// Fechas siempre en hora local: new Date("2026-11-25") sería UTC.
const iso = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const deIso = (s) => { const [a, m, d] = s.split("-").map(Number); return new Date(a, m - 1, d); };
const suma = (s, n) => { const d = deIso(s); d.setDate(d.getDate() + n); return iso(d); };
const valida = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s || "") && !Number.isNaN(deIso(s).getTime());

/** El día anterior o siguiente de entreno: el domingo no se entrena. */
function paso(s, dir) {
  let d = suma(s, dir);
  if (deIso(d).getDay() === 0) d = suma(d, dir);
  return d;
}

function relativo(s, hoy) {
  if (s === hoy) return "Hoy";
  if (s === suma(hoy, 1)) return "Mañana";
  if (s === suma(hoy, -1)) return "Ayer";
  const n = DIAS[deIso(s).getDay()];
  return n[0].toUpperCase() + n.slice(1);
}

function larga(s, hoy) {
  const d = deIso(s);
  const anio = s.slice(0, 4) !== hoy.slice(0, 4) ? ` de ${d.getFullYear()}` : "";
  return `${DIAS[d.getDay()]} ${d.getDate()} de ${MESES[d.getMonth()]}${anio}`;
}

const corta = (s) => { const d = deIso(s); return `${d.getDate()} ${MES[d.getMonth()]}`; };

/** «del 24 al 27 nov», o nada si es solo ese día. */
function rango(f) {
  if (f.fecha_inicio === f.fecha_fin) return "";
  const a = deIso(f.fecha_inicio), b = deIso(f.fecha_fin);
  const anio = a.getFullYear() !== b.getFullYear() ? ` ${b.getFullYear()}` : "";
  const desde = a.getMonth() === b.getMonth() && !anio ? `${a.getDate()}` : corta(f.fecha_inicio);
  return `del ${desde} al ${corta(f.fecha_fin)}${anio}`;
}

/** «Todo el día», «Mañana», «M1 · 8:30–10:00»… */
function parte(f) {
  const horas = f.hora_desde || f.hora_hasta ? `${f.hora_desde || "…"}–${f.hora_hasta || "…"}` : "";
  const amb = AMBITO[f.ambito] || f.ambito;
  if (horas && f.ambito === "DIA") return horas;
  return horas ? `${amb} · ${horas}` : amb;
}

function apuntada(f, hoy) {
  if (!f.created_at) return f.apuntada_por || "";
  const d = new Date(f.created_at);
  const hora = d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
  const dia = iso(d) === hoy ? "hoy" : iso(d) === suma(hoy, -1) ? "ayer" : corta(iso(d));
  return `${f.apuntada_por ? `${f.apuntada_por} · ` : ""}${dia} ${hora}`;
}

function tipo(f) {
  if (f.estado === "EN_TORNEO") return "torneo";
  if (["LESION", "ENFERMEDAD", "PRUEBA_MEDICA"].includes(f.subtipo)) return "salud";
  return "otra";
}

const iniciales = (n) => n.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join("").toUpperCase();

function Avatar({ jugador }) {
  if (jugador.foto) return <img className="avatar player fd-avatar" src={jugador.foto} alt="" />;
  return <span className="avatar player fd-avatar" aria-hidden="true">{iniciales(jugador.nombre)}</span>;
}

function Jugador({ item, hoy }) {
  return (
    <li className="fd-jug">
      <Avatar jugador={item.jugador} />
      <div className="fd-jug-txt">
        <div className="fd-jug-nombre">
          {item.jugador.nombre}
          {item.jugador.division ? <span className="fd-div">D{item.jugador.division}</span> : null}
        </div>
        {item.faltas.map((f) => (
          <div key={f.id} className="fd-falta">
            <div className="fd-falta-linea">
              <span className={`fd-motivo fd-${tipo(f)}`}>{f.motivo}</span>
              <span className="fd-parte">{parte(f)}</span>
              {rango(f) && <span className="fd-rango">{rango(f)}</span>}
            </div>
            {f.nota && <div className="fd-nota">{f.nota}</div>}
            <div className="fd-meta">
              {apuntada(f, hoy)}
              {f.tras_corte && <span className="fd-corte">tras el corte</span>}
            </div>
          </div>
        ))}
      </div>
    </li>
  );
}

function Grupo({ g, hoy, unico }) {
  return (
    <article className="fd-grupo">
      <header className="fd-grupo-head">
        <span className="fd-ent">{g.entrenador.nombre}</span>
        <span className={`fd-cuenta${g.faltan.length ? " hay" : ""}`}>
          {g.faltan.length} de {g.alumnos}
        </span>
      </header>
      {g.entrenador_fuera.map((v) => (
        <p key={v.id} className="fd-ent-fuera">
          {/* En una columna compartida («Mario / Jorge») se dice cuál de los dos. */}
          {g.entrenador.ids.length > 1 ? <><b>{v.entrenador}</b> no está</> : <b>No está</b>}
          {v.motivo ? ` · ${v.motivo}` : ""} · {parte(v).toLowerCase()}
          {rango(v) ? ` · ${rango(v)}` : ""}
        </p>
      ))}
      {g.faltan.length > 0 ? (
        <ul className="fd-lista">
          {g.faltan.map((x) => <Jugador key={x.jugador.id} item={x} hoy={hoy} />)}
        </ul>
      ) : unico ? (
        <p className="fd-nadie">Nadie de tu grupo falta este día.</p>
      ) : null}
    </article>
  );
}

function Bloque({ b, hoy, conTitulo }) {
  const conAlgo = b.grupos.filter((g) => g.faltan.length || g.entrenador_fuera.length);
  const sinNada = b.grupos.filter((g) => !g.faltan.length && !g.entrenador_fuera.length);
  const color = b.coach?.color;
  return (
    <section className={`fd-bloque${color ? ` color-${color}` : ""}`}>
      {conTitulo && b.coach && (
        <h2 className="fd-bloque-tit">
          <span className="fd-punto" aria-hidden="true" />
          Grupo {b.coach.color_nombre.toLowerCase()}
          <span className="fd-bloque-coach">{b.coach.nombre}</span>
        </h2>
      )}
      {conAlgo.map((g) => <Grupo key={g.entrenador.id} g={g} hoy={hoy} />)}
      {sinNada.length > 0 && (
        <p className="fd-sin">
          <span>Sin faltas:</span> {sinNada.map((g) => g.entrenador.nombre).join(", ")}
        </p>
      )}
    </section>
  );
}

export default function FaltasDelDiaPage() {
  const [hoy, setHoy] = useState(() => iso(new Date()));
  const [fecha, setFecha] = useState(null);
  const [datos, setDatos] = useState(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState(null);
  const pedida = useRef(null);

  // La fecha va en la dirección (?fecha=), para volver al mismo día al recargar.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search).get("fecha");
    setFecha(valida(p) ? p : iso(new Date()));
  }, []);

  const cargar = useCallback(async (f) => {
    pedida.current = f;
    setCargando(true);
    setError(null);
    try {
      const d = await getFaltasDelDia(f);
      if (pedida.current === f) setDatos(d);
    } catch (e) {
      if (pedida.current === f) setError(String(e.message || e));
    } finally {
      if (pedida.current === f) setCargando(false);
    }
  }, []);

  useEffect(() => {
    if (!fecha) return;
    const url = new URL(window.location.href);
    if (fecha === iso(new Date())) url.searchParams.delete("fecha");
    else url.searchParams.set("fecha", fecha);
    window.history.replaceState(null, "", url.pathname + url.search);
    cargar(fecha);
  }, [fecha, cargar]);

  // Al volver a la pestaña (el móvil en el bolsillo), se pide otra vez: las
  // faltas se apuntan durante el día. Y si ha cambiado el día, «Hoy» también.
  useEffect(() => {
    const volver = () => {
      if (document.visibilityState !== "visible") return;
      setHoy(iso(new Date()));
      if (pedida.current) cargar(pedida.current);
    };
    document.addEventListener("visibilitychange", volver);
    return () => document.removeEventListener("visibilitychange", volver);
  }, [cargar]);

  const alcance = datos?.alcance;
  const deQuien = alcance === "club" ? "todo el club"
    : alcance === "color" && datos.bloques[0]?.coach
      ? `grupo ${datos.bloques[0].coach.color_nombre.toLowerCase()}`
      : "tu grupo";
  const vacio = datos && datos.bloques.length === 0 && datos.sin_grupo.length === 0;

  return (
    <div className="fd">
      <div className="fd-cabecera">
        <h1>Faltas del día</h1>
        <Link href="/faltas" className="fd-apuntar">Apuntar una falta</Link>
      </div>

      {fecha && (
        <div className="fd-dia">
          <button type="button" className="fd-flecha" onClick={() => setFecha(paso(fecha, -1))}
                  aria-label="Día anterior">‹</button>
          <label className="fd-fecha">
            <span className="fd-rel">{relativo(fecha, hoy)}</span>
            <span className="fd-larga">{larga(fecha, hoy)}</span>
            <input type="date" value={fecha} aria-label="Elegir día"
                   onChange={(e) => valida(e.target.value) && setFecha(e.target.value)} />
          </label>
          <button type="button" className="fd-flecha" onClick={() => setFecha(paso(fecha, 1))}
                  aria-label="Día siguiente">›</button>
        </div>
      )}
      {fecha && fecha !== hoy && (
        <button type="button" className="fd-hoy" onClick={() => setFecha(hoy)}>Volver a hoy</button>
      )}

      {error && <p className="err">{error}</p>}
      {!datos ? (!error && <p className="msg">Cargando…</p>) : (
        <div className={`fd-cuerpo${cargando ? " fd-cargando" : ""}`} aria-busy={cargando}>
          <p className="fd-resumen">
            {datos.total_faltan === 0
              ? <>Nadie falta · {deQuien}</>
              : <><b>{datos.total_faltan}</b> {datos.total_faltan === 1 ? "falta" : "faltan"} de {datos.total_alumnos} · {deQuien}</>}
          </p>

          {vacio && <p className="fd-nadie">No llevas ningún grupo.</p>}

          {datos.bloques.map((b, i) => (
            alcance === "grupo"
              ? b.grupos.map((g) => (
                <section key={g.entrenador.id} className={`fd-bloque${b.coach?.color ? ` color-${b.coach.color}` : ""}`}>
                  <Grupo g={g} hoy={hoy} unico />
                </section>
              ))
              : <Bloque key={b.coach?.id ?? `b${i}`} b={b} hoy={hoy} conTitulo />
          ))}

          {datos.sin_grupo.length > 0 && (
            <section className="fd-bloque fd-sin-grupo">
              <h2 className="fd-bloque-tit"><span className="fd-punto" aria-hidden="true" />Sin grupo de color</h2>
              <article className="fd-grupo">
                <ul className="fd-lista">
                  {datos.sin_grupo.map((x) => <Jugador key={x.jugador.id} item={x} hoy={hoy} />)}
                </ul>
              </article>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
