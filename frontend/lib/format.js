// Utilidades de presentación compartidas.

const hhmm = (t) => (typeof t === "string" ? t.slice(0, 5) : "");

// Horas efectivas de un turno para la fecha dada (verano = julio/agosto).
export function turnoHoras(t, fechaISO) {
  if (!t) return "";
  let mes;
  if (fechaISO) mes = Number(String(fechaISO).slice(5, 7));
  else mes = new Date().getMonth() + 1;
  const verano = (mes === 7 || mes === 8) && t.hora_inicio_verano && t.hora_fin_verano;
  const ini = verano ? t.hora_inicio_verano : t.hora_inicio;
  const fin = verano ? t.hora_fin_verano : t.hora_fin;
  return ini && fin ? `${hhmm(ini)}–${hhmm(fin)}` : "";
}

export const SUPERFICIE_LABEL = { TIERRA: "Tierra batida", RESINA: "Resina" };
export const SUPERFICIE_SHORT = { TIERRA: "Tierra", RESINA: "Resina" };
// Color de la superficie (arcilla vs azul resina). Independiente de estados.
export const SUPERFICIE_COLOR = { TIERRA: "#B65C3A", RESINA: "#3B6EA5" };

// Estados de la matriz del PRD, con los colores del Excel de la academia.
export const ESTADO_COLOR = {
  DISPONIBLE: "#1f9d57", AUSENCIA_JUGADOR: "#d33b3b", CALENTAMIENTO: "#c08a00",
  EN_TORNEO: "#d9772b", CLIMATOLOGIA: "#2f7fd1", AUSENCIA_COACH: "#7b54e0",
  EXTRA: "#0f8b8d",
};
export const ESTADO_LABEL = {
  DISPONIBLE: "Disponible", AUSENCIA_JUGADOR: "Ausencia", CALENTAMIENTO: "Calentamiento",
  EN_TORNEO: "En torneo", CLIMATOLOGIA: "Lluvia", AUSENCIA_COACH: "Sin coach",
  EXTRA: "Viene además",
};
