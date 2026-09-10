"""Pure constraint-solving core for one (day, shift).

No Django imports — fully unit-testable. Given the available players, the courts
(central first, then satellites) and the business rules, it produces court
pairings.

Hard constraints:
  * Neighbour rule: two players on the same court differ by <= `neighbor_span`
    divisions (1 por defecto).
  * Rencillas: vetoed pairs are never on the same court.
  * Capacity: <= court.capacity players per court.
  * Occupancy: a used court holds >= `min_occupancy` players (1 si se permiten
    clases particulares, 2 si no).

Soft (minimised):
  * Anti-repetition: penalise pairs that already played together this week.
  * Prefer filling fewer courts at the base venue before spilling to satellites.
  * Density: penalise every player above the court's normal density, so el
    motor sube a 3-4 solo cuando hace falta para colocar a alguien.
  * Court opening: cada pista abierta cuesta un poco, así se agrupa en pistas
    de 2 en vez de repartir individuales.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ortools.sat.python import cp_model


@dataclass(frozen=True)
class Player:
    id: int
    division: int | None = None          # None = not yet classified (wildcard)
    sponsor_coach_id: int | None = None
    priority: int = 1                    # higher = more likely to be assigned
    # Superficie preferida estricta (#1): "TIERRA"/"RESINA"; None = indiferente.
    surface_pref: str | None = None
    # #6: si True, solo puede jugar en el Resort (nunca en sedes satélite).
    solo_central: bool = False


@dataclass(frozen=True)
class Court:
    id: int
    venue_id: int
    capacity: int = 2
    # Densidad "de crucero": por encima de ella cada jugador extra penaliza.
    normal_density: int = 2
    is_satellite: bool = False
    # Orden de desbordamiento de la sede (0 = base). Los satélites se llenan
    # de menor a mayor: Sta. Bárbara antes que Bétera antes que Mas Camarena.
    fill_rank: int = 0
    # Superficie de la pista (#1): "TIERRA" / "RESINA".
    surface: str | None = None


@dataclass
class PairingInput:
    players: list[Player]
    courts: list[Court]
    vetoes: set[tuple[int, int]] = field(default_factory=set)
    recent_partners: dict[frozenset[int], int] = field(default_factory=dict)
    time_limit_s: float = 10.0
    # Tunable criteria (read from ConfiguracionMotor). Defaults = current values.
    w_assign: int = 1000
    w_satellite: int = 5
    w_central: int = 100
    w_repeat: int = 10
    apply_neighbor: bool = True
    # Diferencia máxima de división admitida dentro de una pista.
    neighbor_span: int = 1
    # Ocupación mínima de una pista usada: 1 permite la clase particular.
    min_occupancy: int = 2
    # Penalización por jugador por encima de `Court.normal_density`.
    w_density: int = 400
    # Coste de abrir una pista. Hace que el motor prefiera una pista de 2
    # antes que dos individuales, sin llegar a impedir la clase particular.
    w_court: int = 500
    # Parejas preferidas (#5): HARD = misma pista obligatoria; SOFT = bonus.
    pairs_hard: set[frozenset[int]] = field(default_factory=set)
    pairs_soft: set[frozenset[int]] = field(default_factory=set)
    w_pair: int = 300


@dataclass
class PairingResult:
    # court_id -> list of player ids
    courts: dict[int, list[int]]
    unassigned: list[int]
    status: str
    objective: float


def _normalise(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a <= b else (b, a)


def _incompatible(
    p: Player, q: Player, vetoes: set[tuple[int, int]],
    apply_neighbor: bool = True, span: int = 1,
) -> bool:
    if _normalise(p.id, q.id) in vetoes:
        return True
    if apply_neighbor and p.division is not None and q.division is not None:
        return abs(p.division - q.division) > max(1, span)
    return False


def solve_pairing(data: PairingInput) -> PairingResult:
    model = cp_model.CpModel()
    players = data.players
    courts = data.courts
    pidx = {p.id: p for p in players}

    x = {
        (p.id, c.id): model.NewBoolVar(f"x_{p.id}_{c.id}")
        for p in players
        for c in courts
    }
    used = {c.id: model.NewBoolVar(f"used_{c.id}") for c in courts}

    # Each player on at most one court (unassigned allowed -> overflow signal).
    for p in players:
        model.Add(sum(x[p.id, c.id] for c in courts) <= 1)

    # Occupancy: a used court holds between `min_occupancy` and capacity
    # players; 0 otherwise. Además se mide el exceso sobre la densidad normal
    # para penalizarlo en el objetivo (pistas de 3-4 solo si hacen falta).
    min_occ = max(1, data.min_occupancy)
    excess = {}
    for c in courts:
        occ = sum(x[p.id, c.id] for p in players)
        model.Add(occ <= c.capacity * used[c.id])
        model.Add(occ >= min_occ * used[c.id])
        e = model.NewIntVar(0, max(0, c.capacity - c.normal_density), f"exc_{c.id}")
        model.Add(e >= occ - c.normal_density)
        excess[c.id] = e

    # Preferencia de superficie estricta (#1): un jugador con superficie
    # preferida no puede jugar en una pista de otra superficie.
    for p in players:
        if p.surface_pref:
            for c in courts:
                if c.surface and c.surface != p.surface_pref:
                    model.Add(x[p.id, c.id] == 0)

    # #6: jugadores restringidos al Resort (p. ej. Junior Program) nunca en
    # una pista de sede satélite.
    for p in players:
        if p.solo_central:
            for c in courts:
                if c.is_satellite:
                    model.Add(x[p.id, c.id] == 0)

    # Incompatible pairs may never share a court.
    incompatible: list[tuple[int, int]] = []
    for i in range(len(players)):
        for j in range(i + 1, len(players)):
            if _incompatible(
                players[i], players[j], data.vetoes, data.apply_neighbor,
                data.neighbor_span,
            ):
                incompatible.append((players[i].id, players[j].id))
    for a, b in incompatible:
        for c in courts:
            model.Add(x[a, c.id] + x[b, c.id] <= 1)

    # Parejas obligatorias (#5, HARD): si ambos están disponibles este turno,
    # comparten pista (o ambos quedan sin asignar).
    for pair in data.pairs_hard:
        a, b = tuple(pair)
        if a in pidx and b in pidx:
            for c in courts:
                model.Add(x[a, c.id] == x[b, c.id])

    # --- Objective ---------------------------------------------------------
    terms = []
    # 1) Maximise assigned players, weighted by division/state priority.
    #    Bonus per player on central (non-satellite) courts ensures the
    #    GTennis academy courts fill first.
    for p in players:
        for c in courts:
            bonus = data.w_central if not c.is_satellite else 0
            terms.append((data.w_assign * p.priority + bonus) * x[p.id, c.id])
    # 2) Prefer the base venue, and among satellites respect the overflow order
    #    (fill_rank): a small penalty per used satellite, growing with its rank.
    for c in courts:
        if c.is_satellite:
            terms.append(-data.w_satellite * max(1, c.fill_rank) * used[c.id])
    # 3) Densidad: cada jugador por encima de la densidad normal de la pista
    #    penaliza, así el motor prefiere abrir otra pista antes que apretar.
    #    Y abrir pista también cuesta, para que no reparta individuales
    #    pudiendo agrupar de dos en dos.
    for c in courts:
        terms.append(-data.w_density * excess[c.id])
        terms.append(-data.w_court * used[c.id])
    # 4) Anti-repetition: penalise re-pairing recent partners.
    for pair, weight in data.recent_partners.items():
        a, b = tuple(pair)
        if a not in pidx or b not in pidx:
            continue
        together = model.NewBoolVar(f"rep_{a}_{b}")
        for c in courts:
            # together >= x[a,c] + x[b,c] - 1
            model.Add(together >= x[a, c.id] + x[b, c.id] - 1)
        terms.append(-(data.w_repeat * weight) * together)
    # 5) Parejas preferentes (#5, SOFT): bonus si ambos coinciden en una pista.
    for pair in data.pairs_soft:
        a, b = tuple(pair)
        if a not in pidx or b not in pidx:
            continue
        for c in courts:
            both = model.NewBoolVar(f"soft_{a}_{b}_{c.id}")
            model.Add(both <= x[a, c.id])
            model.Add(both <= x[b, c.id])
            terms.append(data.w_pair * both)

    model.Maximize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = data.time_limit_s
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    out: dict[int, list[int]] = {}
    assigned: set[int] = set()
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for c in courts:
            members = [p.id for p in players if solver.Value(x[p.id, c.id])]
            if members:
                out[c.id] = members
                assigned.update(members)

    unassigned = [p.id for p in players if p.id not in assigned]
    return PairingResult(
        courts=out,
        unassigned=unassigned,
        status=solver.StatusName(status),
        objective=solver.ObjectiveValue() if status != cp_model.UNKNOWN else 0.0,
    )
