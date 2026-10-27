"use client";

import { crearEvaluacion, crearEvaluacionFisica } from "./api";
import { fmtLarga } from "./torneos";

export const ESTADO_INFORME = {
  EN_CURSO: ["A medias", "gris"],
  PENDIENTE: ["Pendiente de validar", "pend"],
  DEVUELTO: ["Devuelto", "no"],
  VALIDADO: ["Validado", "ok"],
};

/** Dónde está el jugador en su ciclo trimestral (75/90 días desde la validación). */
export function textoCiclo(c) {
  const f = c.proxima ? fmtLarga(c.proxima) : "";
  return {
    nuevo: [`Primer informe a partir del ${f}`, "gris"],
    primera: ["Toca el primer informe", "pend"],
    al_dia: [`Al día · siguiente hacia el ${f}`, "ok"],
    pronto: [`Toca pronto · antes del ${f}`, "pend"],
    vencido: ["Vencido: han pasado 90 días", "no"],
  }[c.estado] || [c.estado, "gris"];
}

/** Estado de una parte (tenis o física) dentro del informe en curso. */
export function textoParte(p, devuelta) {
  if (!p) return ["Sin empezar", "gris"];
  if (devuelta) return ["A corregir", "no"];
  return p.estado === "TERMINADA" ? ["Terminada", "ok"] : ["A medias", "pend"];
}

/** Abre la evaluación de esa parte: la que ya hay en el informe o una nueva. */
export async function abrirParte(router, jugadorId, parte, existenteId) {
  const ruta = parte === "tenis" ? "/evaluaciones/" : "/evaluaciones/fisica/";
  if (existenteId) { router.push(ruta + existenteId); return; }
  try {
    const crear = parte === "tenis" ? crearEvaluacion : crearEvaluacionFisica;
    const ev = await crear({ jugador: jugadorId });
    router.push(ruta + ev.id);
  } catch (e) {
    if (e.cuerpo?.existente) { router.push(ruta + e.cuerpo.existente); return; }
    throw e;
  }
}
