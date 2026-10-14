"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import TorneoForm from "../../../../components/TorneoForm";
import { crearTorneo, getTorneosResumen } from "../../../../lib/api";
import { fmtSemana, sumaDias } from "../../../../lib/torneos";

function NuevoTorneo() {
  const router = useRouter();
  const params = useSearchParams();
  // Desde el calendario se llega con la semana ya elegida (?desde=lunes).
  const desde = params.get("desde") || "";
  const [circuitos, setCircuitos] = useState([]);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { getTorneosResumen().then((r) => setCircuitos(r.circuitos.map((c) => c.nombre))).catch(() => {}); }, []);

  async function guardar(body) {
    setGuardando(true); setError("");
    try {
      const t = await crearTorneo(body);
      router.push(`/torneos/${t.id}`);
    } catch (e) { setError(e.message); setGuardando(false); }
  }

  return (
    <div>
      <div className="page-head"><h1>Nuevo torneo{desde ? <span className="h1-sub"> · semana {fmtSemana(desde)}</span> : null}</h1></div>
      <p className="help">
        Da de alta un torneo del calendario. Después, desde su ficha, podrás apuntar a los jugadores
        que van. Si lo propones para que lo valide dirección, déjalo en <b>Propuesto</b>.
      </p>
      <TorneoForm key={desde} circuitos={circuitos} onGuardar={guardar} onCancelar={() => router.push("/torneos")}
        inicial={desde ? { fecha_inicio: desde, fecha_fin: sumaDias(desde, 6) } : null}
        guardando={guardando} error={error} />
    </div>
  );
}

export default function NuevoTorneoPage() {
  return <Suspense fallback={<p className="msg">Cargando…</p>}><NuevoTorneo /></Suspense>;
}
