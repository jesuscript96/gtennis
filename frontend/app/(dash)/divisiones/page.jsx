"use client";

import { useEffect, useState } from "react";
import ResourceCrud from "../../../components/ResourceCrud";
import { getGrupos, getPermisosDivisiones, getUser, moverDeDivision, resource } from "../../../lib/api";
import { roleRank } from "../../../lib/perms";
import { RESOURCES } from "../../../lib/resources";

/**
 * Divisiones con el aspecto de Grupos (21/10/2026): una columna por división
 * con sus alumnos debajo. Dirección y Dani Gimeno mueven alumnos de una
 * división a otra (arrastrando, o tocando al alumno y luego el destino) y el
 * cambio se guarda en su ficha al momento; el resto solo mira. Dirección
 * conserva, plegada, la tabla para crear o editar divisiones.
 *
 * Los alumnos salen de /grupos/, que ya devuelve a todos los activos con su
 * división (en algún grupo o en «sin grupo»); aquí solo se reagrupan.
 */
export default function Page() {
  const [divisiones, setDivisiones] = useState(null);
  const [alumnos, setAlumnos] = useState([]);
  const [puedeMover, setPuedeMover] = useState(false);
  const [busca, setBusca] = useState("");
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState(null); // {texto, deshacer?}
  const [cogido, setCogido] = useState(null); // alumno elegido para mover
  const [encima, setEncima] = useState(null); // columna bajo el arrastre
  const [ocupado, setOcupado] = useState(false);
  const direccion = roleRank(getUser()) >= 3;

  useEffect(() => {
    Promise.all([resource("divisiones").list(), getGrupos()])
      .then(([divs, g]) => {
        const porId = new Map();
        for (const b of g.bloques || []) {
          for (const gr of b.grupos || []) for (const j of gr.jugadores || []) porId.set(j.id, j);
        }
        for (const j of g.sin_grupo || []) porId.set(j.id, j);
        setAlumnos([...porId.values()].sort((a, b) => a.nombre.localeCompare(b.nombre, "es")));
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
        <div className="page-head"><h1>Divisiones</h1></div>
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
   *  y, si el servidor no lo acepta, vuelve a su sitio. */
  async function mover(jugador, divisionId, { deshaciendo = false } = {}) {
    const destino = divisionId == null ? null : nivelDe.get(divisionId);
    setCogido(null);
    setEncima(null);
    if (destino === jugador.division) return;
    const antes = jugador.division;
    const cambiar = (nivel) => setAlumnos((prev) => prev.map((x) => (x.id === jugador.id ? { ...x, division: nivel } : x)));
    cambiar(destino);
    setOcupado(true);
    setError("");
    try {
      const r = await moverDeDivision(jugador.id, divisionId);
      setAviso(deshaciendo
        ? { texto: `${jugador.nombre} vuelve a ${tituloDe(destino)}.` }
        : {
          texto: `${jugador.nombre} pasa a ${tituloDe(destino)}.`,
          deshacer: () => mover({ ...jugador, division: destino }, r.anterior_id ?? null, { deshaciendo: true }),
        });
    } catch (e) {
      cambiar(antes);
      setError(e.message);
    } finally {
      setOcupado(false);
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

  const deEstaColumna = (c, j) => (c.nivel == null ? (j.division == null || !niveles.has(j.division)) : j.division === c.nivel);

  return (
    <div className={`page grupos divisiones-vista${puedeMover ? " movible" : ""}`}>
      <div className="page-head">
        <h1>Divisiones</h1>
        {!puedeMover && <span className="pill no">Solo lectura</span>}
      </div>
      <p className="help">
        Los alumnos activos, cada uno bajo su división ({alumnos.length} en total).
        {puedeMover
          ? " Arrastra a un alumno a otra división, o tócalo y elige el destino: el cambio se guarda en su ficha al momento."
          : " La división de un alumno se cambia en su ficha."}
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
          <span>Moviendo a <b>{cogido.nombre}</b> ({tituloDe(cogido.division)}): elige la división de destino.</span>
          <button type="button" className="btn ghost sm" onClick={() => setCogido(null)}>Cancelar</button>
        </div>
      )}

      <section className="bloque">
        <div className="columnas">
          {columnas.map((c) => {
            const visibles = c.jugadores.filter(coincide);
            const destinoPosible = puedeMover && cogido && !deEstaColumna(c, cogido);
            return (
              <article key={c.clave}
                className={["columna", encima === c.clave ? "encima" : "", destinoPosible ? "esperando" : ""].filter(Boolean).join(" ")}
                onDragOver={puedeMover ? (e) => { e.preventDefault(); if (encima !== c.clave) setEncima(c.clave); } : undefined}
                onDragLeave={puedeMover ? (e) => { if (!e.currentTarget.contains(e.relatedTarget)) setEncima(null); } : undefined}
                onDrop={puedeMover ? (e) => {
                  e.preventDefault();
                  const id = Number(e.dataTransfer.getData("text/plain"));
                  const j = alumnos.find((x) => x.id === id);
                  if (j) mover(j, c.id); else setEncima(null);
                } : undefined}>
                <header className="col-head">
                  <div>
                    <h3>{c.titulo}</h3>
                    <p className="sub">{c.jugadores.length} alumno{c.jugadores.length === 1 ? "" : "s"}</p>
                  </div>
                </header>
                {destinoPosible && (
                  <button type="button" className="btn sm traer" disabled={ocupado}
                    onClick={() => mover(cogido, c.id)}>
                    Traer aquí
                  </button>
                )}
                {visibles.length === 0 ? (
                  <p className="msg">{busca ? "Ninguno con ese nombre." : "Sin alumnos."}</p>
                ) : (
                  <ul className="miembros">
                    {visibles.map((j) => (
                      <li key={j.id} className={cogido?.id === j.id ? "cogido" : ""}
                        draggable={puedeMover && !ocupado}
                        onDragStart={puedeMover ? (e) => {
                          e.dataTransfer.setData("text/plain", String(j.id));
                          e.dataTransfer.effectAllowed = "move";
                        } : undefined}
                        onDragEnd={() => setEncima(null)}>
                        <button type="button" className="nombre-alumno" disabled={!puedeMover || ocupado}
                          aria-pressed={cogido?.id === j.id}
                          title={puedeMover ? "Toca para moverlo a otra división" : undefined}
                          onClick={() => setCogido(cogido?.id === j.id ? null : j)}>
                          <span className="txt">{j.nombre}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </article>
            );
          })}
        </div>
      </section>

      {direccion && (
        <details className="editar-divisiones">
          <summary>Editar divisiones</summary>
          <ResourceCrud config={RESOURCES.divisiones} />
        </details>
      )}
    </div>
  );
}
