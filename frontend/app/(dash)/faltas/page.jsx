"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { getFaltas, getUser, getVienenAdemas, resource } from "../../../lib/api";
import CalendarioAusencias from "../../../components/CalendarioAusencias";
import { esDireccion, esHeadCoach } from "../../../lib/menu";

// Faltas (10/11/2026): un solo registro. Aquí se ve la semana entera y se
// apunta en el calendario del jugador, que es el mismo que sale en su ficha.
const DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

const iso = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const deIso = (s) => { const [a, m, d] = s.split("-").map(Number); return new Date(a, m - 1, d); };
const suma = (s, n) => { const d = deIso(s); d.setDate(d.getDate() + n); return iso(d); };
const corta = (s) => { const d = deIso(s); return `${d.getDate()} ${MESES[d.getMonth()]}`; };
function lunesDe(d) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dow = (x.getDay() + 6) % 7; // 0 = lunes
  // El domingo ya se mira la semana que empieza.
  x.setDate(x.getDate() - dow + (dow === 6 ? 7 : 0));
  return iso(x);
}
const hhmm = (t) => (t ? t.slice(0, 5) : "");

function cuando(f) {
  // Si acaba otro año, con el año («del 10 nov al 10 nov 2027»).
  const otroAnio = f.fecha_fin.slice(0, 4) !== f.fecha_inicio.slice(0, 4);
  const fechas = f.fecha_inicio === f.fecha_fin
    ? `${DIAS[(deIso(f.fecha_inicio).getDay() + 6) % 7] || "domingo"} ${corta(f.fecha_inicio)}`
    : `del ${corta(f.fecha_inicio)} al ${corta(f.fecha_fin)}${otroAnio ? ` ${f.fecha_fin.slice(0, 4)}` : ""}`;
  const parte = f.ambito !== "DIA" ? ` · ${f.ambito_display.toLowerCase()}` : "";
  const horas = f.hora_desde || f.hora_hasta ? ` · ${hhmm(f.hora_desde) || "…"}–${hhmm(f.hora_hasta) || "…"}` : "";
  return fechas + parte + horas;
}
const motivo = (f) => (f.estado === "EN_TORNEO" ? "Torneo" : f.subtipo_display || f.estado_display);

export default function FaltasPage() {
  const [lunes, setLunes] = useState(() => lunesDe(new Date()));
  const [faltas, setFaltas] = useState(null);
  const [vienen, setVienen] = useState([]);
  const [semanas, setSemanas] = useState([]);
  const [jugadores, setJugadores] = useState([]);
  const [busca, setBusca] = useState("");
  const [abierto, setAbierto] = useState(null);
  const [error, setError] = useState(null);
  // Los entrenadores que no están esa semana (11/11/2026): la vista conjunta
  // que antes daban «Vacaciones» y «Disp. entrenadores». Dirección ve a todos;
  // el head coach, a los de su grupo (lo filtra el servidor).
  const veEntrenadores = esDireccion(getUser()) || esHeadCoach(getUser());
  const [ausentes, setAusentes] = useState([]);
  const sabado = suma(lunes, 5);

  useEffect(() => {
    resource("jugadores").list().then(setJugadores).catch(() => {});
    resource("semanas").list().then(setSemanas).catch(() => {});
  }, []);

  const cargar = useCallback(async () => {
    setError(null);
    try {
      setFaltas(await getFaltas(lunes, sabado));
      if (veEntrenadores) {
        const [vac, ents] = await Promise.all([
          resource("vacaciones").list().catch(() => []),
          resource("entrenadores").list().catch(() => []),
        ]);
        const activos = new Set(ents.filter((e) => e.activo).map((e) => e.id));
        setAusentes(vac.filter((v) => activos.has(v.entrenador) && v.fecha_inicio <= sabado && v.fecha_fin >= lunes)
          .sort((a, b) => (a.fecha_inicio < b.fecha_inicio ? -1 : a.fecha_inicio > b.fecha_inicio ? 1
            : (a.entrenador_nombre || "").localeCompare(b.entrenador_nombre || ""))));
      }
      const s = semanas.find((x) => x.fecha_inicio === lunes);
      setVienen(s ? await getVienenAdemas(s.id) : []);
    } catch (e) { setError(String(e.message || e)); }
  }, [lunes, sabado, semanas, veEntrenadores]);
  useEffect(() => { cargar(); }, [cargar]);

  const texto = busca.trim().toLowerCase();
  const visibles = useMemo(() => (faltas || []).filter((f) => !texto || f.jugador_nombre.toLowerCase().includes(texto)), [faltas, texto]);
  const sugeridos = texto ? jugadores.filter((j) => j.nombre.toLowerCase().includes(texto)).slice(0, 8) : [];
  const jugadorAbierto = jugadores.find((j) => j.id === abierto) || (faltas || []).map((f) => ({ id: f.jugador, nombre: f.jugador_nombre })).find((j) => j.id === abierto);

  return (
    <div>
      <div className="page-head">
        <h1>Faltas</h1>
        <div className="semana-nav">
          <button className="btn ghost sm" onClick={() => setLunes(suma(lunes, -7))} aria-label="Semana anterior">‹</button>
          <span>Semana del {corta(lunes)} al {corta(sabado)}</span>
          <button className="btn ghost sm" onClick={() => setLunes(suma(lunes, 7))} aria-label="Semana siguiente">›</button>
          <button className="btn ghost sm" onClick={() => setLunes(lunesDe(new Date()))}>Hoy</button>
        </div>
      </div>
      <p className="help">
        Todas las faltas de la semana, apunte quien las apunte. Para apuntar una, busca al jugador y
        márcala en su calendario. Una falta apuntada después de las 19:00 del día anterior sale como «tras el corte»:
        no entró en el cuadrante y hay que mover al jugador a mano.
      </p>

      <div className="faltas-buscar">
        <input className="search" placeholder="Buscar jugador para ver o apuntar sus faltas…" value={busca}
               onChange={(e) => setBusca(e.target.value)} />
        {sugeridos.length > 0 && (
          <div className="faltas-sugeridos">
            {sugeridos.map((j) => (
              <button key={j.id} type="button" className="chip" onClick={() => { setAbierto(j.id); setBusca(""); }}>
                {j.nombre}
              </button>
            ))}
          </div>
        )}
      </div>

      {jugadorAbierto && (
        <div className="card faltas-calendario">
          <div className="faltas-calendario-head">
            <h2>{jugadorAbierto.nombre}</h2>
            <button className="btn ghost sm" onClick={() => setAbierto(null)}>Cerrar</button>
          </div>
          <CalendarioAusencias jugador={jugadorAbierto} onCambio={cargar} />
        </div>
      )}

      {error && <p className="err">{error}</p>}
      {!faltas ? <p className="msg">Cargando…</p> : (
        <div className="card">
          {visibles.length === 0 ? <p className="msg" style={{ padding: 16 }}>Nadie falta esta semana.</p> : (
            <table className="data">
              <thead>
                <tr><th>Jugador</th><th>Cuándo</th><th>Motivo</th><th>Apuntada por</th></tr>
              </thead>
              <tbody>
                {visibles.map((f) => (
                  <tr key={f.id}>
                    <td data-label="Jugador"><button type="button" className="link" onClick={() => setAbierto(f.jugador)}>{f.jugador_nombre}</button></td>
                    <td data-label="Cuándo">{cuando(f)}</td>
                    <td data-label="Motivo">{motivo(f)}{f.nota ? <span className="muted"> · {f.nota}</span> : null}
                      {f.tardia && <span className="badge" style={{ marginLeft: 8 }}>tras el corte</span>}</td>
                    <td className="muted" data-label="Apuntada por">{f.apuntada_por || "—"}{f.created_at ? ` · ${new Date(f.created_at).toLocaleString("es-ES", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {vienen.length > 0 && (
        <>
          <h2 className="titulo-lista" style={{ marginTop: 24 }}>Vienen además</h2>
          <div className="card">
            <table className="data">
              <tbody>
                {vienen.map((v) => (
                  <tr key={v.id}><td data-label="Jugador">{v.jugador_nombre || v.jugador}</td><td data-label="Cuándo">{DIAS[v.dia]} · {v.ambito}</td><td className="muted" data-label="Nota">{v.nota}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {veEntrenadores && ausentes.length > 0 && (
        <>
          <h2 className="titulo-lista" style={{ marginTop: 24 }}>Entrenadores que no están</h2>
          <div className="card">
            <table className="data">
              <thead><tr><th>Entrenador</th><th>Cuándo</th><th>Motivo</th></tr></thead>
              <tbody>
                {ausentes.map((v) => (
                  <tr key={v.id}>
                    <td data-label="Entrenador">{v.entrenador_nombre}</td>
                    <td data-label="Cuándo">{cuando({ ...v, ambito_display: v.ambito === "MANANA" ? "Mañana" : v.ambito === "TARDE" ? "Tarde" : v.ambito })}</td>
                    <td data-label="Motivo">{v.motivo || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
