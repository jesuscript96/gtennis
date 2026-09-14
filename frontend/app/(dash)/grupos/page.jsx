"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getGrupos, grupoMover, grupoMoverEntrenador, grupoQuitar, resource,
} from "../../../lib/api";

/**
 * El organigrama de la academia, como está en el Excel de dirección: cada
 * bloque es un coach, dentro van las columnas de sus entrenadores y bajo cada
 * columna sus alumnos.
 *
 * Se reorganiza arrastrando, y cada cosa solo entra donde tiene sentido: un
 * alumno cae en una columna de entrenador, y una columna entera —el entrenador
 * con sus alumnos— cae en un bloque. Al soltar se guarda.
 *
 * El arrastre va con eventos de puntero y NO con el drag-and-drop de HTML5. No
 * es capricho: la fila del alumno es un botón, y un control de formulario se
 * come el gesto, así que con `draggable` el navegador no llegaba a empezar el
 * arrastre nunca. Con punteros da igual lo que haya dentro, y de paso se puede
 * pintar el fantasma que sigue al cursor y desplazar la página sola al llegar
 * a los bordes.
 *
 * En táctil no se arrastra —el dedo tiene que poder desplazar la lista— así
 * que ahí se toca a quien se mueve y luego "Traer aquí" en el destino. Eso
 * funciona también con ratón, para quien lo prefiera.
 *
 * Un alumno sale además en el "también entrena" de otros entrenadores de su
 * bloque: todos los capacitados para su división pueden entrenarle. Va plegado
 * para que no parezca el mismo grupo repetido.
 */
export default function Page() {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [busca, setBusca] = useState("");
  // Lo que se está moviendo, se arrastre o se toque: { tipo, id, nombre, desde }
  const [cogido, setCogido] = useState(null);
  const [encima, setEncima] = useState(null);
  const [fantasma, setFantasma] = useState(null);
  // Se arrastra con el puntero (true) o se ha cogido tocando (false). Importa
  // porque los botones "Traer aquí" solo valen para el toque: si salieran
  // mientras se arrastra, empujarían la página y el destino se movería.
  const [arrastrando, setArrastrando] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const arrastre = useRef(null);
  // Los manejadores de ventana viven en el efecto (necesitan `soltarEn`), pero
  // quien los engancha es el pointerdown de cada fila: se pasan por aquí.
  const manejadores = useRef({});

  const cargar = useCallback(async () => {
    try {
      setDatos(await getGrupos());
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => { cargar(); }, [cargar]);

  const editable = !!datos?.puede_editar;

  const limpiar = useCallback(() => {
    setCogido(null);
    setEncima(null);
    setFantasma(null);
    setArrastrando(false);
    document.body.classList.remove("arrastrando");
  }, []);

  const accion = useCallback(async (fn, mensaje) => {
    setOcupado(true); setError(""); setAviso("");
    try {
      await fn();
      setAviso(mensaje);
      await cargar();
    } catch (e) {
      setError(e.message);
    }
    setOcupado(false);
  }, [cargar]);

  // --- soltar: lo mismo para el arrastre y para el toque --------------------
  const soltarEn = useCallback((zona, q) => {
    limpiar();
    if (!q || !zona) return;
    if (q.tipo === "jugador") {
      if (zona.entrenador === null) {
        if (!q.desde) return;
        return accion(
          () => grupoQuitar(q.id, q.desde),
          `${q.nombre} se queda sin responsable.`
        );
      }
      if (zona.entrenador === q.desde) return;
      return accion(
        () => grupoMover(q.id, zona.entrenador),
        `${q.nombre} pasa al grupo de ${zona.nombre}.`
      );
    }
    if (zona.quitar) {
      if (!window.confirm(
        `¿Quitar a ${q.nombre} de la lista de grupos?\n\n` +
        "Deja de estar activo: no entra en el reparto ni sale aquí. Sus " +
        "alumnos se quedan sin responsable hasta que los lleves a otro grupo. " +
        "Se puede volver a activar desde Entrenadores."
      )) return;
      return accion(
        () => resource("entrenadores").update(q.id, { activo: false }),
        `${q.nombre} fuera de la lista de grupos.`
      );
    }
    if (zona.coach === q.desde) return;
    return accion(
      () => grupoMoverEntrenador(q.id, zona.coach),
      zona.coach
        ? `${q.nombre} y sus alumnos pasan al bloque de ${zona.nombre}.`
        : `${q.nombre} se queda fuera de los bloques.`
    );
  }, [accion, limpiar]);

  // --- arrastre con eventos de puntero -------------------------------------
  // Zona de destino bajo el cursor, de las que aceptan lo que se lleva.
  function zonaEn(x, y, tipo) {
    const el = document.elementFromPoint(x, y);
    if (!el) return null;
    if (tipo === "entrenador") {
      // Soltar a un entrenador encima de otra columna no hace nada: se queda
      // en la suya. Solo cuentan el bloque y la zona de quitar.
      const papelera = el.closest('[data-zona="quitar"]');
      if (papelera) return { clave: "quitar", quitar: true };
      if (el.closest(".columna")) return null;
    }
    const destino = el.closest(`[data-zona="${tipo}"]`);
    if (!destino) return null;
    const d = destino.dataset;
    return {
      clave: d.clave,
      nombre: d.nombre,
      entrenador: d.entrenador ? Number(d.entrenador) : null,
      coach: d.coach ? Number(d.coach) : null,
    };
  }

  useEffect(() => {
    function alMover(e) {
      const a = arrastre.current;
      if (!a) return;
      if (!a.activo) {
        // Umbral: sin esto, un clic con un temblor de 1px ya sería arrastre.
        if (Math.hypot(e.clientX - a.x, e.clientY - a.y) < 5) return;
        a.activo = true;
        setCogido(a.payload);
        setArrastrando(true);
        document.body.classList.add("arrastrando");
      }
      setFantasma({ x: e.clientX, y: e.clientY, nombre: a.payload.nombre });
      const zona = zonaEn(e.clientX, e.clientY, a.payload.tipo);
      setEncima(zona ? zona.clave : null);

      // Al llegar a los bordes la página se desplaza sola: si no, no se puede
      // llevar a nadie de la lista de arriba a un bloque de más abajo.
      const margen = 70, paso = 14;
      if (e.clientY < margen) window.scrollBy(0, -paso);
      else if (e.clientY > window.innerHeight - margen) window.scrollBy(0, paso);
    }

    function alSoltar(e) {
      const a = arrastre.current;
      arrastre.current = null;
      window.removeEventListener("pointermove", alMover);
      window.removeEventListener("pointerup", alSoltar);
      window.removeEventListener("pointercancel", alCancelar);
      if (!a || !a.activo) return;  // fue un clic: lo recoge el onClick
      soltarEn(zonaEn(e.clientX, e.clientY, a.payload.tipo), a.payload);
    }

    function alCancelar() {
      arrastre.current = null;
      window.removeEventListener("pointermove", alMover);
      window.removeEventListener("pointerup", alSoltar);
      window.removeEventListener("pointercancel", alCancelar);
      limpiar();
    }

    manejadores.current = { alMover, alSoltar, alCancelar };
    return () => {
      window.removeEventListener("pointermove", alMover);
      window.removeEventListener("pointerup", alSoltar);
      window.removeEventListener("pointercancel", alCancelar);
    };
  }, [soltarEn, limpiar]);

  function empezarArrastre(e, payload) {
    if (!editable || ocupado) return;
    // El dedo tiene que poder desplazar la lista: en táctil se mueve tocando.
    if (e.pointerType === "touch" || e.button !== 0) return;
    if (e.target.closest("button.quitar, button.traer")) return;
    const h = manejadores.current;
    if (!h.alMover) return;
    arrastre.current = { payload, x: e.clientX, y: e.clientY, activo: false };
    window.addEventListener("pointermove", h.alMover);
    window.addEventListener("pointerup", h.alSoltar);
    window.addEventListener("pointercancel", h.alCancelar);
  }

  if (!datos) {
    return (
      <div className="page grupos">
        <h1>Grupos</h1>
        {error ? <p className="err">{error}</p> : <p className="msg">Cargando…</p>}
      </div>
    );
  }

  const coincide = (j) =>
    !busca.trim() || j.nombre.toLowerCase().includes(busca.trim().toLowerCase());
  const moviendoJugador = cogido?.tipo === "jugador";
  const moviendoEntrenador = cogido?.tipo === "entrenador";
  // Los botones de destino son la alternativa al arrastre, no su compañía.
  const conBotones = !!cogido && !arrastrando;

  // --- piezas --------------------------------------------------------------
  const alumno = (j, entrenador) => {
    const payload = {
      tipo: "jugador", id: j.id, nombre: j.nombre,
      desde: entrenador ? entrenador.id : null,
    };
    return (
      <li key={`${entrenador ? entrenador.id : "sin"}-${j.id}`}
        className={moviendoJugador && cogido.id === j.id ? "cogido" : ""}
        onPointerDown={(e) => { e.stopPropagation(); empezarArrastre(e, payload); }}>
        <button type="button" className="nombre-alumno" disabled={!editable}
          title={editable ? "Arrástralo, o tócalo y elige destino" : undefined}
          onClick={() => setCogido(payload)}>
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
  };

  const columna = (g, coachId) => {
    const e = g.entrenador;
    const propios = g.jugadores.filter(coincide);
    const tambien = g.tambien.filter(coincide);
    const clave = `col-${e.id}`;
    const payload = { tipo: "entrenador", id: e.id, nombre: e.nombre, desde: coachId };
    return (
      <article key={e.id}
        onPointerDown={(ev) => empezarArrastre(ev, payload)}
        data-zona="jugador" data-clave={clave} data-entrenador={e.id} data-nombre={e.nombre}
        className={[
          "columna",
          moviendoEntrenador && cogido.id === e.id ? "cogido" : "",
          encima === clave ? "encima" : "",
          moviendoJugador ? "esperando" : "",
        ].filter(Boolean).join(" ")}>
        <header className="col-head"
          onClick={() => editable && setCogido(payload)}
          title={editable ? "Arrastra la columna a otro bloque" : undefined}>
          <span className="agarre" aria-hidden="true">⠿</span>
          <div>
            <h3>{e.nombre}</h3>
            <p className="sub">{e.divisiones} · {g.jugadores.length} alumno
              {g.jugadores.length === 1 ? "" : "s"}</p>
          </div>
        </header>

        {moviendoJugador && conBotones && editable && (
          <button className="btn sm traer" disabled={ocupado}
            onClick={() => soltarEn({ entrenador: e.id, nombre: e.nombre }, cogido)}>
            Traer aquí
          </button>
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
        <b> columna entera</b> (por su cabecera) a otro bloque: el alumno cambia
        de responsable y el entrenador se lleva a los suyos. En el móvil, toca a
        quien mueves y luego <b>Traer aquí</b>.
      </p>

      <div className="toolbar">
        <input className="search" placeholder="Buscar alumno…" value={busca}
          onChange={(e) => setBusca(e.target.value)} />
      </div>

      {error && <p className="err">{error}</p>}
      {aviso && <p className="ok-msg">{aviso}</p>}

      {conBotones && (
        <div className="barra-cogido">
          <span>
            Moviendo {moviendoJugador ? "a" : "la columna de"}{" "}
            <b>{cogido.nombre}</b>. Suéltalo en{" "}
            {moviendoJugador ? "una columna" : "un bloque"} o toca «Traer aquí».
          </span>
          <button className="btn ghost sm" onClick={limpiar}>Cancelar</button>
        </div>
      )}

      {moviendoEntrenador && editable && (
        <div data-zona="quitar"
          className={`zona-quitar${encima === "quitar" ? " encima" : ""}`}>
          <span>Soltar aquí para quitar a <b>{cogido.nombre}</b> de la lista</span>
          {conBotones && (
            <button className="btn ghost sm" disabled={ocupado}
              onClick={() => soltarEn({ quitar: true }, cogido)}>
              Quitar de la lista
            </button>
          )}
        </div>
      )}

      {datos.sin_grupo.length > 0 && (
        <section
          data-zona="jugador" data-clave="sin-grupo" data-nombre="Sin grupo"
          className={`bloque huerfanos${encima === "sin-grupo" ? " encima" : ""}${moviendoJugador ? " esperando" : ""}`}>
          <header className="bloque-head">
            <h2>Sin grupo</h2>
            <span className="cuenta">
              {datos.sin_grupo.length} alumnos · nadie responde por ellos
            </span>
            {moviendoJugador && conBotones && editable && cogido.desde && (
              <button className="btn sm traer" disabled={ocupado}
                onClick={() => soltarEn({ entrenador: null }, cogido)}>
                Dejar sin grupo
              </button>
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
            data-zona="entrenador" data-clave={clave}
            data-coach={b.coach ? b.coach.id : ""}
            data-nombre={b.coach ? b.coach.nombre : "sin bloque"}
            className={[
              "bloque",
              encima === clave ? "encima" : "",
              moviendoEntrenador ? "esperando" : "",
            ].filter(Boolean).join(" ")}>
            <header className="bloque-head">
              <h2>{b.coach ? b.coach.nombre : "Sin bloque"}</h2>
              <span className="cuenta">
                {b.grupos.length} entrenador{b.grupos.length === 1 ? "" : "es"}
                {" · "}{alumnos} alumno{alumnos === 1 ? "" : "s"}
              </span>
              {moviendoEntrenador && conBotones && editable && (
                <button className="btn sm traer" disabled={ocupado}
                  onClick={() => soltarEn({
                    coach: b.coach ? b.coach.id : null,
                    nombre: b.coach ? b.coach.nombre : "sin bloque",
                  }, cogido)}>
                  Traer aquí
                </button>
              )}
            </header>
            {b.grupos.length === 0 ? (
              <p className="msg">
                Bloque vacío{editable ? " · arrastra aquí una columna" : ""}.
              </p>
            ) : (
              <div className="columnas">
                {b.grupos.map((g) => columna(g, b.coach ? b.coach.id : null))}
              </div>
            )}
          </section>
        );
      })}

      {fantasma && (
        <div className="fantasma" style={{ left: fantasma.x, top: fantasma.y }}>
          {fantasma.nombre}
        </div>
      )}
    </div>
  );
}
