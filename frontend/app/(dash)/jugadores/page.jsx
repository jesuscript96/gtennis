"use client";
import ResourceCrud from "../../../components/ResourceCrud";
import MisJugadores from "../../../components/MisJugadores";
import { RESOURCES } from "../../../lib/resources";
import { getUser } from "../../../lib/api";
import { roleRank } from "../../../lib/perms";

export default function Page() {
  // Ni el entrenador ni el coach gestionan la ficha del alumno: para ellos es
  // una lista de nombres que se despliega para declarar turnos y faltas, no
  // una tabla de campos vacíos. La ficha entera es cosa de dirección.
  if (roleRank(getUser()) < 3) return <MisJugadores />;
  return <ResourceCrud config={RESOURCES.jugadores} />;
}
