"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { getInformes, getPanelInformes } from "../../../lib/api";
import { ESTADO_INFORME, abrirParte, textoCiclo, textoParte } from "../../../lib/informes";
import { fmtLarga } from "../../../lib/torneos";

const FILTROS = [
  ["todos", "Todos"],
  ["toca", "Les toca"],
  ["marcha", "En marcha"],
  ["devueltos", "Devueltos"],
];

function pasa(j, filtro) {
  if (filtro === "toca") return !j.informe && ["primera", "pronto", "vencido"].includes(j.ciclo.estado);
  if (filtro === "marcha") return !!j.informe;
  if (filtro === "devueltos") return j.informe?.estado === "DEVUELTO";
  return true;
}

function Parte({ j, parte, titulo, puede }) {
  const router = useRouter();
  const [error, setError] = useState("");
  const inf = j.informe;
  const p = inf?.[parte === "tenis" ? "tenis" : "fisica"];
  const [texto, pill] = textoParte(p, inf?.devuelto_partes.includes(parte));
  return (
    <span className="inf-parte">
      <span className="inf-parte-nombre">{titulo}</span>
      <span className={`pill ${pill}`}>{texto}</span>
      {puede && (
        <button type="button" className="btn ghost sm"
          onClick={() => abrirParte(router, j.id, parte, p?.id).catch((e) => setError(e.message))}>
          {p ? "Abrir" : "Evaluar"}
        </button>
      )}
      {error && <span className="err">{error}</span>}
    </span>
  );
}

function Jugadores({ panel }) {
  const [busca, setBusca] = useState("");
  const [filtro, setFiltro] = useState("todos");
  const q = busca.trim().toLowerCase();
  const lista = panel.jugadores.filter((j) => pasa(j, filtro) && (!q || j.nombre.toLowerCase().includes(q)));
  const cuenta = Object.fromEntries(FILTROS.map(([k]) => [k, panel.jugadores.filter((j) => pasa(j, k)).length]));

  return (
    <>
      <div className="inf-filtros">
        <input className="eval-busca" type="search" placeholder="Buscar jugador"
          value={busca} onChange={(e) => setBusca(e.target.value)} />
        <div className="tabs-inv">
          {FILTROS.map(([k, t]) => (
            <button key={k} type="button" className={`chip${filtro === k ? " on" : ""}`} onClick={() => setFiltro(k)}>
              {t} · {cuenta[k]}
            </button>
          ))}
        </div>
      </div>
      {lista.length === 0 ? <p className="msg">Nadie con ese filtro.</p> : (
        <ul className="inf-lista">
          {lista.map((j) => {
            const [ciclo, pillCiclo] = textoCiclo(j.ciclo);
            const est = j.informe && ESTADO_INFORME[j.informe.estado];
            return (
              <li key={j.id} className="card inf-fila">
                <div className="inf-fila-cab">
                  <span className="eval-lista-nombre">{j.nombre}</span>
                  {j.edad != null && <span className="eval-lista-meta">{j.edad} años</span>}
                  {!j.foto && <span className="pill gris" title="Sin foto para el informe">sin foto</span>}
                  <span className={`pill ${pillCiclo}`}>{ciclo}</span>
                </div>
                <div className="inf-fila-partes">
                  <Parte j={j} parte="tenis" titulo="Tenis" puede={panel.evalua_tenis} />
                  <Parte j={j} parte="fisico" titulo="Físico" puede={panel.evalua_fisico} />
                </div>
                <div className="inf-fila-pie">
                  {j.informe ? (
                    <>
                      <span className={`pill ${est[1]}`}>{est[0]}</span>
                      <Link href={`/informes/${j.informe.id}`} className="btn sm">Ver informe</Link>
                    </>
                  ) : <span className="eval-nota">Sin informe en marcha.</span>}
                  {j.ultimo && (
                    <Link href={`/informes/${j.ultimo.id}`} className="inf-ultimo">
                      Último validado: {fmtLarga(j.ultimo.fecha)}
                    </Link>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}

function PorValidar({ informes }) {
  if (informes.length === 0) return <p className="msg">No hay informes pendientes de validar.</p>;
  return (
    <ul className="eval-lista">
      {informes.map((i) => (
        <li key={i.id}>
          <Link href={`/informes/${i.id}`} className="card">
            <span className="eval-lista-nombre">{i.jugador_nombre}</span>
            <span className="eval-lista-meta">
              Tenis: {i.tenis?.evaluador || "—"} · Físico: {i.fisica?.evaluador || "—"}
              {i.version > 1 && ` · corregido (v${i.version})`}
            </span>
            <span className="pill pend">Desde {fmtLarga(i.actualizado.slice(0, 10))}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function Informes() {
  const params = useSearchParams();
  const [panel, setPanel] = useState(null);
  const [pendientes, setPendientes] = useState([]);
  const [vista, setVista] = useState(params.get("vista") === "validar" ? "validar" : "jugadores");
  const [error, setError] = useState("");

  useEffect(() => {
    getPanelInformes().then((p) => {
      setPanel(p);
      if (p.puede_validar) getInformes({ estado: "PENDIENTE" }).then(setPendientes).catch(() => {});
    }).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="err">{error}</p>;
  if (!panel) return <p className="msg">Cargando…</p>;

  return (
    <div>
      <div className="page-head"><h1>Informes</h1></div>
      <p className="help">
        El informe trimestral de cada jugador de <b>Competición de tardes</b>: la evaluación de tenis y la
        de preparación física van en un solo PDF. Cuando las dos están terminadas, pasa a dirección
        deportiva, que lo aprueba o lo devuelve con una nota. El siguiente toca a los 90 días de validarlo.
      </p>
      {panel.puede_validar && (
        <div className="tabs-inv" role="tablist">
          <button type="button" role="tab" aria-selected={vista === "jugadores"}
            className={`chip${vista === "jugadores" ? " on" : ""}`} onClick={() => setVista("jugadores")}>Jugadores</button>
          <button type="button" role="tab" aria-selected={vista === "validar"}
            className={`chip${vista === "validar" ? " on" : ""}`} onClick={() => setVista("validar")}>
            Por validar{pendientes.length > 0 && <span className="nav-badge">{pendientes.length}</span>}
          </button>
        </div>
      )}
      {vista === "validar" && panel.puede_validar ? <PorValidar informes={pendientes} /> : <Jugadores panel={panel} />}
    </div>
  );
}

export default function InformesPage() {
  return <Suspense fallback={<p className="msg">Cargando…</p>}><Informes /></Suspense>;
}
