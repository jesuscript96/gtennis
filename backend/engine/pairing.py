"""Pure constraint-solving core for one (day, shift) — or for all the shifts of
a block at once (M1 and M2 of a morning).

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
  * Franjas: cada jugador solo entra en las suyas, y en tantas del bloque como
    marque `max_franjas` (una por defecto).

Soft (minimised):
  * Anti-repetition: penalise pairs that already played together this week.
  * Prefer filling fewer courts at the base venue before spilling to satellites.
  * Density: penalise every player above the court's normal density, so el
    motor sube a 3-4 solo cuando hace falta para colocar a alguien.
  * Court opening: cada pista abierta cuesta un poco, así se agrupa en pistas
    de 2 en vez de repartir individuales.
  * Equilibrio: con varias franjas a la vez, los jugadores se reparten entre
    ellas en proporción a los entrenadores de cada una.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from math import lcm

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
    # Hacia dónde prefiere emparejarse dentro del ±1: -1 = con la división de
    # número menor (la D1 es la más alta, así que eso es «hacia arriba»),
    # +1 = hacia abajo, 0 = le da igual.
    division_pref: int = 0
    # Horquilla propia de divisiones, cuando la suya es más estrecha que la del
    # club: cuántas admite por encima (número menor) y por debajo (número
    # mayor). None = la del club. Es regla dura, como la vecindad general.
    div_arriba: int | None = None
    div_abajo: int | None = None
    # "CHICO"/"CHICA"; None = sin declarar. Un chico no comparte pista con una
    # chica de división más baja.
    sexo: str | None = None
    # Años. Los menores solo entrenan con gente de edad parecida (`BANDAS_EDAD`).
    edad: int | None = None


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
    # Número de la pista dentro de su sede. Dos pistas son contiguas si son de
    # la misma sede y sus números se llevan uno: es lo que permite que un
    # entrenador abarque la suya y la de al lado.
    number: int | None = None


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
    # Coste de abrir una pista de resina: el club entrena en tierra y la resina
    # es el recurso de última hora. Por debajo de lo que vale colocar a
    # alguien, así que nadie se queda fuera por no pisar resina.
    w_resina: int = 300
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
    # Premio por emparejar a quien lo pide hacia su lado de división, y la
    # mitad en contra si cae hacia el otro. Pequeño frente a colocar a todos:
    # es un desempate, nunca una razón para dejar a nadie sin pista.
    w_div_pref: int = 30
    # --- Varias franjas a la vez -------------------------------------------
    # Ids de las franjas que se deciden juntas (M1 y M2 de una mañana). Vacío =
    # una sola franja, como siempre.
    franjas: list[int] = field(default_factory=list)
    # Jugador -> {franja: prioridad}: en qué franjas puede entrar y con qué
    # prioridad en cada una. Quien no aparece entra en todas con `priority`.
    franjas_de: dict[int, dict[int, int]] = field(default_factory=dict)
    # Jugador -> en cuántas franjas del bloque puede entrar como mucho. Por
    # defecto una: nadie repite en la misma mañana.
    max_franjas: dict[int, int] = field(default_factory=dict)
    # Franja -> entrenadores disponibles. Los jugadores se reparten entre
    # franjas en esa proporción; sin datos, a partes iguales.
    entrenadores_franja: dict[int, int] = field(default_factory=dict)
    # Coste por cada jugador de desequilibrio. Por debajo de lo que vale
    # colocar a alguien (nunca deja a nadie fuera por cuadrar) y de lo que
    # cuesta abrir una pista (no parte una pareja en dos individuales).
    w_balance: int = 200


@dataclass
class PairingResult:
    # court_id -> list of player ids (con una sola franja)
    courts: dict[int, list[int]]
    unassigned: list[int]
    status: str
    objective: float
    # franja -> court_id -> player ids (con varias franjas a la vez)
    franjas: dict[int, dict[int, list[int]]] = field(default_factory=dict)


def _normalise(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a <= b else (b, a)


# Diferencia de edad que admite cada franja de edad: (desde, hasta, años). Los
# críos entrenan con críos — de 10 a 14 años, como mucho dos años de
# diferencia; de 15 a 18, tres. Fuera de esas edades el club no pone tope.
BANDAS_EDAD = ((10, 12, 2), (13, 14, 2), (15, 18, 3))
# Por debajo de esto la edad no es de un alumno, es un error de tecleo: se
# trata como si no estuviera declarada en vez de dejar a nadie sin compañero.
EDAD_MINIMA_CREIBLE = 8


def _edad_creible(edad: int | None) -> int | None:
    """La edad, o None si no la hay o no se la cree nadie."""
    return edad if edad is not None and edad >= EDAD_MINIMA_CREIBLE else None


def _tope_edad(edad: int | None) -> int | None:
    """Años de diferencia que admite alguien de esta edad. None = sin tope."""
    if edad is None:
        return None
    for desde, hasta, tope in BANDAS_EDAD:
        if desde <= edad <= hasta:
            return tope
    return None


def _horquilla(p: Player, span: int) -> tuple[int, int]:
    """Divisiones que admite `p` por encima y por debajo de la suya."""
    ancho = max(1, span)
    return (ancho if p.div_arriba is None else p.div_arriba,
            ancho if p.div_abajo is None else p.div_abajo)


def _incompatible(
    p: Player, q: Player, vetoes: set[tuple[int, int]],
    apply_neighbor: bool = True, span: int = 1,
) -> bool:
    if _normalise(p.id, q.id) in vetoes:
        return True
    if apply_neighbor and p.division is not None and q.division is not None:
        # Cada uno tiene su horquilla y manda la más estrecha: si a uno de los
        # dos no le vale el otro, no comparten pista. La D1 es la más alta, así
        # que una diferencia positiva quiere decir que `q` es de nivel más bajo.
        salto = q.division - p.division
        p_arriba, p_abajo = _horquilla(p, span)
        q_arriba, q_abajo = _horquilla(q, span)
        if salto > 0 and (salto > p_abajo or salto > q_arriba):
            return True
        if salto < 0 and (-salto > p_arriba or -salto > q_abajo):
            return True
        # Un chico no entrena con una chica de nivel más bajo (división de
        # número mayor). Al revés sí: ella puede entrenar con chicos de su
        # nivel o de nivel más bajo.
        if p.sexo and q.sexo and p.sexo != q.sexo:
            chico, chica = (p, q) if p.sexo == "CHICO" else (q, p)
            if chica.division > chico.division:
                return True
    # Edad: manda el más estricto de los dos, y hacen falta las dos edades para
    # poder compararlas.
    edad_p, edad_q = _edad_creible(p.edad), _edad_creible(q.edad)
    if edad_p is not None and edad_q is not None:
        topes = [t for t in (_tope_edad(edad_p), _tope_edad(edad_q)) if t is not None]
        if topes and abs(edad_p - edad_q) > min(topes):
            return True
    return False


def solve_pairing(data: PairingInput) -> PairingResult:
    """Empareja una franja, o todas las de `data.franjas` a la vez.

    Decidirlas juntas es lo que permite repartir: resolviendo franja a franja,
    la primera se llevaba a todo el que cupiera y la segunda quedaba vacía.
    """
    model = cp_model.CpModel()
    players = data.players
    courts = data.courts
    pidx = {p.id: p for p in players}
    franjas = list(data.franjas) or [None]

    def prioridad(p, f):
        """Prioridad de `p` en la franja `f`, o None si ahí no puede entrar."""
        if f is None or p.id not in data.franjas_de:
            return p.priority
        return data.franjas_de[p.id].get(f)

    # x[p, f, c]: el jugador p juega en la pista c en la franja f. Solo existe
    # donde puede entrar: sus franjas, su superficie estricta (#1) y, si es de
    # una escuela del Resort (#6), sin satélites.
    x = {}
    del_jugador = defaultdict(list)
    en_pista = defaultdict(list)
    for p in players:
        for f in franjas:
            if prioridad(p, f) is None:
                continue
            for c in courts:
                if p.surface_pref and c.surface and c.surface != p.surface_pref:
                    continue
                if p.solo_central and c.is_satellite:
                    continue
                var = model.NewBoolVar(f"x_{p.id}_{f}_{c.id}")
                x[p.id, f, c.id] = var
                del_jugador[p.id].append((f, var))
                en_pista[f, c.id].append(var)

    def xv(pid, f, cid):
        return x.get((pid, f, cid), 0)

    used = {(f, c.id): model.NewBoolVar(f"used_{f}_{c.id}")
            for f in franjas for c in courts}

    # Una pista como mucho por franja, y `max_franjas` franjas del bloque (una
    # por defecto: nadie repite en la misma mañana). Quedarse sin pista está
    # permitido: es la señal de que no caben.
    for p in players:
        por_franja = defaultdict(list)
        for f, var in del_jugador[p.id]:
            por_franja[f].append(var)
        for vs in por_franja.values():
            model.Add(sum(vs) <= 1)
        if del_jugador[p.id]:
            model.Add(sum(v for _f, v in del_jugador[p.id])
                      <= data.max_franjas.get(p.id, 1))

    # Occupancy: a used court holds between `min_occupancy` and capacity
    # players; 0 otherwise. Además se mide el exceso sobre la densidad normal
    # para penalizarlo en el objetivo (pistas de 3-4 solo si hacen falta).
    min_occ = max(1, data.min_occupancy)
    excess = {}
    for f in franjas:
        for c in courts:
            occ = sum(en_pista[f, c.id])
            model.Add(occ <= c.capacity * used[f, c.id])
            model.Add(occ >= min_occ * used[f, c.id])
            e = model.NewIntVar(0, max(0, c.capacity - c.normal_density),
                                f"exc_{f}_{c.id}")
            model.Add(e >= occ - c.normal_density)
            excess[f, c.id] = e

    # Incompatible pairs may never share a court.
    for i in range(len(players)):
        for j in range(i + 1, len(players)):
            a, b = players[i], players[j]
            if not _incompatible(a, b, data.vetoes, data.apply_neighbor,
                                 data.neighbor_span):
                continue
            for f in franjas:
                for c in courts:
                    if (a.id, f, c.id) in x and (b.id, f, c.id) in x:
                        model.Add(x[a.id, f, c.id] + x[b.id, f, c.id] <= 1)

    # Parejas obligatorias (#5, HARD): en una franja en la que pueden entrar
    # los dos, comparten pista (o ninguno de los dos juega en ella).
    for pair in data.pairs_hard:
        a, b = tuple(pair)
        if a not in pidx or b not in pidx:
            continue
        for f in franjas:
            if prioridad(pidx[a], f) is None or prioridad(pidx[b], f) is None:
                continue
            for c in courts:
                va, vb = xv(a, f, c.id), xv(b, f, c.id)
                if isinstance(va, int) and isinstance(vb, int):
                    continue
                model.Add(va == vb)

    # --- Objective ---------------------------------------------------------
    terms = []
    court_by_id = {c.id: c for c in courts}
    # 1) Maximise assigned players, weighted by division/state priority.
    #    Bonus per player on central (non-satellite) courts ensures the
    #    GTennis academy courts fill first.
    for (pid, f, cid), var in x.items():
        bonus = data.w_central if not court_by_id[cid].is_satellite else 0
        terms.append((data.w_assign * prioridad(pidx[pid], f) + bonus) * var)
    for f in franjas:
        for c in courts:
            # 2) Prefer the base venue, and among satellites respect the
            #    overflow order (fill_rank).
            if c.is_satellite:
                terms.append(-data.w_satellite * max(1, c.fill_rank) * used[f, c.id])
            # Primero la tierra: la resina solo se abre cuando la tierra está
            # llena (o cuando la pide quien juega en ella).
            if c.surface == "RESINA":
                terms.append(-data.w_resina * used[f, c.id])
            # 3) Densidad y apertura de pista: se prefiere abrir otra pista antes
            #    que apretar, y agrupar de dos en dos antes que individuales.
            terms.append(-data.w_density * excess[f, c.id])
            terms.append(-data.w_court * used[f, c.id])
    # 4) Anti-repetition: penalise re-pairing recent partners.
    for pair, weight in data.recent_partners.items():
        a, b = tuple(pair)
        if a not in pidx or b not in pidx:
            continue
        comunes = [(f, c.id) for f in franjas for c in courts
                   if (a, f, c.id) in x and (b, f, c.id) in x]
        if not comunes:
            continue
        together = model.NewBoolVar(f"rep_{a}_{b}")
        for f, cid in comunes:
            # together >= x[a,f,c] + x[b,f,c] - 1
            model.Add(together >= x[a, f, cid] + x[b, f, cid] - 1)
        terms.append(-(data.w_repeat * weight) * together)
    # 5) Parejas preferentes (#5, SOFT): bonus si ambos coinciden en una pista.
    for pair in data.pairs_soft:
        a, b = tuple(pair)
        if a not in pidx or b not in pidx:
            continue
        for f in franjas:
            for c in courts:
                if (a, f, c.id) not in x or (b, f, c.id) not in x:
                    continue
                both = model.NewBoolVar(f"soft_{a}_{b}_{f}_{c.id}")
                model.Add(both <= x[a, f, c.id])
                model.Add(both <= x[b, f, c.id])
                terms.append(data.w_pair * both)

    # 6) Preferencia de división: quien pide jugar hacia arriba (o abajo)
    #    cobra un premio si comparte pista con alguien de ese lado, y paga la
    #    mitad si le toca alguien del lado contrario. Es un desempate: la
    #    vecindad de ±1 sigue siendo la regla dura.
    for p in players:
        if not p.division_pref or p.division is None:
            continue
        lado = [q for q in players
                if q.id != p.id and q.division == p.division + p.division_pref]
        contrario = [q for q in players
                     if q.id != p.id and q.division == p.division - p.division_pref]
        for f in franjas:
            for c in courts:
                if (p.id, f, c.id) not in x:
                    continue
                yo = x[p.id, f, c.id]
                de_lado = [x[q.id, f, c.id] for q in lado if (q.id, f, c.id) in x]
                if de_lado:
                    y = model.NewBoolVar(f"divpref_{p.id}_{f}_{c.id}")
                    model.Add(y <= yo)
                    model.Add(y <= sum(de_lado))
                    terms.append(data.w_div_pref * y)
                del_otro = [x[q.id, f, c.id] for q in contrario
                            if (q.id, f, c.id) in x]
                if del_otro:
                    z = model.NewBoolVar(f"divcontra_{p.id}_{f}_{c.id}")
                    for v in del_otro:
                        model.Add(z >= yo + v - 1)
                    terms.append(-(data.w_div_pref // 2) * z)

    # 7) Equilibrio entre franjas: los jugadores se reparten en proporción a
    #    los entrenadores de cada una (a partes iguales si tienen los mismos).
    #    Se mide la carga de cada franja —jugadores por entrenador, en enteros—
    #    y se penaliza la distancia entre la más cargada y la menos.
    if len(franjas) > 1 and data.w_balance > 0:
        entrenadores = {f: data.entrenadores_franja.get(f, 0) for f in franjas}
        if not any(entrenadores.values()):
            entrenadores = {f: 1 for f in franjas}
        cuentan = [f for f in franjas if entrenadores[f] > 0]
        if len(cuentan) > 1:
            comun = lcm(*(entrenadores[f] for f in cuentan))
            carga = {f: sum(v for c in courts for v in en_pista[f, c.id])
                        * (comun // entrenadores[f])
                     for f in cuentan}
            techo = max(1, len(players)) * comun
            mas = model.NewIntVar(0, techo, "carga_max")
            menos = model.NewIntVar(0, techo, "carga_min")
            for f in cuentan:
                model.Add(mas >= carga[f])
                model.Add(menos <= carga[f])
            # Un jugador de más en la franja con más entrenadores cuesta
            # exactamente `w_balance`.
            unidad = max(1, round(data.w_balance * max(entrenadores[f] for f in cuentan) / comun))
            terms.append(-unidad * (mas - menos))

    model.Maximize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = data.time_limit_s
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    por_franja: dict = {f: {} for f in franjas}
    assigned: set[int] = set()
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for f in franjas:
            for c in courts:
                members = [p.id for p in players
                           if (p.id, f, c.id) in x and solver.Value(x[p.id, f, c.id])]
                if members:
                    por_franja[f][c.id] = members
                    assigned.update(members)

    unassigned = [p.id for p in players if p.id not in assigned]
    return PairingResult(
        courts=por_franja[franjas[0]] if len(franjas) == 1 else {},
        unassigned=unassigned,
        status=solver.StatusName(status),
        objective=solver.ObjectiveValue() if status != cp_model.UNKNOWN else 0.0,
        franjas=por_franja if data.franjas else {},
    )
