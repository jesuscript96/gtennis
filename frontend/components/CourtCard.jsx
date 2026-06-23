"use client";

import Avatar from "./Avatar";

const ESTADO_COLOR = {
  DISPONIBLE: "#1f9d57", AUSENCIA_JUGADOR: "#d33b3b", CALENTAMIENTO: "#c08a00",
  EN_TORNEO: "#d9772b", CLIMATOLOGIA: "#2f7fd1", AUSENCIA_COACH: "#7b54e0",
};
const ESTADO_LABEL = {
  DISPONIBLE: "Disponible", AUSENCIA_JUGADOR: "Ausencia", CALENTAMIENTO: "Calentamiento",
  EN_TORNEO: "En torneo", CLIMATOLOGIA: "Lluvia", AUSENCIA_COACH: "Sin coach",
};

const first = (n) => (n || "").split(" ")[0];

// El coach (entrenador) se coloca en el centro, junto a la red.
const COACH = { l: 50, t: 50 };

// Pista vista desde arriba con la red VERTICAL en el centro (l=50%).
// Dos mitades: izquierda (l≈32) y derecha (l≈68); nunca encima de la red.
function positions(n) {
  if (n <= 1) return [{ l: 32, t: 50 }];
  if (n === 2) return [{ l: 32, t: 50 }, { l: 68, t: 50 }];
  if (n === 3) return [{ l: 32, t: 38 }, { l: 32, t: 62 }, { l: 68, t: 50 }];
  if (n === 4) return [{ l: 32, t: 38 }, { l: 68, t: 38 }, { l: 32, t: 62 }, { l: 68, t: 62 }];
  if (n === 5) return [{ l: 32, t: 34 }, { l: 32, t: 50 }, { l: 32, t: 66 }, { l: 68, t: 40 }, { l: 68, t: 60 }];
  if (n === 6) return [{ l: 32, t: 33 }, { l: 32, t: 50 }, { l: 32, t: 67 }, { l: 68, t: 33 }, { l: 68, t: 50 }, { l: 68, t: 67 }];
  // Reparto genérico en dos columnas para densidades altas.
  const out = [];
  const half = Math.ceil(n / 2);
  for (let i = 0; i < n; i++) {
    const left = i < half;
    const idx = left ? i : i - half;
    const count = left ? half : n - half;
    const t = count === 1 ? 50 : 32 + (idx * 36) / (count - 1);
    out.push({ l: left ? 32 : 68, t });
  }
  return out;
}

// Esquema cenital 4:3 con la red vertical en el centro.
function CourtSvg() {
  return (
    <svg viewBox="0 0 240 180" preserveAspectRatio="none" aria-hidden="true">
      <rect width="240" height="180" fill="#46815a" />
      <rect x="16" y="22" width="208" height="136" fill="#3f6f9e" />
      <g stroke="#eef2f0" strokeWidth="2" fill="none">
        <rect x="16" y="22" width="208" height="136" />
        <line x1="16" y1="40" x2="224" y2="40" />
        <line x1="16" y1="140" x2="224" y2="140" />
        <line x1="74" y1="40" x2="74" y2="140" />
        <line x1="166" y1="40" x2="166" y2="140" />
        <line x1="74" y1="90" x2="166" y2="90" />
      </g>
      {/* red vertical en el centro */}
      <rect x="117" y="22" width="6" height="136" fill="#1f3326" opacity="0.5" />
      <line x1="120" y1="18" x2="120" y2="162" stroke="#eef2f0" strokeWidth="2" />
    </svg>
  );
}

export default function CourtCard({ pista, players, coach, mode }) {
  const estado = players[0]?.estado || "DISPONIBLE";
  const color = ESTADO_COLOR[estado] || "#999";
  const empty = players.length === 0;
  const pos = positions(players.length);

  return (
    <div
      className={`court court-${mode} ${empty ? "is-empty" : ""}`}
      style={{ borderTop: `3px solid ${empty ? "var(--border-strong)" : color}` }}
    >
      <div className="court-top">
        <span className="court-name">{pista.label}</span>
        {!empty && (
          <span className="court-state" style={{ background: color }}>
            {ESTADO_LABEL[estado]}
          </span>
        )}
      </div>

      <div className="court-field">
        {mode === "cancha" && <CourtSvg />}
        {empty && <div className="court-free">Libre</div>}

        {players.map((p, i) => (
          <div key={p.id} className="court-av" style={{ left: `${pos[i].l}%`, top: `${pos[i].t}%` }}>
            <Avatar nombre={p.nombre} fotoUrl={p.foto} kind="player" />
            <span className="nm">{first(p.nombre)}</span>
          </div>
        ))}

        {coach && !empty && (
          <div className="court-av court-coach" style={{ left: `${COACH.l}%`, top: `${COACH.t}%` }}>
            <Avatar nombre={coach.nombre} fotoUrl={coach.foto} kind="coach" />
            <span className="nm">{first(coach.nombre)}</span>
          </div>
        )}
      </div>
    </div>
  );
}
