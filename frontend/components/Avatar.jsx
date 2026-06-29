"use client";

function initials(nombre) {
  return (nombre || "?")
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((s) => s[0] || "")
    .join("")
    .toUpperCase();
}

// kind: "player" (borde dorado) | "coach" (borde negro)
export default function Avatar({ nombre, fotoUrl, kind = "player" }) {
  if (fotoUrl) {
    return <img className={`avatar ${kind}`} src={fotoUrl} alt={nombre || ""} title={nombre} draggable={false} />;
  }
  return (
    <span className={`avatar ${kind}`} title={nombre}>
      {initials(nombre)}
    </span>
  );
}
