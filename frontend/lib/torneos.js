// Presentación del módulo de torneos.
export const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
  "septiembre", "octubre", "noviembre", "diciembre"];
export const MES3 = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

// Fecha local AAAA-MM-DD (toISOString daría la de UTC y a partir de las 22:00 ya es «mañana»).
const isoLocal = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const hoyISO = () => isoLocal(new Date());

export function fmtCorta(iso) {
  if (!iso) return "";
  const [, m, d] = iso.split("-");
  return `${Number(d)} ${MES3[Number(m) - 1]}`;
}
export function fmtLarga(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${Number(d)} de ${MESES[Number(m) - 1]} de ${y}`;
}
export function fmtRango(ini, fin) {
  if (!ini) return "";
  if (!fin || fin === ini) return fmtCorta(ini);
  const [, m1, d1] = ini.split("-");
  const [, m2, d2] = fin.split("-");
  if (m1 === m2) return `${Number(d1)}–${Number(d2)} ${MES3[Number(m1) - 1]}`;
  return `${fmtCorta(ini)} – ${fmtCorta(fin)}`;
}
// Días que faltan para una fecha (negativo = pasada).
export function diasHasta(iso) {
  if (!iso) return null;
  const a = new Date(hoyISO() + "T00:00:00");
  const b = new Date(iso + "T00:00:00");
  return Math.round((b - a) / 86400000);
}
export const CERTEZA_LABEL = { CONFIRMADO: "Confirmado", PENDIENTE: "Pendiente", DEDUCIDO: "Deducido" };
export const CERTEZA_CLASS = { CONFIRMADO: "ok", PENDIENTE: "pend", DEDUCIDO: "ded" };
export const ESTADO_CLASS = { VALIDADO: "ok", PROPUESTO: "pend", CANCELADO: "no" };
export function sumaDias(iso, n) {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + n);
  return isoLocal(d);
}
// Lunes de la semana a la que pertenece una fecha.
export function lunesDe(iso) {
  const d = new Date(iso + "T00:00:00");
  return sumaDias(iso, -((d.getDay() + 6) % 7));
}
export function fmtSemana(lunes) {
  const fin = sumaDias(lunes, 6);
  const [, m1, d1] = lunes.split("-");
  const [, m2, d2] = fin.split("-");
  if (m1 === m2) return `del ${Number(d1)} al ${Number(d2)} de ${MESES[Number(m1) - 1]}`;
  return `del ${Number(d1)} de ${MESES[Number(m1) - 1]} al ${Number(d2)} de ${MESES[Number(m2) - 1]}`;
}
export const solapa = (a1, a2, b1, b2) => a1 <= b2 && b1 <= a2;
// Primer día que el torneo ocupa: la previa si la tiene, si no el cuadro final.
export const inicioEfectivo = (t) =>
  (t.qualy_inicio && t.qualy_inicio < t.fecha_inicio ? t.qualy_inicio : t.fecha_inicio);
// Lunes de todas las semanas que toca, de la previa al último día.
export function semanasDe(t) {
  const out = [];
  for (let l = lunesDe(inicioEfectivo(t)); l <= t.fecha_fin; l = sumaDias(l, 7)) out.push(l);
  return out;
}
