"use client";

import { useEffect, useState } from "react";
import { getGruposDivisiones, getPermisosDivisiones, moverDeDivision, ordenarDivision, resource } from "../lib/api";

/**
 * Grupos → «Por división» (10/11/2026; antes, la pantalla Divisiones): una
 * columna por división con sus alumnos y su ranking. Solo dirección mueve de
 * división y ordena (decisión 5); el resto mira. Los niveles y sus nombres se
 * editan en Club → Divisiones.
 *
 * Divisiones con el aspecto de Grupos (21/10/2026): una columna por división
 * con sus alumnos debajo. Dirección y Dani Gimeno mueven alumnos de una
 * división a otra (arrastrando, o tocando al alumno y luego el destino) y el
 * cambio se guarda en su ficha al momento; el resto solo mira. Dirección
 * conserva, plegada, la tabla para crear o editar divisiones.
 *
 * Los alumnos salen de /grupos/divisiones/: todos los que entrenan (sin bajas
 * ya pasadas), también los de bloques que alguien no ve, con su responsable y
 * su edad debajo, como en la antigua vista «Por división» (11/11/2026).
 *
 * Ranking (27/10/2026): dentro de cada columna, arrastrar a un alumno encima o
 * debajo de otro cambia su puesto en la división (1 = el mejor); soltarlo
 * sobre un alumno de otra columna lo cambia de división y lo deja en ese
 * puesto. Tocando: se toca al alumno y luego a aquel delante del que va. Una
 * división sin ranking sale por orden alfabético y sin números hasta que
 * alguien la ordena por primera vez.
 */

/** Los alumnos de una columna en su orden: por puesto y, sin él, por nombre. */
function enOrden(jugadores) {
  return [...jugadores].sort((a, b) => {
    const pa = a.orden_division ?? Infinity;
    const pb = b.orden_division ?? Infinity;
    return pa === pb ? a.nombre.localeCompare(b.nombre, "es") : pa - pb;
  });
}
export default function DivisionesRanking({ pestanas }) {
  const [divisiones, setDivisiones] = useState(null);
  const [alumnos, setAlumnos] = useState([]);
  const [puedeMover, setPuedeMover] = useState(false);
  const [busca, setBusca] = useState("");
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState(null); // {texto, deshacer?}
  const [cogido, setCogido] = useState(null); // alumno elegido para mover
  const [encima, setEncima] = useState(null); // columna bajo el arrastre
  const [caer, setCaer] = useState(null); // {id, despues}: dónde caería en la columna
  const [ocupado, setOcupado] = useState(false);

  useEffect(() => {
    Promise.all([resource("divisiones").list(), getGruposDivisiones()])
      .then(([divs, g]) => {
        const todos = (g.divisiones || []).flatMap((d) => d.jugadores || []);
        setAlumnos(todos.sort((a, b) => a.nombre.localeCompare(b.nombre, "es")));
        setDivisiones([...divs].sort((a, b) => a.nivel - b.nivel));
      })
      .catch((e) => setError(e.message));
    getPermisosDivisiones().then((r) => setPuedeMover(!!r.puede_mover)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!cogido) return undefined;
    const esc = (e) => { if (e.key === "Escape") setCogido(null); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [cogido]);

  if (!divisiones) {
    return (
      <div className="page grupos">
        <div className="page-head"><h1>Grupos</h1></div>
        {pestanas}
        {error ? <p className="err">{error}</p> : <p className="msg">Cargando…</p>}
      </div>
    );
  }

  const nivelDe = new Map(divisiones.map((d) => [d.id, d.nivel]));
  const tituloDe = (nivel) => {
    const d = divisiones.find((x) => x.nivel === nivel);
    return d ? (d.nombre || `División ${d.nivel}`) : "Sin división";
  };

  /** Mueve al alumno a `divisionId` (null = sin división). Se pinta al momento
   *  y, si el servidor no lo acepta, vuelve a su sitio. Devuelve si salió bien. */
  async function mover(jugador, divisionId, { deshaciendo = false, sinAviso = false } = {}) {
    const destino = divisionId == null ? null : nivelDe.get(divisionId);
    setCogido(null);
    setEncima(null);
    setCaer(null);
    if (destino === jugador.division) return true;
    const antes = { division: jugador.division, orden_division: jugador.orden_division };
    const cambiar = (datos) => setAlumnos((prev) => prev.map((x) => (x.id === jugador.id ? { ...x, ...datos } : x)));
    cambiar({ division: destino, orden_division: null });
    setOcupado(true);
    setError("");
    try {
      const r = await moverDeDivision(jugador.id, divisionId);
      cambiar({ orden_division: r.orden_division ?? null });
      if (!sinAviso) {
        setAviso(deshaciendo
          ? { texto: `${jugador.nombre} vuelve a ${tituloDe(destino)}.` }
          : {
            texto: `${jugador.nombre} pasa a ${tituloDe(destino)}.`,
            deshacer: () => mover({ ...jugador, division: destino }, r.anterior_id ?? null, { deshaciendo: true }),
          });
      }
      return true;
    } catch (e) {
      cambiar(antes);
      setError(e.message);
      return false;
    } finally {
      setOcupado(false);
    }
  }

  /** Guarda el ranking de una división: `ids`, del mejor al último. */
  async function ordenar(divisionId, ids, { texto, antes } = {}) {
    const previo = new Map(alumnos.map((x) => [x.id, x.orden_division]));
    const puesto = new Map(ids.map((id, i) => [id, i + 1]));
    setAlumnos((prev) => prev.map((x) => (puesto.has(x.id) ? { ...x, orden_division: puesto.get(x.id) } : x)));
    setOcupado(true);
    setError("");
    try {
      const r = await ordenarDivision(divisionId, ids);
      const final = new Map((r.orden || []).map((f) => [f.id, f.orden_division]));
      setAlumnos((prev) => prev.map((x) => (final.has(x.id) ? { ...x, orden_division: final.get(x.id) } : x)));
      if (texto) {
        setAviso({ texto, deshacer: antes ? () => ordenar(divisionId, antes, { texto: "Ranking como estaba." }) : undefined });
      }
    } catch (e) {
      setAlumnos((prev) => prev.map((x) => ({ ...x, orden_division: previo.get(x.id) ?? x.orden_division })));
      setError(e.message);
    } finally {
      setOcupado(false);
    }
  }

  /** Suelta a `j` en la columna `c`: delante (o detrás, con `despues`) del
   *  alumno `refId`, o al final si no hay. Si es otra división, primero lo
   *  cambia de división. */
  async function soltar(j, c, refId = null, despues = false) {
    setCogido(null);
    setEncima(null);
    setCaer(null);
    if (c.id == null) { // «Sin división» no tiene ranking.
      if (!deEstaColumna(c, j)) await mover(j, null);
      return;
    }
    const misma = deEstaColumna(c, j);
    const actual = enOrden(c.jugadores).map((x) => x.id);
    const base = actual.filter((id) => id !== j.id);
    let i = refId == null ? base.length : base.indexOf(refId) + (despues ? 1 : 0);
    if (i < 0) i = base.length;
    const nuevo = [...base.slice(0, i), j.id, ...base.slice(i)];
    const puesto = i + 1;
    if (misma) {
      if (nuevo.every((id, k) => id === actual[k])) return;
      await ordenar(c.id, nuevo, {
        texto: `${j.nombre}, ${puesto}º de ${c.titulo}.`,
        antes: actual,
      });
      return;
    }
    if (refId == null) { await mover(j, c.id); return; }
    if (await mover(j, c.id, { sinAviso: true })) {
      await ordenar(c.id, nuevo, { texto: `${j.nombre} pasa a ${c.titulo}, ${puesto}º.` });
    }
  }

  const q = busca.trim().toLowerCase();
  const coincide = (j) => !q || j.nombre.toLowerCase().includes(q);
  const niveles = new Set(divisiones.map((d) => d.nivel));
  const columnas = [
    ...divisiones.map((d) => ({ clave: String(d.id), id: d.id, titulo: d.nombre || `División ${d.nivel}`, nivel: d.nivel,
      jugadores: alumnos.filter((j) => j.division === d.nivel) })),
    { clave: "sin", id: null, titulo: "Sin división", nivel: null,
      jugadores: alumnos.filter((j) => j.division == null || !niveles.has(j.division)) },
  ].filter((c) => c.nivel != null || c.jugadores.length || puedeMover);

  function deEstaColumna(c, j) {
    return c.nivel == null ? (j.division == null || !niveles.has(j.division)) : j.division === c.nivel;
  }

  return (
    <div className={`page grupos divisiones-vista${puedeMover ? " movible" : ""}`}>
      <div className="page-head">
        <h1>Grupos</h1>
      </div>
      {pestanas}
      <p className="help">
        Los alumnos activos, cada uno bajo su división ({alumnos.length} en total).
        {puedeMover
          ? " Arrastra a un alumno encima o debajo de otro para cambiar su puesto en la división (1º = el mejor), o a otra división. Tocando: toca al alumno y luego a aquel delante del que va, o «Traer aquí». Se guarda al momento."
          : " El número es su puesto en la división (1º = el mejor). La división y el puesto los cambia dirección."}
      </p>

      <div className="toolbar">
        <input className="search" placeholder="Buscar alumno…" value={busca}
          onChange={(e) => setBusca(e.target.value)} />
      </div>
      {error && <p className="err" role="alert">{error}</p>}
      {aviso && (
        <p className="ok-msg" role="status">
          {aviso.texto}
          {aviso.deshacer && (
            <button type="button" className="btn ghost sm deshacer-div" disabled={ocupado}
              onClick={() => { const d = aviso.deshacer; setAviso(null); d(); }}>Deshacer</button>
          )}
        </p>
      )}
      {cogido && (
        <div className="barra-cogido">
          <span>Moviendo a <b>{cogido.nombre}</b> ({tituloDe(cogido.division)}): toca al alumno delante del que va, o «Traer aquí» en otra división.</span>
          <button type="button" className="btn ghost sm" onClick={() => setCogido(null)}>Cancelar</button>
        </div>
      )}

      <section className="bloque">
        <div className="columnas">
          {columnas.map((c) => {
            const ordenados = enOrden(c.jugadores);
            const conRanking = c.id != null && ordenados.some((j) => j.orden_division != null);
            const visibles = ordenados.filter(coincide);
            const destinoPosible = puedeMover && cogido && !deEstaColumna(c, cogido);
            return (
              <article key={c.clave}
                className={["columna", encima === c.clave ? "encima" : "", destinoPosible ? "esperando" : ""].filter(Boolean).join(" ")}
                onDragOver={puedeMover ? (e) => { e.preventDefault(); if (encima !== c.clave) setEncima(c.clave); } : undefined}
                onDragLeave={puedeMover ? (e) => { if (!e.currentTarget.contains(e.relatedTarget)) { setEncima(null); setCaer(null); } } : undefined}
                onDrop={puedeMover ? (e) => {
                  e.preventDefault();
                  const id = Number(e.dataTransfer.getData("text/plain"));
                  const j = alumnos.find((x) => x.id === id);
                  if (j) soltar(j, c); else { setEncima(null); setCaer(null); }
                } : undefined}>
                <header className="col-head">
                  <div>
                    <h3>{c.titulo}</h3>
                    <p className="sub">{c.jugadores.length} alumno{c.jugadores.length === 1 ? "" : "s"}</p>
                  </div>
                </header>
                {destinoPosible && (
                  <button type="button" className="btn sm traer" disabled={ocupado}
                    onClick={() => soltar(cogido, c)}>
                    Traer aquí
                  </button>
                )}
                {visibles.length === 0 ? (
                  <p className="msg">{busca ? "Ninguno con ese nombre." : "Sin alumnos."}</p>
                ) : (
                  <ul className="miembros">
                    {visibles.map((j) => {
                      const puesto = conRanking && j.orden_division != null
                        ? ordenados.findIndex((x) => x.id === j.id) + 1 : null;
                      const clases = [
                        cogido?.id === j.id ? "cogido" : "",
                        cogido && cogido.id !== j.id && c.id != null ? "destino-toque" : "",
                        caer?.id === j.id ? (caer.despues ? "caer-despues" : "caer-antes") : "",
                      ].filter(Boolean).join(" ");
                      return (
                        <li key={j.id} className={clases}
                          draggable={puedeMover && !ocupado}
                          onDragStart={puedeMover ? (e) => {
                            e.dataTransfer.setData("text/plain", String(j.id));
                            e.dataTransfer.effectAllowed = "move";
                          } : undefined}
                          onDragOver={puedeMover && c.id != null ? (e) => {
                            e.preventDefault();
                            const r = e.currentTarget.getBoundingClientRect();
                            const despues = e.clientY > r.top + r.height / 2;
                            if (caer?.id !== j.id || caer?.despues !== despues) setCaer({ id: j.id, despues });
                          } : undefined}
                          onDrop={puedeMover && c.id != null ? (e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            const id = Number(e.dataTransfer.getData("text/plain"));
                            const arrastrado = alumnos.find((x) => x.id === id);
                            const despues = caer?.id === j.id ? caer.despues : false;
                            if (arrastrado && arrastrado.id !== j.id) soltar(arrastrado, c, j.id, despues);
                            else { setEncima(null); setCaer(null); }
                          } : undefined}
                          onDragEnd={() => { setEncima(null); setCaer(null); }}>
                          <button type="button" className="nombre-alumno" disabled={!puedeMover || ocupado}
                            aria-pressed={cogido?.id === j.id}
                            title={puedeMover
                              ? (cogido && cogido.id !== j.id ? `Poner a ${cogido.nombre} delante` : "Toca para moverlo de puesto o de división")
                              : undefined}
                            onClick={() => {
                              if (!cogido || cogido.id === j.id) setCogido(cogido?.id === j.id ? null : j);
                              else if (c.id != null) soltar(cogido, c, j.id, false);
                              else setCogido(j);
                            }}>
                            {conRanking && <span className="puesto">{puesto ? `${puesto}º` : "—"}</span>}
                            <span className="txt">{j.nombre}</span>
                            <span className="resp">
                              {[j.responsable || "Sin grupo", j.edad ? `${j.edad} año${j.edad === 1 ? "" : "s"}` : null]
                                .filter(Boolean).join(" · ")}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </article>
            );
          })}
        </div>
      </section>

    </div>
  );
}
