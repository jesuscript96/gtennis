"""Pure constraint-solving core for one (day, shift).

No Django imports — fully unit-testable. Given the available players, the courts
(central first, then satellites) and the business rules, it produces court
pairings.

Hard constraints:
  * Neighbour rule: two players on the same court differ by <=1 division.
  * Rencillas: vetoed pairs are never on the same court.
  * Capacity: <= court.capacity players per court (2 normal, up to 4 Sta. Bárbara).
  * No half-courts: a used court holds >= 2 players.

Soft (minimised):
  * Anti-repetition: penalise pairs that already played together this week.
  * Prefer filling fewer courts at the base venue before spilling to satellites.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ortools.sat.python import cp_model


@dataclass(frozen=True)
class Player:
    id: int
    division: int | None = None          # None = not yet classified (wildcard)
    sponsor_coach_id: int | None = None


@dataclass(frozen=True)
class Court:
    id: int
    venue_id: int
    capacity: int = 2
    is_satellite: bool = False


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
    w_repeat: int = 10
    apply_neighbor: bool = True


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
    p: Player, q: Player, vetoes: set[tuple[int, int]], apply_neighbor: bool = True
) -> bool:
    if _normalise(p.id, q.id) in vetoes:
        return True
    if apply_neighbor and p.division is not None and q.division is not None:
        return abs(p.division - q.division) > 1
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

    # Occupancy: a used court holds between 2 and capacity players; 0 otherwise.
    for c in courts:
        occ = sum(x[p.id, c.id] for p in players)
        model.Add(occ <= c.capacity * used[c.id])
        model.Add(occ >= 2 * used[c.id])

    # Incompatible pairs may never share a court.
    incompatible: list[tuple[int, int]] = []
    for i in range(len(players)):
        for j in range(i + 1, len(players)):
            if _incompatible(
                players[i], players[j], data.vetoes, data.apply_neighbor
            ):
                incompatible.append((players[i].id, players[j].id))
    for a, b in incompatible:
        for c in courts:
            model.Add(x[a, c.id] + x[b, c.id] <= 1)

    # --- Objective ---------------------------------------------------------
    terms = []
    # 1) Maximise assigned players (dominant term).
    for p in players:
        terms.append(data.w_assign * sum(x[p.id, c.id] for c in courts))
    # 2) Prefer the base venue: small penalty per used satellite court.
    for c in courts:
        if c.is_satellite:
            terms.append(-data.w_satellite * used[c.id])
    # 3) Anti-repetition: penalise re-pairing recent partners.
    for pair, weight in data.recent_partners.items():
        a, b = tuple(pair)
        if a not in pidx or b not in pidx:
            continue
        together = model.NewBoolVar(f"rep_{a}_{b}")
        for c in courts:
            # together >= x[a,c] + x[b,c] - 1
            model.Add(together >= x[a, c.id] + x[b, c.id] - 1)
        terms.append(-(data.w_repeat * weight) * together)

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
