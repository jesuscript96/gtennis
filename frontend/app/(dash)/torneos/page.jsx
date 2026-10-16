"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  getTorneos, getTorneosEntrenadores, getTorneosResumen, guardarTorneo, updParticipante,
} from "../../../lib/api";
import { canWrite } from "../../../lib/perms";
import DeshacerTorneos from "../../../components/DeshacerTorneos";
import {
  ESTADO_CLASS, MESES, diasHasta, fmtCorta, fmtRango, fmtSemana, hoyISO, inicioEfectivo, lunesDe, semanasDe, solapa,
} from "../../../lib/torneos";

const ANIO = 2026;
// Cada semana lleva un color (se repiten cada cinco) para leer el calendario de un vistazo.
const COLORES_SEMANA = 5;

// Desplegable(s) de «acompaña»: uno por entrenador ya asignado y otro para
// añadir. Solo ofrece a los que no están de vacaciones en las fechas del
// torneo; si ya acompaña a otro torneo esa misma semana, lo dice.
function AcompanaCell({ t, lunes, entrenadores, enSemana, onGuardar, puedeEditar }) {
  const disponibles = entrenadores.filter((e) =>
    !e.vacaciones.some((v) => solapa(v.fecha_inicio, v.fecha_fin, inicioEfectivo(t), t.fecha_fin)));
  const ids = t.acompanantes || [];
  if (!puedeEditar) {
    return <>{t.acompanantes_detalle.map((e) => e.nombre).join(", ") || <span className="muted">—</span>}</>;
  }
  const opcion = (e) => {
    const otro = enSemana(e.id, t, lunes);
    return <option key={e.id} value={e.id}>{e.nombre}{otro ? ` · ya en ${otro}` : ""}</option>;
  };
  function cambiar(i, valor) {
    const nuevos = [...ids];
    if (valor === "") nuevos.splice(i, 1); else nuevos[i] = Number(valor);
    onGuardar(t.id, { acompanantes: [...new Set(nuevos)] });
  }
  return (
    <div className="acomp-cell">
      {ids.map((id, i) => {
        const actual = entrenadores.find((e) => e.id === id);
        const deVacaciones = actual && !disponibles.includes(actual);
        const opts = deVacaciones ? [actual, ...disponibles] : disponibles;
        return (
          <select key={`${id}-${i}`} value={id} onChange={(e) => cambiar(i, e.target.value)}
            className={deVacaciones ? "vacas" : ""} title={deVacaciones ? "Está de vacaciones esas fechas" : ""}>
            <option value="">— quitar —</option>
            {opts.map(opcion)}
          </select>
        );
      })}
      <select value="" className="anadir" onChange={(e) => e.target.value && onGuardar(t.id, { acompanantes: [...new Set([...ids, Number(e.target.value)])] })}>
        <option value="">{ids.length ? "+ otro…" : "Elegir…"}</option>
        {disponibles.filter((e) => !ids.includes(e.id)).map(opcion)}
      </select>
      {t.acompanante_nota && <span className="muted nota">{t.acompanante_nota}</span>}
    </div>
  );
}

// Jugadores del torneo: todos a la vista. Se arrastran a otro torneo, o se
// toca uno y luego se toca el torneo de destino (móvil).
function JugadoresCell({ t, sel, setSel, onMover, puedeEditar }) {
  const [over, setOver] = useState(false);
  const esDestino = sel && sel.torneo !== t.id;
  return (
    <div className={`torneo-jug${over ? " drop-ok" : ""}${esDestino ? " destino" : ""}`}
      onDragOver={(e) => { if (!puedeEditar) return; e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault(); setOver(false);
        const pid = Number(e.dataTransfer.getData("participante"));
        const desde = Number(e.dataTransfer.getData("torneo"));
        if (pid && desde !== t.id) onMover(pid, desde, t.id);
      }}
      onClick={() => { if (esDestino) { onMover(sel.id, sel.torneo, t.id); setSel(null); } }}>
      {t.jugadores.map((j) => (
        <span key={j.id} draggable={puedeEditar}
          className={`jug-chip${j.certeza !== "CONFIRMADO" ? " dudoso" : ""}${sel?.id === j.id ? " sel" : ""}${puedeEditar ? " movible" : ""}`}
          onDragStart={(e) => {
            e.dataTransfer.setData("participante", String(j.id));
            e.dataTransfer.setData("torneo", String(t.id));
            e.dataTransfer.effectAllowed = "move";
          }}
          onClick={(e) => {
            e.stopPropagation();
            if (!puedeEditar) return;
            setSel(sel?.id === j.id ? null : { id: j.id, torneo: t.id, nombre: j.nombre });
          }}
          title={puedeEditar ? "Arrastra a otro torneo, o toca y luego toca el torneo de destino" : ""}>
          {j.nombre}
        </span>
      ))}
      {!t.jugadores.length && <span className="muted">{esDestino ? "soltar aquí" : "—"}</span>}
    </div>
  );
}

export default function TorneosPage() {
  const hoy = hoyISO();
  const [items, setItems] = useState(null);
  const [resumen, setResumen] = useState(null);
  const [entrenadores, setEntrenadores] = useState([]);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [circuito, setCircuito] = useState("");
  const [mes, setMes] = useState("prox");
  const [soloConJug, setSoloConJug] = useState(false);
  const [sel, setSel] = useState(null);
  // Sube con cada cambio, para que «Deshacer» sepa cuál es el último.
  const [tick, setTick] = useState(0);
  // Semanas con el desplegable de «sin jugadores» abierto. Al buscar se
  // abren todas: si no, un torneo encontrado por su nombre quedaría oculto.
  const [abiertas, setAbiertas] = useState(() => new Set());
  const verSin = (lunes) => abiertas.has(lunes) || q.trim() !== "";
  const alternar = (lunes) => setAbiertas((a) => {
    const n = new Set(a);
    if (n.has(lunes)) n.delete(lunes); else n.add(lunes);
    return n;
  });
  const puedeEditar = canWrite("torneos");

  const rango = useMemo(() => {
    if (mes === "prox") return { desde: hoy, hasta: `${ANIO}-12-31` };
    if (mes === "todo") return { desde: `${ANIO}-01-01`, hasta: `${ANIO}-12-31` };
    const m = Number(mes);
    return { desde: `${ANIO}-${String(m).padStart(2, "0")}-01`, hasta: `${ANIO}-${String(m).padStart(2, "0")}-${new Date(ANIO, m, 0).getDate()}` };
  }, [mes, hoy]);

  const cargar = useCallback(() => getTorneos({ q, circuito, ...rango, con_jugadores: soloConJug ? 1 : "" })
    .then(setItems).catch((e) => setError(e.message)), [q, circuito, rango, soloConJug]);

  const cargarResumen = useCallback(() => getTorneosResumen().then(setResumen).catch(() => {}), []);
  useEffect(() => { cargarResumen(); }, [cargarResumen]);
  useEffect(() => { setItems(null); cargar(); }, [cargar]);
  useEffect(() => {
    getTorneosEntrenadores(rango.desde, rango.hasta).then(setEntrenadores).catch(() => {});
  }, [rango]);

  // Semanas: cada torneo sale en todas las que ocupa, desde la previa si la
  // tiene (un circuito de fines de semana de un mes sale en las cuatro). Solo
  // las semanas del tramo elegido.
  const semanas = useMemo(() => {
    const primerLunes = lunesDe(rango.desde);
    const porLunes = new Map();
    for (const t of items || []) {
      const ss = semanasDe(t);
      ss.forEach((lunes, i) => {
        if (lunes < primerLunes || lunes > rango.hasta) return;
        let g = porLunes.get(lunes);
        if (!g) { g = { lunes, items: [], con: [], sin: [] }; porLunes.set(lunes, g); }
        const fila = { t, lunes, n: i + 1, total: ss.length };
        g.items.push(fila);
        // Primero los torneos a los que va alguien; el resto, plegado debajo.
        (t.jugadores.length ? g.con : g.sin).push(fila);
      });
    }
    return [...porLunes.values()].sort((a, b) => (a.lunes < b.lunes ? -1 : 1));
  }, [items, rango]);

  // ¿Este entrenador ya acompaña a otro torneo que también ocupa esta semana?
  const enSemana = useCallback((entId, t, lunes) => {
    const otro = (items || []).find((x) => x.id !== t.id && (x.acompanantes || []).includes(entId)
      && semanasDe(x).includes(lunes));
    return otro ? otro.nombre.slice(0, 28) : "";
  }, [items]);

  async function guardarCampo(id, body) {
    setError("");
    try {
      const nuevo = await guardarTorneo(id, body);
      setItems((xs) => xs.map((x) => (x.id === id ? { ...x, ...nuevo, jugadores: x.jugadores } : x)));
      setTick((n) => n + 1);
    } catch (e) { setError(e.message); }
  }

  async function mover(pid, desde, hasta) {
    setError("");
    // Se mueve en pantalla al instante y se confirma con el servidor.
    let chip;
    setItems((xs) => xs.map((x) => {
      if (x.id === desde) { chip = x.jugadores.find((j) => j.id === pid); return { ...x, jugadores: x.jugadores.filter((j) => j.id !== pid) }; }
      return x;
    }));
    setItems((xs) => xs.map((x) => (x.id === hasta && chip ? { ...x, jugadores: [...x.jugadores, chip].sort((a, b) => a.nombre.localeCompare(b.nombre)) } : x)));
    try { await updParticipante(pid, { torneo: hasta }); setTick((n) => n + 1); }
    catch (e) { setError(e.message); cargar(); }
  }

  // Una fila de torneo del calendario.
  function filaTorneo({ t, lunes, n, total }) {
    const pasado = t.fecha_fin < hoy;
    const enCurso = inicioEfectivo(t) <= hoy && t.fecha_fin >= hoy;
    const enPrevia = enCurso && hoy < t.fecha_inicio;
    const dCierre = diasHasta(t.cierre_inscripcion);
    return (
      <tr key={`${lunes}-${t.id}`} className={pasado ? "pasado" : enCurso ? "en-curso" : ""}>
        <td className="td-fechas" data-label="Fechas">
          <div className="fechas-bloque">
            <div>{fmtRango(t.fecha_inicio, t.fecha_fin)}{enCurso && <span className="pill live">{enPrevia ? "previa en juego" : "en juego"}</span>}</div>
            {t.qualy_inicio && <div className="previa">Previa {fmtRango(t.qualy_inicio, t.qualy_fin || t.qualy_inicio)}</div>}
            {(total > 1 || t.solo_fines_semana) && (
              <div className="torneo-sub">
                {total > 1 && <span className="pill semana-n">semana {n} de {total}</span>}
                {t.solo_fines_semana && <span className="pill finde">fines de semana</span>}
              </div>
            )}
          </div>
        </td>
        <td data-label="Torneo">
          <Link href={`/torneos/${t.id}`} className="torneo-link">{t.nombre}</Link>
          <div className="torneo-sub">
            {t.circuito && <span className="pill circ">{t.circuito}</span>}
            {t.nivel && <span className="muted">{t.nivel}</span>}
            {t.lugar && <span className="muted">· {t.lugar}</span>}
          </div>
        </td>
        <td className="td-cierre" data-label="Cierre insc.">
          {t.cierre_inscripcion ? (
            <>
              {fmtCorta(t.cierre_inscripcion)}
              {dCierre !== null && dCierre >= 0 && dCierre <= 7 && !pasado && (
                <span className="pill pend">{dCierre === 0 ? "hoy" : `${dCierre} d`}</span>
              )}
            </>
          ) : <span className="muted">—</span>}
        </td>
        <td className="td-coach" data-label="Acompaña">
          <AcompanaCell t={t} lunes={lunes} entrenadores={entrenadores} enSemana={enSemana}
            onGuardar={guardarCampo} puedeEditar={puedeEditar} />
        </td>
        <td className="td-jug" data-label="Jugadores">
          <JugadoresCell t={t} sel={sel} setSel={setSel} onMover={mover} puedeEditar={puedeEditar} />
        </td>
        <td className="td-estado">
          {t.estado !== "VALIDADO" && <span className={`pill ${ESTADO_CLASS[t.estado]}`}>{t.estado_display}</span>}
        </td>
      </tr>
    );
  }
  return (
    <div>
      <div className="page-head">
        <h1>Calendario de torneos</h1>
        {puedeEditar && (
          <div className="row-actions">
            <DeshacerTorneos tick={tick} onDeshecho={() => { cargar(); cargarResumen(); }} />
            <Link href="/torneos/nuevo" className="btn">+ Nuevo torneo</Link>
          </div>
        )}
      </div>
      {puedeEditar ? (
        <p className="help">
          Semana a semana, lo que queda de <b>{ANIO}</b>: cada torneo sale en todas las semanas que dura, desde la previa si la tiene. En «Acompaña»
          solo se ofrecen entrenadores que no están de vacaciones esas fechas. Los jugadores se pueden
          <b> arrastrar de un torneo a otro</b> (en el móvil: tocar el jugador y luego el torneo de destino).
          Los nombres en <span className="jug-chip dudoso">naranja</span> vienen del Excel con dudas.
        </p>
      ) : (
        <p className="help">
          Semana a semana, lo que queda de <b>{ANIO}</b>: cada torneo sale en todas las semanas que dura, con quién
          acompaña y qué jugadores van. Es solo consulta: los cambios los hacen los head coaches y dirección.
          Los nombres en <span className="jug-chip dudoso">naranja</span> vienen del Excel con dudas.
        </p>
      )}

      {resumen && (
        <div className="metrics">
          <div className="metric"><div className="label">Torneos en el calendario</div><div className="value">{resumen.total}</div></div>
          <div className="metric"><div className="label">Con jugadores apuntados</div><div className="value">{resumen.con_jugadores}</div></div>
          <div className="metric"><div className="label">En juego esta semana</div><div className="value">{resumen.en_curso}</div></div>
          <div className="metric"><div className="label">Cierres en 3 semanas</div><div className="value">{resumen.proximos_cierres.length}</div></div>
        </div>
      )}

      {resumen?.proximos_cierres?.length > 0 && (
        <div className="card cierres-card">
          <div className="cierres-head">Próximos cierres de inscripción</div>
          <ul className="cierres-lista">
            {resumen.proximos_cierres.map((t) => {
              const dias = diasHasta(t.cierre_inscripcion);
              return (
                <li key={t.id}>
                  <span className={`cierre-dias${dias <= 3 ? " urgente" : ""}`}>
                    {dias === 0 ? "hoy" : dias === 1 ? "mañana" : `${dias} días`}
                  </span>
                  <Link href={`/torneos/${t.id}`}>{t.nombre}</Link>
                  <span className="muted">cierra el {fmtCorta(t.cierre_inscripcion)} · empieza el {fmtCorta(t.fecha_inicio)} · {t.n_jugadores} jug.</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div className="toolbar torneos-toolbar">
        <input className="search" placeholder="Buscar torneo, ciudad, jugador o coach…" value={q}
          onChange={(e) => setQ(e.target.value)} />
        <select className="filtro-select" value={mes} onChange={(e) => setMes(e.target.value)}>
          <option value="prox">Desde hoy</option>
          <option value="todo">Todo {ANIO}</option>
          {MESES.map((m, i) => <option key={m} value={i + 1}>{m[0].toUpperCase() + m.slice(1)}</option>)}
        </select>
        <select className="filtro-select" value={circuito} onChange={(e) => setCircuito(e.target.value)}>
          <option value="">Todos los circuitos</option>
          {(resumen?.circuitos || []).map((c) => <option key={c.nombre} value={c.nombre}>{c.nombre} ({c.n})</option>)}
        </select>
        <label className="check filtro-check">
          <input type="checkbox" checked={soloConJug} onChange={(e) => setSoloConJug(e.target.checked)} />
          Solo con jugadores
        </label>
      </div>

      {sel && (
        <div className="mover-bar">
          <span>Moviendo a <b>{sel.nombre}</b>: toca el torneo de destino.</span>
          <button type="button" className="btn ghost sm" onClick={() => setSel(null)}>Cancelar</button>
        </div>
      )}
      {error && <p className="err">{error}</p>}
      {!items && !error && <p className="msg">Cargando torneos…</p>}
      {items && items.length === 0 && <p className="msg">No hay torneos con esos filtros.</p>}

      {items && items.length > 0 && (
        <div className="card">
          <table className="data tabla-torneos">
            <thead>
              <tr><th>Fechas</th><th>Torneo</th><th>Cierre insc.</th><th>Acompaña</th><th>Jugadores</th><th></th></tr>
            </thead>
            {semanas.map((s, i) => {
              const color = `sem-${i % COLORES_SEMANA}`;
              return (
                <tbody key={s.lunes} className={`semana ${color}`}>
                  <tr className="fila-semana">
                    <td colSpan={6}>
                      <span className="sem-marca" />
                      <b>Semana {fmtSemana(s.lunes)}</b>
                      <span className="muted"> · {s.con.length} con jugadores{s.sin.length ? ` · ${s.sin.length} sin jugadores` : ""}</span>
                      {puedeEditar && (
                        <Link className="link-mas" href={`/torneos/nuevo?desde=${s.lunes}`}>+ añadir un torneo esta semana</Link>
                      )}
                    </td>
                  </tr>
                  {s.con.map(filaTorneo)}
                  {s.sin.length > 0 && (
                    <tr className="fila-otros">
                      <td colSpan={6}>
                        <button type="button" className="btn-otros" aria-expanded={verSin(s.lunes)}
                          onClick={() => alternar(s.lunes)}>
                          <span className="flecha">{verSin(s.lunes) ? "▾" : "▸"}</span>
                          {verSin(s.lunes) ? "Ocultar" : "Ver"} {s.con.length ? "los otros " : "los "}
                          {s.sin.length} torneo{s.sin.length !== 1 ? "s" : ""} de la semana sin jugadores
                        </button>
                      </td>
                    </tr>
                  )}
                  {verSin(s.lunes) && s.sin.map(filaTorneo)}
                </tbody>
              );
            })}
          </table>
        </div>
      )}
    </div>
  );
}
