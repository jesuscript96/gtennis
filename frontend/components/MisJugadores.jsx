"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { getAgendaJugador, jugadorExtra, quitarExtra, resource } from "../lib/api";
import CalendarioAusencias from "./CalendarioAusencias";
import PanelTurnos from "./PanelTurnos";

/**
 * Los jugadores de un entrenador: una lista de nombres y nada más.
 *
 * El entrenador no gestiona la ficha del alumno, así que no tiene sentido
 * enseñarle una tabla de campos vacíos con guiones. Lo único que declara es
 * cuándo entrena cada uno, y eso se abre al desplegar su fila.
 */
export default function MisJugadores() {
  const api = useMemo(() => resource("jugadores"), []);
  const [jugadores, setJugadores] = useState([]);
  const [turnos, setTurnos] = useState([]);
  const [abierto, setAbierto] = useState(null);
  const [busca, setBusca] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.list().then(setJugadores).catch((e) => setError(e.message));
    resource("turnos").list().then(setTurnos).catch(() => {});
  }, [api]);

  const visibles = jugadores.filter((j) =>
    j.nombre.toLowerCase().includes(busca.trim().toLowerCase())
  );

  function resumen(j) {
    const m = turnos.find((t) => t.id === j.turno_manana);
    const t = turnos.find((t2) => t2.id === j.turno_tarde);
    const partes = [m && m.codigo, t && t.codigo].filter(Boolean);
    const excepciones = (j.horario || []).length;
    if (!partes.length && !excepciones) return "sin turnos declarados";
    return partes.join(" + ") + (excepciones ? ` · ${excepciones} día${excepciones > 1 ? "s" : ""} distintos` : "");
  }

  const actualizar = (nuevo) =>
    setJugadores((prev) => prev.map((x) => (x.id === nuevo.id ? nuevo : x)));

  return (
    <div className="page">
      <h1>Mis jugadores</h1>
      <p className="hint">
        Declara cuándo entrena cada uno. Toca un nombre para abrirlo.
      </p>

      <input className="buscador" placeholder="Buscar jugador…" value={busca}
        onChange={(e) => setBusca(e.target.value)} />

      {error && <p className="error">{error}</p>}

      <ul className="lista-jugadores">
        {visibles.map((j) => {
          const activo = abierto === j.id;
          return (
            <li key={j.id} className={activo ? "abierto" : ""}>
              <button type="button" className="fila-jugador"
                aria-expanded={activo}
                onClick={() => setAbierto(activo ? null : j.id)}>
                <span className="nombre">{j.nombre}</span>
                <span className="resumen">{resumen(j)}</span>
                <span className="chevron" aria-hidden="true">{activo ? "−" : "+"}</span>
              </button>

              {activo && (
                <div className="detalle-jugador">
                  <AgendaJugador jugador={j} />

                  <PanelTurnos jugador={j} onGuardado={actualizar} compacto />

                  <div className="bloque-faltas">
                    <h3>Faltas</h3>
                    <CalendarioAusencias jugador={j} />
                  </div>

                  <div className="accesos">
                    <Link href={`/ausencias?jugador=${j.id}`}>Parte de esta semana</Link>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>

      {!visibles.length && <p className="hint">Ningún jugador con ese nombre.</p>}
    </div>
  );
}


/**
 * Lo que este alumno tiene hoy y lo que tiene esta semana.
 *
 * Es la primera pregunta del entrenador cuando abre a uno de los suyos —
 * «¿cuándo le toca y con quién?»— y hasta ahora había que ir al cuadrante
 * general a buscarlo. Si dirección todavía no ha generado la semana se enseña
 * lo previsto por su horario, dicho como tal para no confundirlo con lo real.
 */
function AgendaJugador({ jugador }) {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [extraDia, setExtraDia] = useState("");
  const [extraTurno, setExtraTurno] = useState("M1");
  const [mensaje, setMensaje] = useState("");
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(async () => {
    try {
      setDatos(await getAgendaJugador(jugador.id));
    } catch (e) { setError(e.message); }
  }, [jugador.id]);

  useEffect(() => { setDatos(null); setError(""); cargar(); }, [cargar]);

  if (error && !datos) return <p className="error">{error}</p>;
  if (!datos) return <p className="hint">Cargando su agenda…</p>;

  const hoy = datos.hoy;
  const conAlgo = datos.dias.some((d) => d.sesiones.length || (d.extras || []).length);
  // El miércoles por la tarde el club no abre: ese día solo hay mañanas.
  const franjasDe = (d) => (d.dia === 2 ? ["M1", "M2"] : ["M1", "M2", "T1", "T2"]);
  const diasPosibles = datos.dias.filter((d) => d.alta && d.dia <= 4);
  const diaElegido = diasPosibles.find((d) => String(d.dia) === extraDia) || diasPosibles[0];

  async function apuntarExtra(e) {
    e.preventDefault();
    if (!diaElegido) return;
    const posibles = franjasDe(diaElegido);
    const turno = posibles.includes(extraTurno) ? extraTurno : posibles[0];
    setOcupado(true); setMensaje(""); setError("");
    try {
      const r = await jugadorExtra(jugador.id, { fecha: diaElegido.fecha, turno });
      setMensaje(r.mensaje || "Apuntado.");
      await cargar();
    } catch (err) { setError(err.message); }
    setOcupado(false);
  }

  async function quitar(d, turno) {
    setOcupado(true); setMensaje(""); setError("");
    try {
      await quitarExtra(jugador.id, { fecha: d.fecha, turno });
      await cargar();
    } catch (err) { setError(err.message); }
    setOcupado(false);
  }

  return (
    <div className="agenda-jugador">
      <div className="agenda-hoy">
        <h3>Hoy{hoy ? ` · ${hoy.nombre}` : ""}</h3>
        {!hoy || !hoy.sesiones.length ? (
          <p className="hint">
            {hoy && hoy.ausencia
              ? `No entrena: ${hoy.ausencia.estado.toLowerCase()}.`
              : "Hoy no le toca entrenar."}
          </p>
        ) : (
          <ul className="sesiones">
            {hoy.sesiones.map((s, i) => <Sesion key={i} s={s} />)}
          </ul>
        )}
        {hoy && hoy.ausencia && hoy.sesiones.length > 0 && (
          <p className="hint">Tiene declarada una baja: {hoy.ausencia.estado.toLowerCase()}.</p>
        )}
      </div>

      <div className="agenda-semana">
        <h3>Esta semana</h3>
        {!datos.hay_semana && (
          <p className="hint">
            La semana todavía no está hecha: esto es lo previsto por su horario.
          </p>
        )}
        {!conAlgo ? (
          <p className="hint">Sin entrenamientos esta semana.</p>
        ) : (
          <ul className="semana-jugador">
            {datos.dias.map((d) => (
              <li key={d.dia} className={d.es_hoy ? "hoy" : ""}>
                <span className="dia">{d.nombre.slice(0, 3)}</span>
                <div className="celdas">
                  {d.ausencia && <span className="chip-baja">{d.ausencia.estado}</span>}
                  {!d.alta && <span className="chip-baja">aún no está de alta</span>}
                  {d.sesiones.length === 0 && !(d.extras || []).length && !d.ausencia && d.alta && (
                    <span className="vacio">—</span>
                  )}
                  {d.sesiones.map((s, i) => (
                    <span key={i} className={[
                      "chip-sesion", s.previsto ? "previsto" : "", s.estado === "EXTRA" ? "extra" : "",
                    ].filter(Boolean).join(" ")}>
                      {s.hora_inicio} {s.turno}
                      {s.pista ? ` · P${s.pista}` : ""}
                      {s.entrenador ? ` · ${s.entrenador}` : ""}
                    </span>
                  ))}
                  {(d.extras || []).map((t) => (
                    <span key={`x-${t}`} className="chip-extra">
                      viene además · {t}
                      <button type="button" disabled={ocupado} title="Quitar"
                        onClick={() => quitar(d, t)}>✕</button>
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}

        {diasPosibles.length > 0 && (
          <form className="agenda-extra" onSubmit={apuntarExtra}>
            <span className="etiqueta">¿Viene además algún día?</span>
            <select value={diaElegido ? String(diaElegido.dia) : ""}
              onChange={(e) => setExtraDia(e.target.value)}>
              {diasPosibles.map((d) => <option key={d.dia} value={d.dia}>{d.nombre}</option>)}
            </select>
            <select value={extraTurno} onChange={(e) => setExtraTurno(e.target.value)}>
              {(diaElegido ? franjasDe(diaElegido) : []).map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <button type="submit" className="btn sm" disabled={ocupado || !diaElegido}>
              Apuntar
            </button>
          </form>
        )}
        {mensaje && <p className="ok-msg">{mensaje}</p>}
        {error && datos && <p className="error">{error}</p>}
      </div>
    </div>
  );
}

function Sesion({ s }) {
  return (
    <li className={["sesion", s.previsto ? "previsto" : "", s.estado === "EXTRA" ? "extra" : ""]
      .filter(Boolean).join(" ")}>
      <span className="hora">{s.hora_inicio}–{s.hora_fin}</span>
      <span className="donde">
        {s.pista ? `${s.sede} · Pista ${s.pista}` : `${s.turno} · previsto`}
      </span>
      {s.entrenador && <span className="con">con {s.entrenador}</span>}
      {s.companeros.length > 0 && (
        <span className="companeros">Comparte con {s.companeros.join(", ")}</span>
      )}
    </li>
  );
}
