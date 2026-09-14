"use client";

import { useEffect, useState } from "react";
import {
  getGrupos, grupoMover, grupoMoverEntrenador, grupoQuitar,
} from "../../../lib/api";

/**
 * El organigrama de la academia, tal y como está en el Excel de dirección:
 * cada bloque es un coach, dentro van las columnas de sus entrenadores y bajo
 * cada columna sus alumnos.
 *
 * Se reorganiza arrastrando, y cada cosa solo entra donde tiene sentido: un
 * alumno cae en una columna de entrenador, y una columna entera —el entrenador
 * con sus alumnos— cae en un bloque. Lo que se arrastra se guarda al soltarlo:
 * el alumno cambia de responsable y el entrenador de coach.
 *
 * Arrastrar no existe en el móvil, así que todo se puede hacer también
 * tocando: tocas a quien mueves y luego "Traer aquí" en el destino.
 *
 * Un alumno puede estar además en el "también entrena" de otros entrenadores
 * de su bloque —todos los capacitados para su división pueden entrenarle— y
 * eso va plegado para que no parezca que el grupo está repetido.
 */
export default function Page() {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [busca, setBusca] = useState("");
  // Lo que se está moviendo, se arrastre o se toque: { tipo, id, nombre, desde }
  const [cogido, setCogido] = useState(null);
  const [encima, setEncima] = useState(null);
  const [ocupado, setOcupado] = useState(false);

  async function cargar() {
    try {
      setDatos(await getGrupos());
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => { cargar(); }, []);

  if (!datos) {
    return (
      <div className="page grupos">
        <h1>Grupos</h1>
        {error ? <p className="err">{error}</p> : <p className="msg">Cargando…</p>}
      </div>
    );
  }

  const editable = datos.puede_editar;
  const coincide = (j) =>
    !busca.trim() || j.nombre.toLowerCase().includes(busca.trim().toLowerCase());

  async function accion(fn, mensaje) {
    setOcupado(true); setError(""); setAviso("");
    try {
      await fn();
      setAviso(mensaje);
      await cargar();
    } catch (e) {
      setError(e.message);
    }
    setOcupado(false);
  }

  // --- mover: lo mismo para el arrastre y para el toque ---------------------
  function soltarEnColumna(entrenador) {
    const q = cogido;
    limpiar();
    if (!q || q.tipo !== "jugador" || q.desde === entrenador.id) return;
    accion(
      () => grupoMover(q.id, entrenador.id),
      `${q.nombre} pasa al grupo de ${entrenador.nombre}.`
    );
  }

  function soltarEnBloque(coach) {
    const q = cogido;
    limpiar();
    const idCoach = coach ? coach.id : null;
    if (!q || q.tipo !== "entrenador" || q.desde === idCoach) return;
    accion(
      () => grupoMoverEntrenador(q.id, idCoach),
      coach
        ? `${q.nombre} y sus alumnos pasan al bloque de ${coach.nombre}.`
        : `${q.nombre} se queda fuera de los bloques.`
    );
  }

  function soltarEnSinGrupo() {
    const q = cogido;
    limpiar();
    if (!q || q.tipo !== "jugador" || !q.desde) return;
    accion(
      () => grupoQuitar(q.id, q.desde),
      `${q.nombre} se queda sin responsable.`
    );
  }

  const limpiar = () => { setCogido(null); setEncima(null); };

  // Arrastrar y tocar comparten estado: empezar a arrastrar es "coger".
  const alArrastrar = (payload) => (e) => {
    if (!editable) return;
    setCogido(payload);
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setData("text/plain", payload.nombre); } catch { /* Safari */ }
  };
  const permitirSoltar = (tipo, zona) => (e) => {
    if (!editable || cogido?.tipo !== tipo) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "move";
    if (encima !== zona) setEncima(zona);
  };
  const alSoltar = (fn) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    fn();
  };

  const moviendoJugador = cogido?.tipo === "jugador";
  const moviendoEntrenador = cogido?.tipo === "entrenador";

  // --- piezas --------------------------------------------------------------
  const alumno = (j, entrenador) => (
    <li key={`${entrenador ? entrenador.id : "sin"}-${j.id}`}
      className={cogido?.tipo === "jugador" && cogido.id === j.id ? "cogido" : ""}
      draggable={editable}
      onDragStart={alArrastrar({
        tipo: "jugador", id: j.id, nombre: j.nombre,
        desde: entrenador ? entrenador.id : null,
      })}
      onDragEnd={limpiar}>
      <button type="button" className="nombre-alumno" disabled={!editable}
        title={editable ? "Arrástralo, o tócalo y elige destino" : undefined}
        onClick={() => setCogido({
          tipo: "jugador", id: j.id, nombre: j.nombre,
          desde: entrenador ? entrenador.id : null,
        })}>
        <span className="div-badge">{j.division ? `D${j.division}` : "—"}</span>
        <span className="txt">{j.nombre}</span>
        {j.grupo_de && <span className="de-quien">de {j.grupo_de}</span>}
      </button>
      {editable && entrenador && (
        <button type="button" className="quitar" disabled={ocupado}
          title={`${entrenador.nombre} deja de llevarle`}
          onClick={() => accion(
            () => grupoQuitar(j.id, entrenador.id),
            `${entrenador.nombre} ya no lleva a ${j.nombre}.`
          )}>
          ✕
        </button>
      )}
    </li>
  );

  const columna = (g) => {
    const e = g.entrenador;
    const propios = g.jugadores.filter(coincide);
    const tambien = g.tambien.filter(coincide);
    const zona = `col-${e.id}`;
    return (
      <article key={e.id}
        className={[
          "columna",
          cogido?.tipo === "entrenador" && cogido.id === e.id ? "cogido" : "",
          encima === zona ? "encima" : "",
          moviendoJugador ? "esperando" : "",
        ].filter(Boolean).join(" ")}
        onDragOver={permitirSoltar("jugador", zona)}
        onDragLeave={() => encima === zona && setEncima(null)}
        onDrop={alSoltar(() => soltarEnColumna(e))}>
        <header className="col-head" draggable={editable}
          onDragStart={alArrastrar({ tipo: "entrenador", id: e.id, nombre: e.nombre, desde: g.coachId })}
          onDragEnd={limpiar}
          onClick={() => editable && setCogido({
            tipo: "entrenador", id: e.id, nombre: e.nombre, desde: g.coachId,
          })}
          title={editable ? "Arrastra la columna a otro bloque" : undefined}>
          <h3>{e.nombre}</h3>
          <p className="sub">{e.divisiones} · {g.jugadores.length} alumno
            {g.jugadores.length === 1 ? "" : "s"}</p>
        </header>

        {moviendoJugador && editable && (
          <button className="btn sm traer" disabled={ocupado}
            onClick={() => soltarEnColumna(e)}>Traer aquí</button>
        )}

        {propios.length === 0 ? (
          <p className="msg">{busca ? "Ninguno con ese nombre." : "Sin alumnos."}</p>
        ) : (
          <ul className="miembros">{propios.map((j) => alumno(j, e))}</ul>
        )}

        {g.tambien.length > 0 && (
          <details className="tambien">
            <summary>También entrena a {g.tambien.length}</summary>
            {tambien.length === 0
              ? <p className="msg">Ninguno con ese nombre.</p>
              : <ul className="miembros">{tambien.map((j) => alumno(j, e))}</ul>}
          </details>
        )}
      </article>
    );
  };

  const sinGrupo = datos.sin_grupo.filter(coincide);

  return (
    <div className="page grupos">
      <div className="page-head">
        <h1>Grupos</h1>
        {!editable && <span className="pill no">Solo lectura</span>}
      </div>
      <p className="help">
        Arrastra un <b>alumno</b> a la columna de otro entrenador, o una
        <b> columna entera</b> a otro bloque: el alumno cambia de responsable y
        el entrenador se lleva a los suyos. En el móvil, toca a quien mueves y
        luego <b>Traer aquí</b>.
      </p>

      <div className="toolbar">
        <input className="search" placeholder="Buscar alumno…" value={busca}
          onChange={(e) => setBusca(e.target.value)} />
      </div>

      {error && <p className="err">{error}</p>}
      {aviso && <p className="ok-msg">{aviso}</p>}

      {cogido && (
        <div className="barra-cogido">
          <span>
            Moviendo {cogido.tipo === "jugador" ? "a" : "la columna de"}{" "}
            <b>{cogido.nombre}</b>. Suéltalo en{" "}
            {cogido.tipo === "jugador" ? "una columna" : "un bloque"} o toca
            «Traer aquí».
          </span>
          <button className="btn ghost sm" onClick={limpiar}>Cancelar</button>
        </div>
      )}

      {datos.sin_grupo.length > 0 && (
        <section
          className={`bloque huerfanos${encima === "sin-grupo" ? " encima" : ""}`}
          onDragOver={permitirSoltar("jugador", "sin-grupo")}
          onDragLeave={() => encima === "sin-grupo" && setEncima(null)}
          onDrop={alSoltar(soltarEnSinGrupo)}>
          <header className="bloque-head">
            <h2>Sin grupo</h2>
            <span className="cuenta">{datos.sin_grupo.length} alumnos · nadie responde por ellos</span>
            {moviendoJugador && editable && (
              <button className="btn sm traer" disabled={ocupado}
                onClick={soltarEnSinGrupo}>Dejar sin grupo</button>
            )}
          </header>
          {sinGrupo.length === 0
            ? <p className="msg">Ninguno con ese nombre.</p>
            : <ul className="miembros sueltos">{sinGrupo.map((j) => alumno(j, null))}</ul>}
        </section>
      )}

      {datos.bloques.map((b) => {
        const clave = b.coach ? `bloque-${b.coach.id}` : "bloque-sin";
        const alumnos = b.grupos.reduce((n, g) => n + g.jugadores.length, 0);
        return (
          <section key={clave}
            className={[
              "bloque",
              encima === clave ? "encima" : "",
              moviendoEntrenador ? "esperando" : "",
            ].filter(Boolean).join(" ")}
            onDragOver={permitirSoltar("entrenador", clave)}
            onDragLeave={() => encima === clave && setEncima(null)}
            onDrop={alSoltar(() => soltarEnBloque(b.coach))}>
            <header className="bloque-head">
              <h2>{b.coach ? b.coach.nombre : "Sin bloque"}</h2>
              <span className="cuenta">
                {b.grupos.length} entrenador{b.grupos.length === 1 ? "" : "es"}
                {" · "}{alumnos} alumno{alumnos === 1 ? "" : "s"}
              </span>
              {moviendoEntrenador && editable && (
                <button className="btn sm traer" disabled={ocupado}
                  onClick={() => soltarEnBloque(b.coach)}>Traer aquí</button>
              )}
            </header>
            {b.grupos.length === 0 ? (
              <p className="msg">
                Bloque vacío{editable ? " · arrastra aquí una columna" : ""}.
              </p>
            ) : (
              <div className="columnas">
                {b.grupos.map((g) => columna({ ...g, coachId: b.coach ? b.coach.id : null }))}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
