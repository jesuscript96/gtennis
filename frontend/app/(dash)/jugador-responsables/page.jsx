"use client";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  getEntrenadoresJugador, guardarEntrenadoresJugador, resource,
} from "../../../lib/api";

const PRINCIPAL = 1;
const SECUNDARIO = 2;

/**
 * Los entrenadores de un alumno: quién le gestiona y con quién entrena.
 *
 * Con quién entrena va en porcentaje: un principal —el de su columna del
 * organigrama— y el resto de su grupo de secundarios, con un 10% como mínimo.
 * El motor reparte los entrenadores de cada turno para acercarse a esos
 * porcentajes a lo largo de la semana; la división ya no cuenta para eso.
 *
 * Se teclea a mano y se guarda todo a la vez: a medio escribir nunca suma 100,
 * así que mientras tanto solo se avisa.
 */
function Inner() {
  const jugadorId = useSearchParams().get("jugador");
  const [datos, setDatos] = useState(null);
  const [filas, setFilas] = useState([]);
  const [responsable, setResponsable] = useState("");
  const [entrenadores, setEntrenadores] = useState([]);
  const [nuevo, setNuevo] = useState("");
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [guardando, setGuardando] = useState(false);

  const cargar = (d) => {
    setDatos(d);
    setFilas(d.entrenadores);
    setResponsable(d.responsable ? String(d.responsable) : "");
  };

  useEffect(() => {
    if (!jugadorId) return;
    getEntrenadoresJugador(jugadorId).then(cargar).catch((e) => setError(e.message));
    resource("entrenadores").list()
      .then((l) => setEntrenadores(l.filter((e) => e.activo)))
      .catch(() => {});
  }, [jugadorId]);

  if (!jugadorId) {
    return <p className="msg">Abre esta página desde el botón «Entrenadores» de un jugador.</p>;
  }
  if (!datos) return error ? <p className="err">{error}</p> : <p className="msg">Cargando…</p>;

  const minimo = datos.minimo_secundario;
  const total = filas.reduce((s, f) => s + (Number(f.porcentaje) || 0), 0);
  const problemas = [];
  if (filas.length) {
    if (!filas.some((f) => f.prioridad === PRINCIPAL)) problemas.push("Falta el entrenador principal.");
    if (filas.some((f) => f.prioridad === SECUNDARIO && Number(f.porcentaje) < minimo)) {
      problemas.push(`Un secundario lleva como mínimo un ${minimo}%.`);
    }
    if (total !== 100) problemas.push(`Tienen que sumar 100 (ahora suman ${total}).`);
  }
  const usados = new Set(filas.map((f) => f.entrenador));

  const cambiar = (i, cambio) =>
    setFilas(filas.map((f, k) => (k === i ? { ...f, ...cambio } : f)));

  // Lo que entra o sale se compensa con el principal que más lleva, para que
  // el total no se descuadre a cada paso.
  const conPrincipal = (lista, delta) => {
    const copia = lista.map((f) => ({ ...f }));
    const mayor = copia.filter((f) => f.prioridad === PRINCIPAL)
      .sort((a, b) => Number(b.porcentaje) - Number(a.porcentaje))[0];
    if (mayor) mayor.porcentaje = Math.max(0, Number(mayor.porcentaje) + delta);
    return copia;
  };

  const anadir = () => {
    const e = entrenadores.find((x) => String(x.id) === nuevo);
    if (!e) return;
    const primero = filas.length === 0;
    setFilas([
      ...(primero ? [] : conPrincipal(filas, -minimo)),
      {
        entrenador: e.id, nombre: e.nombre,
        prioridad: primero ? PRINCIPAL : SECUNDARIO,
        porcentaje: primero ? 100 : minimo,
      },
    ]);
    setNuevo("");
  };

  const quitar = (i) =>
    setFilas(conPrincipal(filas.filter((_, k) => k !== i), Number(filas[i].porcentaje) || 0));

  const repartirComoSuGrupo = async () => {
    setError("");
    try {
      setFilas((await getEntrenadoresJugador(jugadorId, responsable)).propuesta);
    } catch (e) { setError(e.message); }
  };

  const guardar = async () => {
    setGuardando(true); setError(""); setAviso("");
    try {
      cargar(await guardarEntrenadoresJugador(jugadorId, {
        responsable: responsable ? Number(responsable) : null,
        entrenadores: filas.map((f) => ({
          entrenador: f.entrenador, prioridad: f.prioridad,
          porcentaje: Number(f.porcentaje) || 0,
        })),
      }));
      setAviso("Guardado.");
    } catch (e) { setError(e.message); }
    setGuardando(false);
  };

  return (
    <div className="page pesos">
      <div className="page-head"><h1>Entrenadores de {datos.jugador.nombre}</h1></div>
      <p className="help">
        El <b>responsable</b> es quien le gestiona. Con quién <b>entrena</b> va
        aparte y en porcentaje: el <b>principal</b> es el de su columna del
        organigrama y el resto de su grupo, <b>secundarios</b>, con un {minimo}%
        como mínimo. El motor reparte los entrenadores para acercarse a estos
        porcentajes a lo largo de la semana.
      </p>

      <div className="card">
        <label>Responsable · le gestiona{" "}
          <select value={responsable} onChange={(e) => setResponsable(e.target.value)}>
            <option value="">— sin responsable —</option>
            {entrenadores.map((e) => <option key={e.id} value={e.id}>{e.nombre}</option>)}
          </select>
        </label>
      </div>

      <div className="card">
        <table className="data">
          <thead>
            <tr><th>Entrena con</th><th>Papel</th><th>%</th><th /></tr>
          </thead>
          <tbody>
            {filas.length === 0 ? (
              <tr><td colSpan={4} className="msg">Sin porcentajes: entrena con su responsable.</td></tr>
            ) : filas.map((f, i) => (
              <tr key={f.entrenador}>
                <td>{f.nombre}</td>
                <td>
                  <select value={f.prioridad}
                    onChange={(e) => cambiar(i, { prioridad: Number(e.target.value) })}>
                    <option value={PRINCIPAL}>Principal</option>
                    <option value={SECUNDARIO}>Secundario</option>
                  </select>
                </td>
                <td>
                  <input type="number" min={0} max={100} className="pct" value={f.porcentaje}
                    onChange={(e) => cambiar(i, {
                      porcentaje: e.target.value === "" ? "" : Number(e.target.value),
                    })} />
                </td>
                <td style={{ textAlign: "right" }}>
                  <button type="button" className="btn danger sm" onClick={() => quitar(i)}>Quitar</button>
                </td>
              </tr>
            ))}
          </tbody>
          {filas.length > 0 && (
            <tfoot>
              <tr>
                <td colSpan={2}>Total</td>
                <td className={total === 100 ? "total-ok" : "total-mal"}>{total}%</td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>

        <div className="toolbar">
          <select value={nuevo} onChange={(e) => setNuevo(e.target.value)}>
            <option value="">Añadir entrenador…</option>
            {entrenadores.filter((e) => !usados.has(e.id)).map((e) => (
              <option key={e.id} value={e.id}>{e.nombre}</option>
            ))}
          </select>
          <button type="button" className="btn" disabled={!nuevo} onClick={anadir}>Añadir</button>
          <button type="button" className="btn" disabled={!responsable} onClick={repartirComoSuGrupo}
            title="El responsable de principal y el resto de su bloque de secundarios">
            Repartir como su grupo
          </button>
        </div>
      </div>

      {problemas.map((p) => <p key={p} className="err">{p}</p>)}
      {error && <p className="err">{error}</p>}
      {aviso && <p className="ok-msg">{aviso}</p>}
      <div className="toolbar">
        <button type="button" className="btn" disabled={guardando || problemas.length > 0} onClick={guardar}>
          {guardando ? "Guardando…" : "Guardar"}
        </button>
      </div>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<p className="msg">Cargando…</p>}>
      <Inner />
    </Suspense>
  );
}
