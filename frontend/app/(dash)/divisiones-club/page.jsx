"use client";
import ResourceCrud from "../../../components/ResourceCrud";
import { RESOURCES } from "../../../lib/resources";

// Club → Divisiones: los niveles y sus nombres. Quién está en cada división y
// en qué orden se lleva en Grupos (solo dirección, decisión 5).
export default function Page() {
  return <ResourceCrud config={RESOURCES.divisiones} />;
}
