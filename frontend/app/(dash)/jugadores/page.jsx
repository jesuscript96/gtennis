"use client";
import ResourceCrud from "../../../components/ResourceCrud";
import MisJugadores from "../../../components/MisJugadores";
import { RESOURCES } from "../../../lib/resources";
import { getUser } from "../../../lib/api";
import { roleRank } from "../../../lib/perms";

export default function Page() {
  // El entrenador no gestiona la ficha del alumno: para él es una lista de
  // nombres que se despliega para declarar turnos, no una tabla de campos
  // vacíos.
  if (roleRank(getUser()) === 1) return <MisJugadores />;
  return <ResourceCrud config={RESOURCES.jugadores} />;
}
