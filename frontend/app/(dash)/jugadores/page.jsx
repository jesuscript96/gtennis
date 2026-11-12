"use client";
import ResourceCrud from "../../../components/ResourceCrud";
import MisJugadores from "../../../components/MisJugadores";
import { RESOURCES } from "../../../lib/resources";
import { getUser } from "../../../lib/api";
import { roleRank } from "../../../lib/perms";
import { esAdministracion } from "../../../lib/menu";

export default function Page() {
  // Ni el entrenador ni el coach gestionan la ficha del alumno: para ellos es
  // una lista de nombres que se despliega para declarar turnos y faltas, no
  // una tabla de campos vacíos. La ficha entera es cosa de dirección.
  // Dirección y Administración (altas y datos) llevan la tabla de fichas.
  const u = getUser();
  if (roleRank(u) < 3 && !esAdministracion(u)) return <MisJugadores />;
  return <ResourceCrud config={RESOURCES.jugadores} />;
}
