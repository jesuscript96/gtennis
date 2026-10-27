"use client";

import Link from "next/link";

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
        Forma parte del <b>informe conjunto</b> (tenis + preparación física):{" "}
        <span className={`pill ${PILL[informe.estado]}`}>{TEXTO[informe.estado]}</span>
      </span>
      <Link href={`/informes/${informe.id}`} className="btn ghost sm">Ver informe</Link>
      {devuelta && (
        <p className="informe-nota">
          <b>Hay que corregir esta parte:</b> {informe.nota_devolucion}<br />
          Edítala y vuelve a terminarla: el informe pasa otra vez a validar.
        </p>
      )}
    </div>
  );
}
