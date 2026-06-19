"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getLatestSemana, resource } from "../../lib/api";

export default function Panel() {
  const [stats, setStats] = useState(null);
  const [semana, setSemana] = useState(null);

  useEffect(() => {
    (async () => {
      const [jug, ent, sed, ren, con] = await Promise.all([
        resource("jugadores").list(),
        resource("entrenadores").list(),
        resource("sedes").list(),
        resource("rencillas").list(),
        resource("contratos").list(),
      ]);
      setStats({
        jugadores: jug.length,
        activos: jug.filter((j) => j.activo).length,
        menores: jug.filter((j) => j.es_menor).length,
        entrenadores: ent.length,
        sedes: sed.length,
        rencillas: ren.length,
        contratos: con.length,
      });
      setSemana(await getLatestSemana());
    })();
  }, []);

  if (!stats) return <p className="msg">Cargando panel…</p>;

  const cards = [
    ["Jugadores", stats.jugadores],
    ["Activos", stats.activos],
    ["Menores (RGPD)", stats.menores],
    ["Entrenadores", stats.entrenadores],
    ["Sedes", stats.sedes],
    ["Rencillas", stats.rencillas],
    ["Contratos", stats.contratos],
  ];

  return (
    <div>
      <div className="page-head">
        <h1>Panel</h1>
        {semana && (
          <Link href="/cuadrante" className="btn">Ver cuadrante →</Link>
        )}
      </div>

      <div className="metrics">
        {cards.map(([label, value]) => (
          <div className="metric" key={label}>
            <div className="label">{label}</div>
            <div className="value">{value}</div>
          </div>
        ))}
      </div>

      <div className="card" style={{ padding: 18 }}>
        <h2 style={{ marginTop: 0, fontSize: 16 }}>Semana actual</h2>
        {semana ? (
          <p style={{ color: "var(--muted)" }}>
            {semana.fecha_inicio} ·{" "}
            <span className={`badge ${semana.estado === "PUBLICADO" ? "pub" : ""}`}>
              {semana.estado === "PUBLICADO" ? "Publicado" : "Borrador"}
            </span>{" "}
            {semana.generado_at ? "· generado" : "· sin generar"}
          </p>
        ) : (
          <p style={{ color: "var(--muted)" }}>
            No hay semanas. Crea una en <Link href="/semanas" style={{ color: "var(--accent)" }}>Semanas</Link>.
          </p>
        )}
      </div>
    </div>
  );
}
