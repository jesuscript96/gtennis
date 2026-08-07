// Disposición física real de la sede Central de GTennis (según plano del club):
//   columna izquierda:  Pista 3, 2, 1  (de arriba a abajo)
//   columna central:    Pista 8, 7, 6, 5, 4
// Superficie por pista: 1-6 = tierra (vista foto), 7-8 = azul (vista cancha).
export const CENTRAL_COLS = [
  [3, 2, 1], // tierra
  [6, 5, 4], // tierra
  [8, 7],    // azul
];

export function surfaceOf(numero) {
  return numero <= 6 ? "tierra" : "azul";
}

// tierra -> imagen (foto) · azul -> cancha dibujada
export function modeForSurface(surface) {
  return surface === "tierra" ? "foto" : "cancha";
}

export function isCentral(nombre) {
  const n = (nombre || "").toLowerCase();
  // El Resort es la antigua sede "Central": misma disposición física en 3
  // columnas (Pista 3-2-1 · 6-5-4 · 8-7).
  return n.includes("central") || n.includes("resort");
}
