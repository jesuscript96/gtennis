"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { getAgendaJugador, getReglasJugador, getUser, guardarReglaJugador, jugadorExtra, quitarExtra, resource } from "../lib/api";
import { roleRank } from "../lib/perms";
import CalendarioAusencias from "./CalendarioAusencias";
import PanelTurnos, { SemanaHabitual } from "./PanelTurnos";

// Sigue en la lista (es de alguien) pero ya no entrena: tiene fecha de baja
// pasada. Comparar el texto ISO basta.
const hoyIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const noEntrena = (j) => Boolean(j.fecha_baja && j.fecha_baja < hoyIso());

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
  const [fijos, setFijos] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.list("?sin_invitados=1").then(setJugadores).catch((e) => setError(e.message));
    resource("turnos").list().then(setTurnos).catch(() => {});
  }, [api]);

  const visibles = jugadores.filter((j) =>
    j.nombre.toLowerCase().includes(busca.trim().toLowerCase())
  );
  // Los que gestiona (es su responsable o comparte la gestión) van primero y
  // marcados; debajo, los que entrena y los de los demás de su grupo de
  // gestión, que también puede editar.
  const yo = getUser();
  const esCoach = roleRank(yo) >= 2;
  const esDir = roleRank(yo) >= 3;
  // «Mis jugadores» significa lo mismo en toda la aplicación (10/11/2026): los
  // de tu columna de Grupos. Lo calcula el servidor (`relacion`). Con los que
  // entrenas por porcentaje salen aparte.
  // El que se abrió desde «Sin grupo» se queda ahí aunque ya tenga grupo: si
  // saltara de lista a mitad de rellenarlo, se perdería de vista.
  const sinGestion = esCoach
    ? visibles.filter((j) => fijos.includes(j.id) || j.relacion === "sin_grupo")
    : [];
  const deLista = (rel) => visibles.filter((j) => j.relacion === rel && !sinGestion.includes(j));
  const mios = deLista("mio");
  const delGrupo = deLista("grupo");
  const entrena = deLista("entrena");
  const resto = deLista("otro");

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

  const fila = (j, gestion) => {
    const activo = abierto === j.id;
    return (
      <li key={j.id} className={activo ? "abierto" : ""}>
        <button type="button" className="fila-jugador"
          aria-expanded={activo}
          onClick={() => {
            if (sinGestion.includes(j) && !fijos.includes(j.id)) setFijos([...fijos, j.id]);
            setAbierto(activo ? null : j.id);
          }}>
          <span className="nombre">
            {j.nombre}
            {gestion && <span className="marca-gestion">Gestión</span>}
            {noEntrena(j) && <span className="marca-baja">No entrena</span>}
          </span>
          <span className="resumen">
            {resumen(j)}
            {/* El coach ve a todos, y el entrenador a los de su grupo de
                gestión: les sirve saber quién lleva a cada uno. */}
            {(esCoach || !gestion) && j.entrenador_nombre && ` · gestiona ${[j.entrenador_nombre, ...(j.cogestores_nombres || [])].join(" y ")}`}
          </span>
          <span className="chevron" aria-hidden="true">{activo ? "−" : "+"}</span>
        </button>

        {activo && (
          <div className="detalle-jugador">
            {esCoach && <FichaDeportiva jugador={j} esDir={esDir} />}
            <AgendaJugador jugador={j} turnos={turnos} onGuardado={actualizar}
              cambiaHorario={esCoach} />

            <div className="bloque-faltas">
              <h3>Faltas</h3>
              <CalendarioAusencias jugador={j} />
            </div>

            {yo?.ve_reglas_jugador && <ReglasJugador jugador={j} />}
          </div>
        )}
      </li>
    );
  };

  return (
    <div className="page">
      <h1>{esDir ? "Jugadores" : "Mis jugadores"}</h1>
      <p className="hint">
        {esCoach
          ? "Declara cuándo entrena cada uno y sus faltas."
          : "Declara sus faltas y los días que vienen además."} Toca un nombre para
        abrirlo. En el calendario puedes marcar varios días —sueltos o
        arrastrando— y declararlos de una vez.
      </p>

      <input className="buscador" placeholder="Buscar jugador…" value={busca}
        onChange={(e) => setBusca(e.target.value)} />

      {error && <p className="error">{error}</p>}

      {sinGestion.length > 0 && <>
        <h2 className="titulo-lista">Sin grupo <small>({sinGestion.length})</small></h2>
        <p className="hint">Altas nuevas: ponlas en un grupo desde Grupos y completa aquí su ficha deportiva.</p>
        <ul className="lista-jugadores">{sinGestion.map((j) => fila(j, false))}</ul>
      </>}

      {[
        [mios, "Mis jugadores", "Los de tu columna en Grupos.", true],
        [delGrupo, esCoach ? "De tu grupo" : "De tu grupo de color", "Los gestiona otro entrenador de tu grupo.", false],
        [entrena, "Entrenas por porcentaje", "No los gestionas, pero entrenan contigo.", false],
        [resto, sinGestion.length || mios.length || delGrupo.length || entrena.length ? "Resto de jugadores" : null, null, false],
      ].map(([lista, titulo, ayuda, gestion]) => lista.length > 0 && (
        <div key={titulo || "resto"}>
          {titulo && <h2 className="titulo-lista">{titulo} <small>({lista.length})</small></h2>}
          {ayuda && <p className="hint">{ayuda}</p>}
          <ul className="lista-jugadores">{lista.map((j) => fila(j, gestion))}</ul>
        </div>
      ))}

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
function AgendaJugador({ jugador, turnos, onGuardado, cambiaHorario }) {
  const [datos, setDatos] = useState(null);
  // «Esta semana» (lo real o lo previsto) o «habitual» (su semana tipo).
  const [vista, setVista] = useState("semana");
  const [declarando, setDeclarando] = useState(false);
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
  // Al cambiar su horario, lo previsto de esta semana cambia con él.
  const firmaHorario = JSON.stringify([jugador.turno_manana, jugador.turno_tarde, jugador.horario]);
  const primera = useRef(true);
  useEffect(() => {
    if (primera.current) { primera.current = false; return; }
    cargar();
  }, [firmaHorario]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error && !datos) return <p className="error">{error}</p>;
  if (!datos) return <p className="hint">Cargando su agenda…</p>;

  const hoy = datos.hoy;
  const conAlgo = datos.dias.some((d) => d.sesiones.length || (d.extras || []).length);
  // El miércoles por la tarde el club no abre: ese día solo hay mañanas.
  const franjasDe = (d) => (d.dia === 2 ? ["M1", "M2"] : ["M1", "M2", "T1", "T2"]);
  // Solo de hoy en adelante: apuntarle «además» un día que ya pasó no sirve.
  const diasPosibles = datos.dias.filter((d) => d.alta && d.dia <= 4 && (!hoy || d.dia >= hoy.dia));
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
        <h3>{vista === "habitual" ? "Semana habitual" : "Esta semana"}</h3>
        {vista === "habitual" ? (
          <SemanaHabitual jugador={jugador} turnos={turnos} />
        ) : (<>
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
                        s.falta ? "con-falta-tachada" : "",
                      ].filter(Boolean).join(" ")}
                        title={s.falta ? `Falta: ${s.falta.motivo}` : undefined}>
                        {s.hora_inicio} {s.turno}
                        {s.pista ? ` · P${s.pista}` : ""}
                        {s.entrenador ? ` · ${s.entrenador}` : ""}
                      </span>
                    ))}
                    {(d.extras || []).map((t) => (
                      <span key={`x-${t}`} className="chip-extra">
                        viene además · {t}
                        <button type="button" disabled={ocupado}
                          onClick={() => quitar(d, t)}>Quitar</button>
                      </span>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>)}

        {error && datos && !declarando && <p className="error">{error}</p>}
        <div className="acciones-horario">
          <button type="button" className="btn ghost sm"
            onClick={() => setVista(vista === "habitual" ? "semana" : "habitual")}>
            {vista === "habitual" ? "Ver esta semana" : "Ver semana habitual"}
          </button>
          <button type="button" className={declarando ? "btn sm" : "btn ghost sm"}
            aria-expanded={declarando} onClick={() => setDeclarando(!declarando)}>
            Declarar algo distinto
          </button>
        </div>
      </div>

      {declarando && (
        <div className="declarar-distinto">
          <div className="dd-cab">
            <h3>Declarar algo distinto</h3>
            <button type="button" className="btn ghost sm"
              onClick={() => setDeclarando(false)}>Cerrar</button>
          </div>

          <section>
            <h4>Solo esta semana</h4>
            {diasPosibles.length > 0 ? (
              <form className="agenda-extra" onSubmit={apuntarExtra}>
                <span className="etiqueta">Viene además el</span>
                <select value={diaElegido ? String(diaElegido.dia) : ""}
                  onChange={(e) => setExtraDia(e.target.value)}>
                  {diasPosibles.map((d) => <option key={d.dia} value={d.dia}>{d.nombre}</option>)}
                </select>
                <span className="etiqueta">en</span>
                <select value={extraTurno} onChange={(e) => setExtraTurno(e.target.value)}>
                  {(diaElegido ? franjasDe(diaElegido) : []).map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
                <button type="submit" className="btn sm" disabled={ocupado || !diaElegido}>
                  Apuntar
                </button>
              </form>
            ) : (
              <p className="hint">Esta semana ya no quedan días para apuntarle.</p>
            )}
            {mensaje && <p className="ok-msg">{mensaje}</p>}
            {error && datos && <p className="error">{error}</p>}
            <p className="hint">Si algún día no viene, márcalo en Faltas, más abajo.</p>
          </section>

          <section>
            <h4>Todas las semanas</h4>
            {/* El horario habitual lo cambian su head coach o dirección
                (30/10/2026); el entrenador lo ve en «Ver semana habitual». */}
            {cambiaHorario
              ? <PanelTurnos jugador={jugador} onGuardado={onGuardado} compacto />
              : <p className="hint">Su horario habitual lo cambian su head coach o dirección.</p>}
          </section>
        </div>
      )}
    </div>
  );
}

function Sesion({ s }) {
  return (
    <li className={["sesion", s.previsto ? "previsto" : "", s.estado === "EXTRA" ? "extra" : "",
      s.falta ? "con-falta-tachada" : ""].filter(Boolean).join(" ")}>
      <span className="hora">{s.hora_inicio}–{s.hora_fin}</span>
      {s.falta && <span className="falta-tag">falta · {s.falta.motivo}</span>}
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


const VECINDAD = [
  ["CLUB", "La del club (la horquilla general)"],
  ["SOLO", "Solo su división"],
  ["ARRIBA", "Su división y la de encima (D−1)"],
  ["ABAJO", "Su división y la de debajo (D+1)"],
  ["AMBAS", "Su división y las dos vecinas (±1)"],
];
const PAREJA = [
  ["", "— le da igual —"],
  ["ARRIBA", "Hacia arriba · con la división mejor (D−1)"],
  ["ABAJO", "Hacia abajo · con la división de debajo (D+1)"],
];

/**
 * Lo deportivo de la ficha, para el head coach (06/10/2026).
 *
 * Administración da de alta al alumno con sus datos; la división, quién le
 * gestiona y con qué niveles entrena lo pone dirección deportiva. El head
 * coach no tiene la tabla de fichas de dirección, así que lo rellena aquí,
 * sin salir de su lista. Cada cambio se guarda al momento.
 */
function FichaDeportiva({ jugador: j, esDir }) {
  const [divisiones, setDivisiones] = useState([]);
  // Los entrenadores que puede elegir para su grupo: el head coach, los de su
  // color (lo que le devuelve el servidor); dirección, todos.
  const [entrenadores, setEntrenadores] = useState([]);
  const [revisar, setRevisar] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [actual, setActual] = useState(j);

  useEffect(() => {
    resource("divisiones").list().then(setDivisiones).catch(() => {});
    resource("entrenadores").list()
      .then((l) => setEntrenadores([...l].sort((a, b) => a.nombre.localeCompare(b.nombre, "es"))))
      .catch(() => {});
  }, []);
  useEffect(() => setActual(j), [j]);

  const guardar = async (cambio) => {
    setGuardando(true);
    setError("");
    setMsg("");
    try {
      const r = await resource("jugadores").update(j.id, cambio);
      setActual(r);
      setRevisar(Boolean(r.revisar_porcentajes));
      setMsg("Guardado.");
    } catch (e) {
      setError(e.message);
    } finally {
      setGuardando(false);
    }
  };

  const div = divisiones.find((d) => d.id === actual.division);
  const pendiente = !actual.division || !actual.entrenador_responsable;
  const [abiertaAlEntrar] = useState(pendiente);
  const comparten = actual.cogestores_nombres || [];
  // Puede cambiar el grupo si es dirección o si el alumno es de su color, no
  // tiene grupo o su gestor está de baja (la misma regla que en Grupos; el
  // servidor la comprueba igual).
  const actualEnt = entrenadores.find((e) => e.id === actual.entrenador_responsable);
  // (Al head coach el servidor solo le da los de su color: si el del alumno
  // está en la lista, es de su color.)
  const puedeGrupo = esDir || !actual.entrenador_responsable || Boolean(actualEnt);
  const opciones = entrenadores.filter((e) => e.activo || e.id === actual.entrenador_responsable);

  return (
    <details className="ficha-deportiva" open={abiertaAlEntrar}>
      <summary>
        Ficha deportiva
        {pendiente && <span className="marca-baja">Sin completar</span>}
      </summary>
      {error && <p className="error">{error}</p>}
      {/* El grupo también aquí, con la misma regla que en Grupos (13/11/2026);
          compartir la gestión, la división y el ranking, en Grupos. */}
      <div className="fila-form">
        <label>Entrenador (su grupo)
          {puedeGrupo ? (
            <select value={actual.entrenador_responsable || ""} disabled={guardando}
              onChange={(e) => guardar({ entrenador_responsable: e.target.value ? Number(e.target.value) : null })}>
              <option value="">— sin grupo —</option>
              {opciones.map((e) => <option key={e.id} value={e.id}>{e.nombre}{e.activo ? "" : " (de baja)"}</option>)}
            </select>
          ) : (
            <span className="ficha-solo-lectura">{actual.entrenador_nombre} · es de otro grupo de color</span>
          )}
        </label>
      </div>
      {revisar && (
        <p className="hint">
          Su nuevo entrenador no está entre los que le entrenan:{" "}
          <Link href={`/jugador-responsables?jugador=${j.id}&nombre=${encodeURIComponent(j.nombre)}`}>revisa sus porcentajes</Link>.
        </p>
      )}
      <dl className="ficha-lectura">
        {comparten.length > 0 && (
          <div><dt>Comparte la gestión</dt><dd>{comparten.join(" y ")} · <Link href="/grupos">se cambia en Grupos</Link></dd></div>
        )}
        <div><dt>División</dt><dd>{div ? (div.nombre || `División ${div.nivel}`) : "—"}{esDir ? <> · <Link href="/grupos?vista=division">se cambia en Grupos</Link></> : " · la cambia dirección"}</dd></div>
      </dl>
      <div className="fila-form">
        <label>Con qué divisiones entrena
          <select value={actual.vecindad || "CLUB"} disabled={guardando}
            onChange={(e) => guardar({ vecindad: e.target.value })}>
            {VECINDAD.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
          </select>
        </label>
        <label>Se empareja preferentemente
          <select value={actual.pareja_division || ""} disabled={guardando}
            onChange={(e) => guardar({ pareja_division: e.target.value || null })}>
            {PAREJA.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
          </select>
        </label>
      </div>
      <p className="hint">
        La D1 es la más alta. Las franjas de mañana y tarde están más abajo, en
        «Declarar algo distinto → Todas las semanas».
        {msg && <span className="ok-msg"> {msg}</span>}
      </p>
      <div className="accesos">
        <Link href={`/jugador-responsables?jugador=${j.id}&nombre=${encodeURIComponent(j.nombre)}`}>
          Con quién entrena y en qué porcentaje →
        </Link>
      </div>
    </details>
  );
}


/**
 * Las reglas del jugador, juntas (10/11/2026): con quién no coincide, con qué
 * entrenador va siempre o nunca, su pareja, su entrenador por franja y su
 * superficie. Solo dirección y head coaches.
 */
function ReglasJugador({ jugador }) {
  const [r, setR] = useState(null);
  const [jugadores, setJugadores] = useState([]);
  const [entrenadores, setEntrenadores] = useState([]);
  const [turnos, setTurnos] = useState([]);
  const [error, setError] = useState("");
  const [nuevo, setNuevo] = useState({ tipo: "rencilla" });
  const api = resource("jugadores");

  useEffect(() => {
    getReglasJugador(jugador.id).then(setR).catch((e) => setError(e.message));
  }, [jugador.id]);

  async function cargarListas() {
    if (jugadores.length) return;
    const [js, es, ts] = await Promise.all([
      resource("jugadores").list(), resource("entrenadores").list(), resource("turnos").list()]);
    setJugadores(js.filter((x) => x.id !== jugador.id));
    setEntrenadores(es.filter((e) => e.activo));
    setTurnos(ts);
  }

  async function enviar(cuerpo, metodo = "POST") {
    setError("");
    try { setR(await guardarReglaJugador(jugador.id, cuerpo, metodo)); }
    catch (e) { setError(e.message); }
  }

  if (!r) return error ? <p className="error">{error}</p> : null;
  const fila = (tipo, x, texto) => (
    <li key={`${tipo}-${x.id}`}>{texto}
      <button type="button" className="btn ghost sm" onClick={() => enviar({ tipo, id: x.id }, "DELETE")}>Quitar</button>
    </li>
  );
  const tipos = {
    rencilla: ["No coincide con", "jugador"],
    contrato: ["Contrato de patrocinio con", "entrenador"],
    veto: ["No entrena con", "entrenador"],
    pareja: ["Entrena con (pareja)", "jugador"],
    franja: ["Entrenador por franja", "entrenador"],
  };
  const quien = tipos[nuevo.tipo]?.[1];

  return (
    <details className="ficha-deportiva" onToggle={(e) => e.target.open && cargarListas()}>
      <summary>Reglas</summary>
      {error && <p className="error">{error}</p>}
      <ul className="lista-reglas">
        {r.rencillas.map((x) => fila("rencilla", x, `No coincide con ${x.nombre}${x.motivo ? ` (${x.motivo})` : ""}`))}
        {r.contratos.map((x) => fila("contrato", x, `Contrato con ${x.nombre} · ${x.tipo_display}`))}
        {r.vetos.map((x) => fila("veto", x, `No entrena con ${x.nombre}`))}
        {r.parejas.map((x) => fila("pareja", x, `Pareja: ${x.nombre} · ${x.tipo_display}`))}
        {r.franjas.map((x) => fila("franja", x, `En ${x.turno_codigo}, con ${x.nombre} · ${x.tipo_display}`))}
        {r.superficie && fila("superficie", r.superficie, `Superficie: ${r.superficie.superficie === "RESINA" ? "resina" : "tierra"}${r.superficie.estricta ? " (siempre)" : " (si se puede)"}`)}
        {!r.rencillas.length && !r.contratos.length && !r.vetos.length && !r.parejas.length && !r.franjas.length && !r.superficie
          && <li className="hint">Sin reglas.</li>}
      </ul>
      <form className="fila-form" onSubmit={(e) => { e.preventDefault(); enviar(nuevo); }}>
        <label>Añadir
          <select value={nuevo.tipo} onChange={(e) => setNuevo({ tipo: e.target.value })}>
            {Object.entries(tipos).map(([k, [t]]) => <option key={k} value={k}>{t}</option>)}
            <option value="superficie">Superficie fija</option>
          </select>
        </label>
        {quien === "jugador" && (
          <label>Jugador
            <select required value={nuevo.jugador || ""} onChange={(e) => setNuevo({ ...nuevo, jugador: e.target.value })}>
              <option value="">—</option>
              {jugadores.map((x) => <option key={x.id} value={x.id}>{x.nombre}</option>)}
            </select>
          </label>
        )}
        {quien === "entrenador" && (
          <label>Entrenador
            <select required value={nuevo.entrenador || ""} onChange={(e) => setNuevo({ ...nuevo, entrenador: e.target.value })}>
              <option value="">—</option>
              {entrenadores.map((x) => <option key={x.id} value={x.id}>{x.nombre}</option>)}
            </select>
          </label>
        )}
        {nuevo.tipo === "franja" && (
          <label>Franja
            <select required value={nuevo.turno || ""} onChange={(e) => setNuevo({ ...nuevo, turno: e.target.value })}>
              <option value="">—</option>
              {turnos.map((t) => <option key={t.id} value={t.id}>{t.codigo}</option>)}
            </select>
          </label>
        )}
        {nuevo.tipo === "contrato" && (
          <label>Tipo
            <select value={nuevo.tipo_contrato || "DURO"} onChange={(e) => setNuevo({ ...nuevo, tipo_contrato: e.target.value })}>
              <option value="DURO">Siempre con él</option><option value="BLANDO">Cuando se pueda</option>
            </select>
          </label>
        )}
        {nuevo.tipo === "pareja" && (
          <label>Tipo
            <select value={nuevo.tipo_pareja || "SOFT"} onChange={(e) => setNuevo({ ...nuevo, tipo_pareja: e.target.value })}>
              <option value="SOFT">Si se puede</option><option value="HARD">Siempre en la misma pista</option>
            </select>
          </label>
        )}
        {nuevo.tipo === "superficie" && <>
          <label>Superficie
            <select required value={nuevo.superficie || ""} onChange={(e) => setNuevo({ ...nuevo, superficie: e.target.value })}>
              <option value="">—</option><option value="TIERRA">Tierra</option><option value="RESINA">Resina</option>
            </select>
          </label>
          <label className="check"><input type="checkbox" checked={Boolean(nuevo.estricta)}
            onChange={(e) => setNuevo({ ...nuevo, estricta: e.target.checked })} /> Siempre</label>
        </>}
        {nuevo.tipo === "rencilla" && (
          <label>Motivo <input value={nuevo.motivo || ""} onChange={(e) => setNuevo({ ...nuevo, motivo: e.target.value })} /></label>
        )}
        <button className="btn sm" type="submit">Añadir</button>
      </form>
    </details>
  );
}
