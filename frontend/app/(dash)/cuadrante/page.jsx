"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Avatar from "../../../components/Avatar";
import { useIsMobile } from "../../../lib/useIsMobile";
import { SUPERFICIE_LABEL, SUPERFICIE_COLOR } from "../../../lib/format";
import {
  getCuadrante,
  getLatestSemana,
  getPanel,
  generarSemana,
  regenerarTarde,
  publicarSemana,
  despublicarSemana,
  swapAsignacion,
  manualAssign,
  moverAsignacion,
  setCoach,
  removeAsignacion,
} from "../../../lib/api";

const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];
const ESTADO_COLOR = {
  DISPONIBLE: "var(--st-disponible)",
  AUSENCIA_JUGADOR: "var(--st-ausencia)",
  CALENTAMIENTO: "var(--st-calentamiento)",
  EN_TORNEO: "var(--st-torneo)",
  CLIMATOLOGIA: "var(--st-clima)",
  AUSENCIA_COACH: "var(--st-coach)",
};
const ESTADO_LABEL = {
  AUSENCIA_JUGADOR: "Ausencia",
  CALENTAMIENTO: "Calentamiento",
  EN_TORNEO: "En torneo",
  CLIMATOLOGIA: "Climatología",
  AUSENCIA_COACH: "Ausencia coach",
};
const noDisponible = (estado) => estado && estado !== "DISPONIBLE";

function setDrag(e, payload) {
  e.dataTransfer.setData("application/json", JSON.stringify(payload));
  e.dataTransfer.effectAllowed = "move";
}
const overOn = (e) => { e.preventDefault(); e.currentTarget.classList.add("drop-ok"); };
const overOff = (e) => e.currentTarget.classList.remove("drop-ok");
function readDrag(e) {
  try { return JSON.parse(e.dataTransfer.getData("application/json")); } catch { return null; }
}

// Extrae el banquillo (jugadores sin pista) de la respuesta de /panel.
function benchPlayers(panel) {
  if (!panel) return [];
  const out = [];
  for (const g of [...(panel.por_entrenador || []), ...(panel.sin_entrenador || [])]) {
    for (const j of g.jugadores || []) {
      if (!j.tiene_asignacion) {
        out.push({ id: j.id, nombre: j.nombre, foto: j.foto_url, division: j.division_nivel, coach: g.entrenador?.nombre, estado: j.estado });
      }
    }
  }
  out.sort((a, b) => (a.nombre || "").localeCompare(b.nombre || ""));
  return out;
}

function Inner() {
  const searchParams = useSearchParams();
  const qpSemana = searchParams.get("semana");
  const [semanaId, setSemanaId] = useState(null);
  const [dia, setDia] = useState(0);
  const [data, setData] = useState(null);
  const [panel, setPanel] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const isMobile = useIsMobile();
  const [turnoIdx, setTurnoIdx] = useState(0);
  const [sel, setSel] = useState(null); // selección táctil (móvil): {k, jugador?, entrenador?, asignacion?, label}
  const [showRehacerMenu, setShowRehacerMenu] = useState(false);

  async function load(id, d) {
    setError(null);
    try {
      const sid = id ?? (await getLatestSemana())?.id;
      if (!sid) { setError("No hay semanas. Crea una en Semanas y pulsa Generar."); return; }
      setSemanaId(sid);
      const [cua, pan] = await Promise.all([getCuadrante(sid, d), getPanel(sid, d)]);
      setData(cua);
      setPanel(pan);
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  useEffect(() => {
    load(qpSemana ? Number(qpSemana) : null, dia);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dia, qpSemana]);

  async function run(label, fn) {
    setBusy(label);
    try { await fn(); await load(semanaId, dia); }
    catch (e) { setError(String(e.message || e)); }
    finally { setBusy(null); }
  }

  // Operación de drag&drop: ejecuta y recarga; muestra el error de la API si lo hay.
  async function op(fn) {
    setError(null);
    try { await fn(); await load(semanaId, dia); }
    catch (e) {
      let msg = String(e.message || e);
      try { msg = JSON.parse(msg).error || msg; } catch {}
      setError(msg);
    }
  }

  function onDropCell(ctx) {
    return (e) => {
      e.preventDefault(); overOff(e);
      const s = readDrag(e);
      if (!s) return;
      if (s.k === "bj") op(() => manualAssign({ jugador_id: s.jugador, semana: ctx.semana, dia: ctx.dia, turno: ctx.turno, pista: ctx.pista }));
      // Traer a alguien de otra pista: así se abre una pista vacía sin tener
      // que intercambiarlo con nadie.
      else if (s.k === "cj") op(() => moverAsignacion({ asignacion: s.asignacion, dia: ctx.dia, turno: ctx.turno, pista: ctx.pista }));
      else if (s.k === "be") op(() => setCoach({ semana: ctx.semana, dia: ctx.dia, turno: ctx.turno, pista: ctx.pista, entrenador_id: s.entrenador }));
      // Entrenador arrastrado desde otra pista a una celda sin entrenador: se
      // traslada, no se duplica.
      else if (s.k === "cc") op(() => setCoach({ semana: ctx.semana, dia: ctx.dia, turno: ctx.turno, pista: ctx.pista, entrenador_id: s.entrenadorId, desde_pista: s.pista, desde_turno: s.turno, desde_dia: s.dia }));
    };
  }
  function onDropPlayer(targetAsig, ctx) {
    return (e) => {
      e.preventDefault(); e.stopPropagation(); overOff(e);
      const s = readDrag(e);
      if (!s) return;
      if (s.k === "cj" && s.asignacion !== targetAsig) op(() => swapAsignacion(s.asignacion, targetAsig, "jugador"));
      else if (s.k === "bj") op(() => manualAssign({ jugador_id: s.jugador, semana: ctx.semana, dia: ctx.dia, turno: ctx.turno, pista: ctx.pista }));
      else if (s.k === "be") op(() => setCoach({ semana: ctx.semana, dia: ctx.dia, turno: ctx.turno, pista: ctx.pista, entrenador_id: s.entrenador }));
    };
  }
  function onDropCoach(targetAsig, ctx) {
    return (e) => {
      e.preventDefault(); e.stopPropagation(); overOff(e);
      const s = readDrag(e);
      if (!s) return;
      if (s.k === "cc" && s.asignacion !== targetAsig) op(() => swapAsignacion(s.asignacion, targetAsig, "entrenador"));
      else if (s.k === "be") op(() => setCoach({ semana: ctx.semana, dia: ctx.dia, turno: ctx.turno, pista: ctx.pista, entrenador_id: s.entrenador }));
    };
  }
  function onDropBench(e) {
    e.preventDefault(); overOff(e);
    const s = readDrag(e);
    if (s && s.k === "cj") op(() => removeAsignacion(s.asignacion));
  }

  // ----- Interacción táctil (móvil): tocar origen → tocar destino -----
  function pick(next) {
    setSel((cur) =>
      cur && cur.k === next.k && cur.jugador === next.jugador &&
      cur.entrenador === next.entrenador && cur.asignacion === next.asignacion
        ? null : next
    );
  }
  // Coloca la selección actual en una pista (ctx) según lo que ya haya en ella.
  function placeOnCell(ctx, items) {
    if (!sel) return;
    const s = sel;
    const firstPlayer = (items || []).find((a) => a.jugador_nombre);
    const coachAsig = items && items[0] && items[0].entrenador_nombre ? items[0].id : null;
    if (s.k === "bj") op(() => manualAssign({ jugador_id: s.jugador, ...ctx }));
    else if (s.k === "cj") {
      if (firstPlayer && firstPlayer.id !== s.asignacion) op(() => swapAsignacion(s.asignacion, firstPlayer.id, "jugador"));
      else if (!firstPlayer) op(() => moverAsignacion({ asignacion: s.asignacion, dia: ctx.dia, turno: ctx.turno, pista: ctx.pista }));
    }
    else if (s.k === "be") op(() => setCoach({ ...ctx, entrenador_id: s.entrenador }));
    else if (s.k === "cc") {
      if (coachAsig && coachAsig !== s.asignacion) op(() => swapAsignacion(s.asignacion, coachAsig, "entrenador"));
      else if (!coachAsig) op(() => setCoach({ ...ctx, entrenador_id: s.entrenadorId, desde_pista: s.pista, desde_turno: s.turno, desde_dia: s.dia }));
    }
    setSel(null);
  }
  function placeOnBench() {
    if (sel && sel.k === "cj") op(() => removeAsignacion(sel.asignacion));
    setSel(null);
  }

  if (error && !data) return <div><p className="err">{error}</p></div>;
  if (!data) return <p className="msg">Cargando cuadrante…</p>;

  const cellMap = {};
  for (const a of data.asignaciones) (cellMap[`${a.pista}_${a.turno}`] ||= []).push(a);
  const publicado = data.semana.estado === "PUBLICADO";
  const bench = benchPlayers(panel);
  const benchCoaches = panel?.entrenadores_libres || [];
  // Todos los entrenadores con su estado franja a franja: los de la tabla de
  // la derecha, de donde se arrastra para forzar a quien haga falta.
  const coaches = panel?.entrenadores || [];

  // ---------------- Vista móvil: lista por pista + tocar-para-mover ----------------
  if (isMobile) {
    const turnos = data.turnos;
    const tIdx = Math.min(turnoIdx, Math.max(0, turnos.length - 1));
    const turno = turnos[tIdx];

    return (
      <div className="mcuadrante">
        <div className="page-head">
          <h1>Cuadrante</h1>
          <span className={`badge ${publicado ? "pub" : ""}`}>{publicado ? "Publicado" : "Borrador"}</span>
        </div>
        <p className="now-horas">{data.semana.fecha_inicio}</p>

        <div className="controls mscroll">
          {DIAS.map((d, i) => (
            <button key={i} className={i === dia ? "active" : ""} onClick={() => setDia(i)}>{d.slice(0, 3)}</button>
          ))}
        </div>
        <div className="controls mscroll">
          {turnos.map((t, i) => (
            <button key={t.id} className={i === tIdx ? "active" : ""} onClick={() => setTurnoIdx(i)}>{t.codigo}</button>
          ))}
        </div>
        <div className="controls">
          <div style={{ position: "relative", display: "inline-block" }}>
            <button
              className="btn ghost sm"
              disabled={!!busy}
              onClick={() => setShowRehacerMenu(!showRehacerMenu)}
            >
              {busy?.startsWith("gen") || busy === "tarde" ? "…" : "⚙️ Rehacer ▾"}
            </button>
            {showRehacerMenu && (
              <>
                <div
                  style={{ position: "fixed", inset: 0, zIndex: 99 }}
                  onClick={() => setShowRehacerMenu(false)}
                />
                <div
                  style={{
                    position: "absolute",
                    left: 0,
                    top: "100%",
                    marginTop: 4,
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    boxShadow: "0 8px 24px rgba(0,0,0,0.25)",
                    zIndex: 100,
                    minWidth: 220,
                    padding: "4px 0",
                    display: "flex",
                    flexDirection: "column",
                  }}
                >
                  <button
                    className="btn ghost sm"
                    style={{ width: "100%", textAlign: "left", justifyContent: "flex-start", borderRadius: 0, padding: "6px 12px", border: "none" }}
                    onClick={() => {
                      setShowRehacerMenu(false);
                      if (window.confirm("¿Rehacer toda la semana?")) run("gen-all", () => generarSemana(semanaId));
                    }}
                  >
                    🔄 Toda la semana
                  </button>
                  {dia > 0 && dia < 5 && (
                    <button
                      className="btn ghost sm"
                      style={{ width: "100%", textAlign: "left", justifyContent: "flex-start", borderRadius: 0, padding: "6px 12px", border: "none" }}
                      onClick={() => {
                        setShowRehacerMenu(false);
                        if (window.confirm(`¿Rehacer desde el ${DIAS[dia]}?`)) run(`gen-desde-${dia}`, () => generarSemana(semanaId, { desde_dia: dia }));
                      }}
                    >
                      ⏩ Desde {DIAS[dia]}
                    </button>
                  )}
                  {dia < 5 && (
                    <button
                      className="btn ghost sm"
                      style={{ width: "100%", textAlign: "left", justifyContent: "flex-start", borderRadius: 0, padding: "6px 12px", border: "none" }}
                      onClick={() => {
                        setShowRehacerMenu(false);
                        if (window.confirm(`¿Rehacer solo ${DIAS[dia]}?`)) run(`gen-solo-${dia}`, () => generarSemana(semanaId, { solo_dia: dia }));
                      }}
                    >
                      📅 Solo {DIAS[dia]}
                    </button>
                  )}
                  <button
                    className="btn ghost sm"
                    style={{ width: "100%", textAlign: "left", justifyContent: "flex-start", borderRadius: 0, padding: "6px 12px", border: "none" }}
                    onClick={() => {
                      setShowRehacerMenu(false);
                      run("tarde", () => regenerarTarde(semanaId, dia));
                    }}
                  >
                    🌤️ Tarde ({DIAS[dia]})
                  </button>
                </div>
              </>
            )}
          </div>
          {publicado ? (
            <>
              <button className="btn ghost sm" disabled={!!busy} onClick={() => run("despub", () => despublicarSemana(semanaId))}>
                {busy === "despub" ? "…" : "Borrador"}
              </button>
              <button className="btn sm" disabled={!!busy} onClick={() => run("pub", () => publicarSemana(semanaId))}>
                {busy === "pub" ? "…" : "Republicar"}
              </button>
            </>
          ) : (
            <button className="btn sm" disabled={!!busy} onClick={() => run("pub", () => publicarSemana(semanaId))}>
              {busy === "pub" ? "…" : "Publicar"}
            </button>
          )}
        </div>

        {error && <p className="err">{error}</p>}

        {sel && (
          <div className="tap-hint">
            <span>Movimiento: <b>{sel.label}</b> · toca una pista{sel.k === "cj" ? " o el banquillo" : ""}</span>
            <button className="btn ghost sm" onClick={() => setSel(null)}>Cancelar</button>
          </div>
        )}

        {data.sedes.map((sede) => (
          <div key={sede.id} className="msede">
            <div className="msede-title">{sede.nombre}{sede.es_satelite ? " · satélite" : ""}</div>
            {sede.pistas.map((p) => {
              const items = cellMap[`${p.id}_${turno.id}`];
              const ctx = { semana: semanaId, dia, turno: turno.id, pista: p.id };
              const empty = !items || items.length === 0;
              const color = empty ? "var(--border-strong)" : (ESTADO_COLOR[items[0].estado] || "var(--border-strong)");
              return (
                <div
                  key={p.id}
                  className={`mcell${empty ? " empty" : ""}${sel ? " targetable" : ""}`}
                  style={{ borderLeftColor: color }}
                  onClick={() => sel && placeOnCell(ctx, items)}
                >
                  <div className="mcell-head">
                    <span className="mcell-pista">P{p.numero}</span>
                    {p.superficie && (
                      <span className="surf-dot" title={SUPERFICIE_LABEL[p.superficie]}
                        style={{ background: SUPERFICIE_COLOR[p.superficie] }} />
                    )}
                    {sel && <span className="mcell-place">Colocar aquí →</span>}
                  </div>
                  {(items || []).map((a) => {
                    const selected = sel && sel.k === "cj" && sel.asignacion === a.id;
                    return (
                      <div key={a.id} className={`mchip${selected ? " sel" : ""}`}
                        onClick={(e) => { e.stopPropagation(); pick({ k: "cj", asignacion: a.id, label: a.jugador_nombre }); }}>
                        <Avatar nombre={a.jugador_nombre} fotoUrl={a.jugador_foto} kind="player" />
                        <i className="dot" style={{ background: ESTADO_COLOR[a.estado] }} />
                        <span>{a.jugador_nombre}{a.division_nivel ? ` · D${a.division_nivel}` : ""}</span>
                      </div>
                    );
                  })}
                  {!empty && items[0].entrenador_nombre ? (
                    <div className={`mchip coach${sel && sel.k === "cc" && sel.asignacion === items[0].id ? " sel" : ""}`}
                      onClick={(e) => { e.stopPropagation(); pick({ k: "cc", asignacion: items[0].id, label: items[0].entrenador_nombre }); }}>
                      <Avatar nombre={items[0].entrenador_nombre} fotoUrl={items[0].entrenador_foto} kind="coach" />
                      <span>{items[0].entrenador_nombre}</span>
                    </div>
                  ) : null}
                  {empty && <span className="cell-empty-hint">Libre</span>}
                </div>
              );
            })}
          </div>
        ))}

        <div className={`bench mbench${sel && sel.k === "cj" ? " droppable" : ""}`} onClick={() => sel && sel.k === "cj" && placeOnBench()}>
          <div className="bench-title">Banquillo · sin pista <span className="bench-count">{bench.length}</span></div>
          {sel && sel.k === "cj" && <div className="bench-side-hint">Toca aquí para quitar de la pista</div>}
          <div className="bench-items">
            {bench.length === 0 ? <span className="bench-empty">Todos tienen pista.</span> :
              bench.map((p) => {
                const selected = sel && sel.k === "bj" && sel.jugador === p.id;
                return (
                  <div key={p.id} className={`bench-chip${noDisponible(p.estado) ? " nd" : ""}${selected ? " sel" : ""}`}
                    onClick={(e) => { e.stopPropagation(); pick({ k: "bj", jugador: p.id, label: p.nombre }); }}>
                    {noDisponible(p.estado) && (
                      <span className="bench-state-dot" style={{ background: ESTADO_COLOR[p.estado] || "var(--border-strong)" }} />
                    )}
                    <Avatar nombre={p.nombre} fotoUrl={p.foto} kind="player" />
                    <span>{p.nombre}{p.division ? ` · D${p.division}` : ""}</span>
                  </div>
                );
              })}
          </div>
          {coaches.length > 0 && (
            <>
              <div className="bench-title sm">Entrenadores · {turnos[tIdx]?.codigo}</div>
              <div className="bench-items">
                {coaches.map((e2) => {
                  const selected = sel && sel.k === "be" && sel.entrenador === e2.id;
                  const f = (e2.franjas || {})[turnos[tIdx]?.id] || {};
                  const ocupado = f.pistas && f.pistas.length;
                  const donde = ocupado ? f.pistas.map((x) => x.split(" ").pop()).join(",") : (f.libre ? "libre" : (f.motivo || "—"));
                  return (
                    <div key={e2.id} className={`bench-chip${selected ? " sel" : ""}${ocupado || !f.libre ? " nd" : ""}`}
                      onClick={(e) => { e.stopPropagation(); pick({ k: "be", entrenador: e2.id, label: e2.nombre }); }}
                      title={ocupado ? `En ${f.pistas.join(" y ")}` : (f.motivo || "Libre")}>
                      <Avatar nombre={e2.nombre} fotoUrl={e2.foto_url} kind="coach" />
                      <span>{e2.nombre} · {donde}</span>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="page-head">
        <h1>Cuadrante · {data.semana.fecha_inicio}</h1>
        <span className={`badge ${publicado ? "pub" : ""}`}>
          {publicado ? "Publicado" : "Borrador · pendiente de publicar"}
        </span>
      </div>

      <div className="controls">
        {DIAS.map((d, i) => (
          <button key={i} className={i === dia ? "active" : ""} onClick={() => setDia(i)}>{d}</button>
        ))}
        <span style={{ flex: 1 }} />
        <div style={{ position: "relative", display: "inline-block" }}>
          <button
            className="btn ghost sm"
            disabled={!!busy}
            onClick={() => setShowRehacerMenu(!showRehacerMenu)}
            title="Opciones para rehacer o actualizar el cuadrante con las ausencias actuales"
          >
            {busy?.startsWith("gen") || busy === "tarde" ? "Actualizando…" : "⚙️ Rehacer / Actualizar ▾"}
          </button>
          {showRehacerMenu && (
            <>
              <div
                style={{ position: "fixed", inset: 0, zIndex: 99 }}
                onClick={() => setShowRehacerMenu(false)}
              />
              <div
                style={{
                  position: "absolute",
                  right: 0,
                  top: "100%",
                  marginTop: 4,
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  boxShadow: "0 8px 24px rgba(0,0,0,0.25)",
                  zIndex: 100,
                  minWidth: 260,
                  padding: "6px 0",
                  display: "flex",
                  flexDirection: "column",
                }}
              >
                <button
                  className="btn ghost sm"
                  style={{ width: "100%", textAlign: "left", justifyContent: "flex-start", borderRadius: 0, padding: "8px 14px", border: "none" }}
                  onClick={() => {
                    setShowRehacerMenu(false);
                    if (window.confirm("¿Rehacer la semana completa (Lunes a Viernes)? Se recalcularán las asignaciones considerando todas las ausencias y disponibilidades actuales.")) {
                      run("gen-all", () => generarSemana(semanaId));
                    }
                  }}
                >
                  🔄 <b>Toda la semana</b> (Lunes a Viernes)
                </button>

                {dia > 0 && dia < 5 && (
                  <button
                    className="btn ghost sm"
                    style={{ width: "100%", textAlign: "left", justifyContent: "flex-start", borderRadius: 0, padding: "8px 14px", border: "none" }}
                    onClick={() => {
                      setShowRehacerMenu(false);
                      if (window.confirm(`¿Rehacer desde el ${DIAS[dia]} hasta el Viernes? Los días anteriores se mantendrán intactos.`)) {
                        run(`gen-desde-${dia}`, () => generarSemana(semanaId, { desde_dia: dia }));
                      }
                    }}
                  >
                    ⏩ <b>Desde {DIAS[dia]}</b> (hasta Viernes)
                  </button>
                )}

                {dia < 5 && (
                  <button
                    className="btn ghost sm"
                    style={{ width: "100%", textAlign: "left", justifyContent: "flex-start", borderRadius: 0, padding: "8px 14px", border: "none" }}
                    onClick={() => {
                      setShowRehacerMenu(false);
                      if (window.confirm(`¿Rehacer solo el ${DIAS[dia]} (mañana y tarde)?`)) {
                        run(`gen-solo-${dia}`, () => generarSemana(semanaId, { solo_dia: dia }));
                      }
                    }}
                  >
                    📅 <b>Solo {DIAS[dia]}</b> (día completo)
                  </button>
                )}

                <button
                  className="btn ghost sm"
                  style={{ width: "100%", textAlign: "left", justifyContent: "flex-start", borderRadius: 0, padding: "8px 14px", border: "none" }}
                  onClick={() => {
                    setShowRehacerMenu(false);
                    run("tarde", () => regenerarTarde(semanaId, dia));
                  }}
                >
                  🌤️ <b>Regenerar tarde</b> ({DIAS[dia]})
                </button>
              </div>
            </>
          )}
        </div>

        {publicado ? (
          <>
            <button
              className="btn ghost sm"
              disabled={!!busy}
              title="Volver a borrador para realizar ajustes"
              onClick={() => run("despub", () => despublicarSemana(semanaId))}
            >
              {busy === "despub" ? "…" : "A borrador"}
            </button>
            <button
              className="btn sm"
              disabled={!!busy}
              title="Actualizar fecha de publicación"
              onClick={() => run("pub", () => publicarSemana(semanaId))}
            >
              {busy === "pub" ? "…" : "Republicar"}
            </button>
          </>
        ) : (
          <button
            className="btn sm"
            disabled={!!busy}
            onClick={() => run("pub", () => publicarSemana(semanaId))}
          >
            {busy === "pub" ? "Publicando…" : "Publicar"}
          </button>
        )}
      </div>

      {error && <p className="err">{error}</p>}
      <p className="dnd-hint">Arrastra jugadores/entrenadores entre pistas para intercambiarlos, desde el banquillo a una pista para colocarlos, o de una pista al banquillo para quitarlos. Para abrir una pista vacía, suelta ahí a quien quieras —del banquillo o de otra pista— y después arrástrale el entrenador.</p>

      <div className="dnd-layout">
        <div className="dnd-main">
          <table className="grid">
            <thead>
              <tr><th></th>{data.turnos.map((t) => <th key={t.id}>{t.codigo}</th>)}</tr>
            </thead>
            <tbody>
              {data.sedes.map((sede) => (
                <tr key={`h-${sede.id}`} className="sede-row"><td colSpan={data.turnos.length + 1}>{sede.nombre}{sede.es_satelite ? " · satélite" : ""}</td></tr>
              )).flatMap((header, si) => {
                const sede = data.sedes[si];
                return [header, ...sede.pistas.map((p) => (
                  <tr key={p.id}>
                    <td className="pista-label">
                      P{p.numero}
                      {p.superficie && (
                        <span className="surf-dot" title={SUPERFICIE_LABEL[p.superficie]}
                          style={{ background: SUPERFICIE_COLOR[p.superficie] }} />
                      )}
                    </td>
                    {data.turnos.map((t) => (
                      <Cell
                        key={t.id}
                        items={cellMap[`${p.id}_${t.id}`]}
                        ctx={{ semana: semanaId, dia, turno: t.id, pista: p.id }}
                        onDropCell={onDropCell}
                        onDropPlayer={onDropPlayer}
                        onDropCoach={onDropCoach}
                      />
                    ))}
                  </tr>
                ))];
              })}
            </tbody>
          </table>
        </div>

        <aside className="bench-side" onDragOver={overOn} onDragLeave={overOff} onDrop={onDropBench}>
          <div className="bench-title">Banquillo · sin pista <span className="bench-count">{bench.length}</span></div>
          <div className="bench-side-hint">Arrastra a una pista para colocar · suelta aquí para quitar</div>
          <div className="bench-scroll">
            <div className="bench-col-items">
              {bench.length === 0 ? <span className="bench-empty">Todos tienen pista.</span> :
                bench.map((p) => (
                  <div key={p.id} className={`bench-chip dnd${noDisponible(p.estado) ? " nd" : ""}`} draggable
                    onDragStart={(e) => setDrag(e, { k: "bj", jugador: p.id })}
                    title={`${p.nombre}${p.coach ? " · " + p.coach : ""}${noDisponible(p.estado) ? " · " + (ESTADO_LABEL[p.estado] || p.estado) + " (arrastra para forzar pista)" : ""}`}>
                    {noDisponible(p.estado) && (
                      <span className="bench-state-dot" style={{ background: ESTADO_COLOR[p.estado] || "var(--border-strong)" }} />
                    )}
                    <Avatar nombre={p.nombre} fotoUrl={p.foto} kind="player" />
                    <span>{p.nombre}{p.division ? ` · D${p.division}` : ""}</span>
                  </div>
                ))}
            </div>
            {coaches.length > 0 && (
              <>
                <div className="bench-title sm">Entrenadores por franja</div>
                <div className="bench-side-hint">Arrástralos a una pista. Se puede forzar a quien ya está en otra pista a esa hora.</div>
                <table className="coach-grid">
                  <thead>
                    <tr><th /> {data.turnos.map((t) => <th key={t.id}>{t.codigo}</th>)}</tr>
                  </thead>
                  <tbody>
                    {coaches.map((c) => (
                      <tr key={c.id}>
                        <td>
                          <div className="bench-chip dnd" draggable
                            onDragStart={(e) => setDrag(e, { k: "be", entrenador: c.id })}
                            onClick={() => pick({ k: "be", entrenador: c.id })}
                            title={`${c.nombre} · arrastra a una pista`}>
                            <Avatar nombre={c.nombre} fotoUrl={c.foto_url} kind="coach" />
                            <span>{c.nombre}</span>
                          </div>
                        </td>
                        {data.turnos.map((t) => {
                          const f = (c.franjas || {})[t.id] || {};
                          const clase = f.pistas && f.pistas.length ? "ocupado" : (f.libre ? "libre" : "fuera");
                          const texto = f.pistas && f.pistas.length
                            ? f.pistas.map((x) => x.split(" ").pop()).join(",")
                            : (f.libre ? "libre" : "—");
                          return (
                            <td key={t.id} className={`coach-slot ${clase}`}
                              title={f.pistas && f.pistas.length ? `En ${f.pistas.join(" y ")}` : (f.motivo || "Libre")}>
                              {texto}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

function Cell({ items, ctx, onDropCell, onDropPlayer, onDropCoach }) {
  const empty = !items || items.length === 0;
  const color = empty ? "var(--border-strong)" : (ESTADO_COLOR[items[0].estado] || "var(--border-strong)");
  return (
    <td className={`cell ${empty ? "empty" : ""}`} style={{ borderLeftColor: color }}
      onDragOver={overOn} onDragLeave={overOff} onDrop={onDropCell(ctx)}>
      {(items || []).map((a) => (
        <div className="player dnd" key={a.id} draggable
          onDragStart={(e) => setDrag(e, { k: "cj", asignacion: a.id })}
          onDragOver={overOn} onDragLeave={overOff} onDrop={onDropPlayer(a.id, ctx)}
          title="Arrastra para intercambiar / al banquillo">
          <Avatar nombre={a.jugador_nombre} fotoUrl={a.jugador_foto} kind="player" />
          <i className="dot" style={{ background: ESTADO_COLOR[a.estado] }} />
          <span>{a.jugador_nombre}</span>
          {a.division_nivel ? <span className="div">D{a.division_nivel}</span> : null}
        </div>
      ))}
      {!empty && items[0].entrenador_nombre ? (
        <div className="coach dnd" draggable
          onDragStart={(e) => setDrag(e, { k: "cc", asignacion: items[0].id, entrenadorId: items[0].entrenador,
                                           pista: ctx.pista, turno: ctx.turno, dia: ctx.dia })}
          onDragOver={overOn} onDragLeave={overOff} onDrop={onDropCoach(items[0].id, ctx)}
          title="Arrastra para intercambiar entrenador">
          <Avatar nombre={items[0].entrenador_nombre} fotoUrl={items[0].entrenador_foto} kind="coach" />
          {items[0].entrenador_nombre}
        </div>
      ) : null}
      {empty ? <span className="cell-empty-hint">—</span> : null}
    </td>
  );
}

export default function CuadrantePage() {
  return (
    <Suspense fallback={<p className="msg">Cargando…</p>}>
      <Inner />
    </Suspense>
  );
}
