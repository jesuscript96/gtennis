"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import ResourceCrud from "../../../components/ResourceCrud";
import { RESOURCES } from "../../../lib/resources";
import { getUser, resource } from "../../../lib/api";
import { esEntrenador } from "../../../lib/menu";

// Entrenadores: dirección los ve todos y el head coach los de su grupo. El
// entrenador, su propia ficha (10/11/2026).
export default function Page() {
  const user = getUser();
  if (esEntrenador(user)) return <MiFicha id={user?.entrenador_id} />;
  return <ResourceCrud config={RESOURCES.entrenadores} />;
}

function MiFicha({ id }) {
  const [e, setE] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (id) resource("entrenadores").get(id).then(setE).catch((x) => setError(x.message));
  }, [id]);
  if (!id) return <p className="msg">Tu usuario no está enlazado a una ficha de entrenador.</p>;
  if (error) return <p className="err">{error}</p>;
  if (!e) return <p className="msg">Cargando…</p>;
  const filas = [
    ["Franjas", e.turnos_display || "Cualquiera"],
    ["Grupo de divisiones", e.division_desde || e.division_hasta ? `D${e.division_desde ?? "?"}–D${e.division_hasta ?? "?"}` : "Cualquiera"],
    ["Banquillo", e.reserva ? `Sí${e.orden_banquillo ? ` · sale el ${e.orden_banquillo}º` : ""}` : "No"],
    ["Solo a mano", e.solo_manual ? "Sí" : "No"],
  ];
  return (
    <div>
      <div className="page-head"><h1>{e.nombre}</h1></div>
      <div className="card" style={{ maxWidth: 560 }}>
        <table className="data"><tbody>
          {filas.map(([k, v]) => <tr key={k}><th>{k}</th><td>{v}</td></tr>)}
        </tbody></table>
      </div>
      <p className="help" style={{ marginTop: 16 }}>
        Lo cambian dirección y tu head coach. Los días que no puedes venir, apúntalos en tu calendario,
        en <Link href="/mi-agenda">Hoy</Link>.
      </p>
    </div>
  );
}
