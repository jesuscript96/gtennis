"use client";

import { useEffect, useState } from "react";
import ResourceCrud from "../../../components/ResourceCrud";
import { getGrupos, getUser, resource } from "../../../lib/api";
import { roleRank } from "../../../lib/perms";
import { RESOURCES } from "../../../lib/resources";

/**
 * Divisiones con el aspecto de Grupos (21/10/2026): una columna por división
 * con sus alumnos debajo. Es para mirar; la división de cada alumno se cambia
 * en su ficha. Dirección conserva, plegada, la tabla para editar divisiones.
 *
 * Los alumnos salen de /grupos/, que ya devuelve a todos los activos con su
 * división (en algún grupo o en «sin grupo»); aquí solo se reagrupan.
 */
export default function Page() {
  const [divisiones, setDivisiones] = useState(null);
  const [alumnos, setAlumnos] = useState([]);
  const [busca, setBusca] = useState("");
  const [error, setError] = useState("");
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
  }, []);

  if (!divisiones) {
    return (
      <div className="page grupos">
        <div className="page-head"><h1>Divisiones</h1></div>
        {error ? <p className="err">{error}</p> : <p className="msg">Cargando…</p>}
      </div>
    );
  }

  const q = busca.trim().toLowerCase();
  const coincide = (j) => !q || j.nombre.toLowerCase().includes(q);
  const niveles = new Set(divisiones.map((d) => d.nivel));
  const columnas = [
    ...divisiones.map((d) => ({ clave: d.id, titulo: d.nombre || `División ${d.nivel}`, nivel: d.nivel,
      jugadores: alumnos.filter((j) => j.division === d.nivel) })),
    { clave: "sin", titulo: "Sin división", nivel: null,
      jugadores: alumnos.filter((j) => j.division == null || !niveles.has(j.division)) },
  ].filter((c) => c.nivel != null || c.jugadores.length);

  return (
    <div className="page grupos divisiones-vista">
      <div className="page-head">
        <h1>Divisiones</h1>
        {!direccion && <span className="pill no">Solo lectura</span>}
      </div>
      <p className="help">
        Los alumnos activos, cada uno bajo su división ({alumnos.length} en total).
        La división de un alumno se cambia en su ficha.
      </p>

      <div className="toolbar">
        <input className="search" placeholder="Buscar alumno…" value={busca}
          onChange={(e) => setBusca(e.target.value)} />
      </div>
      {error && <p className="err">{error}</p>}

      <section className="bloque">
        <div className="columnas">
          {columnas.map((c) => {
            const visibles = c.jugadores.filter(coincide);
            return (
              <article key={c.clave} className="columna">
                <header className="col-head">
                  <div>
                    <h3>{c.titulo}</h3>
                    <p className="sub">{c.jugadores.length} alumno{c.jugadores.length === 1 ? "" : "s"}</p>
                  </div>
                </header>
                {visibles.length === 0 ? (
                  <p className="msg">{busca ? "Ninguno con ese nombre." : "Sin alumnos."}</p>
                ) : (
                  <ul className="miembros">
                    {visibles.map((j) => (
                      <li key={j.id}>
                        <span className="nombre-alumno">
                          <span className="txt">{j.nombre}</span>
                        </span>
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
