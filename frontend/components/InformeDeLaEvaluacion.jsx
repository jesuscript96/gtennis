"use client";

import Link from "next/link";
import { getUser } from "../lib/api";

const TEXTO = {
  EN_CURSO: "A medias: falta la otra parte",
  PENDIENTE: "Pendiente de validar",
  DEVUELTO: "Devuelto para corregir",
  VALIDADO: "Validado",
};
const PILL = { EN_CURSO: "gris", PENDIENTE: "pend", DEVUELTO: "no", VALIDADO: "ok" };

/** En una evaluación de Competición de tardes: el informe conjunto del que
 *  forma parte, y la nota de quien lo devolvió si toca corregir esta parte. */
export default function InformeDeLaEvaluacion({ informe, parte }) {
  if (!informe) return null;
  const devuelta = informe.estado === "DEVUELTO" && informe.devuelto_partes.includes(parte);
  return (
    <div className={`informe-de-eval${devuelta ? " devuelta" : ""}`}>
      <span>
        {informe.circuito === "alto_rendimiento"
          ? <>Forma parte de su <b>informe</b>, que pasa a validar al terminarla:{" "}</>
          : <>Forma parte del <b>informe conjunto</b> (tenis + preparación física):{" "}</>}
        <span className={`pill ${PILL[informe.estado]}`}>
          {informe.estado === "EN_CURSO" && informe.circuito === "alto_rendimiento" ? "A medias" : TEXTO[informe.estado]}
        </span>
      </span>
      {/* Informes solo lo abre quien evalúa en tardes, valida o envía: al
          entrenador de Alto rendimiento le basta con su parte. */}
      {getUser()?.ve_informes && <Link href={`/informes/${informe.id}`} className="btn ghost sm">Ver informe</Link>}
      {devuelta && (
        <p className="informe-nota">
          <b>Hay que corregir esta parte:</b> {informe.nota_devolucion}<br />
          Edítala y vuelve a terminarla: el informe pasa otra vez a validar.
        </p>
      )}
      {informe.estado === "VALIDADO" && (
        <p className="eval-nota">El informe ya está aprobado: para corregir algo, primero se reabre desde el informe.</p>
      )}
    </div>
  );
}
