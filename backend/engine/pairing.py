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
  * Pistas sin entrenador (13/10/2026, si se dan `entrenadores_reparto`): como
    mucho dos jugadores, y al lado una pista con entrenador y dos jugadores
    como mucho que la vigila. Cada pista con entrenador vigila a una sola.
    En la tierra del Resort solo la 2 y la 5; la resina y cada satélite
    abiertos llevan al menos uno (22/10/2026). Si faltan, salen los del
    banquillo, pagando.

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

import os
import threading
import time
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
    # Alumno de relleno: se coloca donde quepa y nunca abre pista él solo.
    sin_prioridad: bool = False


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
    # Tope de seguridad: el solver nunca pasa de aquí.
    time_limit_s: float = 10.0
    # Se para antes si lleva este rato sin mejorar la mejor solución
    # (21/10/2026: con 30 s fijos un día tardaba 3 minutos y, con 2 s, salía
    # el mismo reparto). None = MOTOR_SIN_MEJORA_S del entorno, o 1 s; 0 = no
    # se para hasta el tope.
    sin_mejora_s: float | None = None
    # Si queda alguien fuera, esperar más antes de parar (PACIENCIA_SI_FALTA_
    # GENTE). No hace falta cuando los que sobran tienen otra franja después
    # (T1 antes que T2) ni al repetir forzando desde una solución ya buena.
    paciencia: bool = True
    # Tunable criteria (read from ConfiguracionMotor). Defaults = current values.
    w_assign: int = 1000
    w_satellite: int = 5
    w_central: int = 100
    # Los mejores grupos, en las primeras pistas. No es que la división N vaya
    # a la pista N —con solo tres jugadores de D1 eso dejaba la pista 1 vacía
    # media semana—: es que cuanto mejor es el grupo más cuesta alejarlo de la
    # pista 1, así que se ordenan de arriba abajo sobre las pistas que haya.
    w_pista_division: int = 50
    # Coste de abrir una pista por cada número que se aleja de la primera.
    # Cierra los huecos: antes de abrir la 5 se abre la 4.
    w_orden_pista: int = 0
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
    # Parejas declaradas a mano en la ficha. Mandan sobre las reglas de
    # emparejamiento —división, edad, chico/chica—, porque quien las declara
    # conoce el caso mejor que el motor. Lo único que no saltan es una
    # rencilla: si dos no deben coincidir, no coinciden.
    pairs_declaradas: set[frozenset[int]] = field(default_factory=set)
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
    # --- Reglas por bloque --------------------------------------------------
    # Tope de jugadores por pista de este bloque, por encima de la capacidad de
    # la sede: por la mañana nunca hay tres en una pista, por la tarde sí.
    capacidad_max: int | None = None
    # Coste por jugador de entrar en esta franja: T2 cuesta y T1 no, así que
    # nadie va a T2 mientras quepa en T1.
    coste_franja: dict[int, int] = field(default_factory=dict)
    # Franja -> pistas que se pueden abrir como mucho. Es el número de
    # entrenadores: por la tarde no se abre una pista que nadie puede dar.
    max_pistas: dict[int, int] = field(default_factory=dict)
    # Lo mismo pero como preferencia (mañana), con su coste por pista de más.
    pistas_objetivo: dict[int, int] = field(default_factory=dict)
    w_exceso_pistas: int = 0
    # Coste de una pista con un solo jugador: antes una pareja y una pista
    # vacía que dos individuales.
    w_individual: int = 0
    # Cuánto se puede estirar la vecindad y la edad antes que dejar a dos
    # alumnos solos en sendas pistas, y lo que cuesta hacerlo.
    span_extra: int = 0
    edad_extra: int = 0
    w_relajar: int = 0
    # (franja, pista) que ya tienen gente puesta a mano: el motor no mete a
    # nadie más ahí ni cuenta con ellas.
    ocupadas: set[tuple[int, int]] = field(default_factory=set)
    # --- Pistas sin entrenador (13/10/2026) ---------------------------------
    # Franja -> entrenadores que se pueden repartir. Con esto, se decide aquí
    # qué pistas llevan entrenador (como mucho tantas como entrenadores) y las
    # demás cumplen la regla del club: dos jugadores como mucho y, al lado,
    # una con entrenador y dos como mucho que la vigila. None = no se mira.
    entrenadores_reparto: dict[int, int] | None = None
    # Franja -> jugadores cuya pista lleva entrenador sí o sí: los que tienen
    # contrato con alguien que está libre a esa hora.
    con_entrenador: dict[int, set[int]] = field(default_factory=dict)
    # Franja -> jugadores cuya pista no vigila a la de al lado: su entrenador
    # viene solo por ellos (Dani con Taberner).
    no_vigilan: dict[int, set[int]] = field(default_factory=dict)
    # Franja -> {entrenador: jugadores}: quien solo entra en pista con estos
    # (14/10/2026: Dani Gimeno, con sus seis del grupo 1-2). Lleva una pista
    # como mucho y en ella solo van jugadores de su lista (uno solo también
    # vale: viene para eso); su pista no vigila a la de al lado. Si no hay
    # pista así, se queda en el banquillo y no cuenta para cubrir otras.
    dedicados: dict[int, dict[int, set[int]]] = field(default_factory=dict)
    # Premio por cada jugador de la lista que va en su pista: que vayan juntos.
    w_dedicado: int = 0
    # Números de las pistas de tierra que se prefieren sin entrenador,
    # vigiladas desde la de al lado (14/10/2026: la 2 y la 5, y con entrenador
    # la 1, 3, 4 y 6). Cada pista de tierra vigilada que no es de estas cuesta
    # `w_vigilada_fuera`.
    vigiladas_preferidas: frozenset[int] = frozenset()
    w_vigilada_fuera: int = 0
    # Regla dura (22/10/2026): en la tierra de la sede base solo se quedan
    # sin entrenador las `vigiladas_preferidas` (la 2 y la 5, contiguas a
    # otras); la 1, 3, 4 y 6, si se abren, lo llevan.
    vigiladas_estrictas: bool = False
    # En resina siempre hay algún entrenador: si una sede abre pistas de
    # resina, al menos una de ellas lo lleva (y vigila a la otra).
    resina_con_entrenador: bool = False
    # Lo mismo en los satélites (22/10/2026): si se abre Sta. Bárbara, al
    # menos una de sus pistas lleva entrenador.
    satelite_con_entrenador: bool = False
    # Franja -> entrenadores de banquillo que se pueden sacar si faltan (Dani,
    # Sergio, Iván, Jorge García). Cada pista con entrenador por encima de los
    # del reparto sale de aquí y cuesta `w_banquillo`: menos que dejar a
    # alguien fuera, más que cualquier preferencia de pista.
    banquillo: dict[int, int] = field(default_factory=dict)
    # Los de `dedicados` que además son de banquillo (Dani): si llevan su
    # pista, ya no están para cubrir otra.
    banquillo_dedicados: set[int] = field(default_factory=set)
    w_banquillo: int = 0
    # Colores (23/10/2026). Franja -> {color: entrenadores del reparto de ese
    # color} ("" = sin color; sin contar a los dedicados). Con esto cada pista
    # con entrenador lleva uno de un color concreto —o de la directiva, del
    # banquillo— y el solver coloca a los jugadores para que encajen: cada
    # jugador con color en una pista de entrenador de otro color cuesta
    # `w_fuera_color`. None = solo se cuenta cuántos hay.
    clases_entrenador: dict[int, dict[str, int]] | None = None
    color_jugador: dict[int, str] = field(default_factory=dict)
    w_fuera_color: int = 0
    # La directiva, con las divisiones más altas: cada división por debajo de
    # la 1 de cada jugador de su pista cuesta esto, y la resina o un satélite,
    # `w_directiva_fuera`.
    w_directiva_division: int = 0
    w_directiva_fuera: int = 0
    # Jugadores cuya pista se prefiere con entrenador (16/10/2026: D1 y D2):
    # cada pista suya que se queda sin él, vigilada, cuesta esto.
    prioridad_cubrir: set[int] = field(default_factory=set)
    w_cubrir_prioridad: int = 0
    # Último recurso (16/10/2026): si sin romper reglas alguien se queda
    # fuera, se repite permitiendo juntar a quien rompe reglas base (división,
    # chico/chica, edad; nunca una rencilla), cobrando cada pareja según lo que
    # rompe. Primero se coloca a todos los posibles; entre esos repartos, el que
    # menos rompe; y nunca se fuerza solo por ahorrarse abrir una pista.
    forzar: bool = False
    # Con quién se puede forzar: los que en el reparto normal se quedaron
    # fuera o solos en una pista. Sin esto el motor rompía reglas con
    # cualquiera y forzaba pistas de más. Vacío = con cualquiera.
    forzar_con: set[int] = field(default_factory=set)
    # El reparto normal, para empezar a buscar desde él: {(jugador, franja): pista}.
    pista_previa: dict[tuple[int, int], int] = field(default_factory=dict)


@dataclass
class PairingResult:
    # court_id -> list of player ids (con una sola franja)
    courts: dict[int, list[int]]
    unassigned: list[int]
    status: str
    objective: float
    # franja -> court_id -> player ids (con varias franjas a la vez)
    franjas: dict[int, dict[int, list[int]]] = field(default_factory=dict)
    # franja -> pistas que llevan entrenador (solo con `entrenadores_reparto`)
    cubiertas: dict[int, set[int]] = field(default_factory=dict)
    # franja -> {entrenador dedicado: su pista} (ver `dedicados`)
    dedicadas: dict[int, dict[int, int]] = field(default_factory=dict)
    # franja -> {pista vigilada: pista con entrenador que la vigila}
    vigilancia: dict[int, dict[int, int]] = field(default_factory=dict)


# Hilos mínimos del solver aunque la máquina tenga menos procesadores
# (23/10/2026): con uno solo, en prod, CP-SAT se quedaba a menudo con un
# reparto de 11-14 jugadores fuera; con cuatro repartiéndose el procesador,
# 0-1. Cada hilo prueba una estrategia distinta, y eso es lo que ayuda.
MIN_WORKERS = 4


def num_workers() -> int:
    """Hilos del solver: los procesadores que de verdad tiene la máquina (en
    Fly, los de la VM) y al menos MIN_WORKERS, o MOTOR_WORKERS si se fija a
    mano."""
    fijo = os.environ.get("MOTOR_WORKERS")
    if fijo:
        return max(1, int(fijo))
    try:
        cpus = len(os.sched_getaffinity(0))
    except AttributeError:  # macOS
        cpus = os.cpu_count() or 1
    return max(MIN_WORKERS, min(8, cpus))


# Si en la mejor solución queda alguien fuera y la cota del solver no descarta
# que quepa, se espera esto por cada segundo de `sin_mejora` antes de parar
# (23/10/2026: en la máquina de prod, parar al segundo dejaba a veces a 12-14
# jugadores fuera de una mañana).
PACIENCIA_SI_FALTA_GENTE = 4


class _ParaSinMejora(cp_model.CpSolverSolutionCallback):
    """Para la búsqueda cuando lleva `segundos` sin encontrar una solución
    mejor. El solver solo avisa al encontrar soluciones, así que un hilo
    aparte mira el reloj.

    Con `colocados` (variable con las plazas ocupadas) y `todos` (las que
    harían falta para colocar a todos), solo para tan pronto si ya están todos
    o si la cota dice que no cabe nadie más (`margen`, lo que vale colocar a
    uno); si no, aguanta PACIENCIA_SI_FALTA_GENTE veces más."""

    def __init__(self, solver: cp_model.CpSolver, segundos: float,
                 margen: float | None = None, colocados=None, todos: int = 0):
        super().__init__()
        self._solver = solver
        self._segundos = segundos
        self._margen = margen
        self._colocados = colocados
        self._todos = todos
        self._n = None
        self._ultima: float | None = None
        self._mejor: float | None = None
        self._cota: float | None = None
        self._fin = threading.Event()
        self._hilo = threading.Thread(target=self._vigilar, daemon=True)
        self._hilo.start()

    def on_solution_callback(self) -> None:
        # El solver solo avisa de soluciones que mejoran la anterior; aun así,
        # el reloj se reinicia solo si cambia el objetivo.
        valor = self.objective_value
        self._cota = self.best_objective_bound
        if self._colocados is not None:
            self._n = self.Value(self._colocados)
        if valor != self._mejor:
            self._mejor = valor
            self._ultima = time.monotonic()

    def _espera(self) -> float:
        if (self._margen is None or self._mejor is None or self._cota is None
                or self._cota - self._mejor < self._margen
                or (self._n is not None and self._n >= self._todos)):
            return self._segundos
        return self._segundos * PACIENCIA_SI_FALTA_GENTE

    def _vigilar(self) -> None:
        while not self._fin.wait(0.05):
            if (self._ultima is not None
                    and time.monotonic() - self._ultima >= self._espera()):
                self._solver.stop_search()
                return

    def terminar(self) -> None:
        self._fin.set()
        self._hilo.join()


def _normalise(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a <= b else (b, a)


# Diferencia de edad que admite cada franja de edad: (desde, hasta, años). Los
# críos entrenan con críos — de 10 a 14 años, como mucho dos años de
# diferencia; de 15 a 18, tres. Fuera de esas edades el club no pone tope.
# Nivel más bajo posible de división. La división 1 es la élite, así que
# cuanto MENOR es el número, mejor es el grupo.
NIVEL_MAX = 9

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
    """¿No pueden compartir pista de ninguna manera?"""
    return _motivo(p, q, vetoes, apply_neighbor, span) == DURO


# Resultados de `_motivo`: None = pueden ir juntos; RELAJABLE = solo si la
# alternativa es peor (dos individuales); DURO = jamás.
RELAJABLE = "RELAJABLE"
DURO = "DURO"


def _motivo(
    p: Player, q: Player, vetoes: set[tuple[int, int]],
    apply_neighbor: bool = True, span: int = 1,
    span_extra: int = 0, edad_extra: int = 0,
) -> str | None:
    """Por qué no pueden compartir pista, o None si sí pueden.

    `span_extra` y `edad_extra` son lo que el club acepta estirar cuando la
    alternativa es dejar a dos alumnos en sendas pistas individuales: una
    división más de distancia y un año más de diferencia. La regla de
    chico/chica, las rencillas y la horquilla que cada alumno tiene declarada
    en su ficha no se estiran nunca.
    """
    blando = False
    if _normalise(p.id, q.id) in vetoes:
        return DURO
    if apply_neighbor and p.division is not None and q.division is not None:
        # Cada uno tiene su horquilla y manda la más estrecha: si a uno de los
        # dos no le vale el otro, no comparten pista. La D1 es la más alta, así
        # que una diferencia positiva quiere decir que `q` es de nivel más bajo.
        salto = q.division - p.division
        p_arriba, p_abajo = _horquilla(p, span)
        q_arriba, q_abajo = _horquilla(q, span)
        # El estirón solo aplica a quien usa la horquilla del club: si el
        # alumno tiene la suya declarada, esa manda tal cual.
        e_p = span_extra if p.div_arriba is None and p.div_abajo is None else 0
        e_q = span_extra if q.div_arriba is None and q.div_abajo is None else 0
        if salto > 0:
            if salto > p_abajo + e_p or salto > q_arriba + e_q:
                return DURO
            if salto > p_abajo or salto > q_arriba:
                blando = True
        elif salto < 0:
            if -salto > p_arriba + e_p or -salto > q_abajo + e_q:
                return DURO
            if -salto > p_arriba or -salto > q_abajo:
                blando = True
        # Un chico no entrena con una chica de nivel más bajo (división de
        # número mayor). Al revés sí: ella puede entrenar con chicos de su
        # nivel o de nivel más bajo.
        if p.sexo and q.sexo and p.sexo != q.sexo:
            chico, chica = (p, q) if p.sexo == "CHICO" else (q, p)
            if chica.division > chico.division:
                return DURO
    # Edad: manda el más estricto de los dos, y hacen falta las dos edades para
    # poder compararlas.
    edad_p, edad_q = _edad_creible(p.edad), _edad_creible(q.edad)
    if edad_p is not None and edad_q is not None:
        topes = [t for t in (_tope_edad(edad_p), _tope_edad(edad_q)) if t is not None]
        if topes:
            tope = min(topes)
            diferencia = abs(edad_p - edad_q)
            if diferencia > tope + edad_extra:
                return DURO
            if diferencia > tope:
                blando = True
    return RELAJABLE if blando else None


def reglas_rotas(p: Player, q: Player, span: int = 1) -> list[str]:
    """Las reglas base que se rompen juntando a `p` y `q`, en palabras: para
    avisar de una pista forzada (14/10/2026). Las rencillas no van aquí: esas
    no se rompen nunca."""
    rotas = []
    if p.division is not None and q.division is not None:
        salto = q.division - p.division
        p_arriba, p_abajo = _horquilla(p, span)
        q_arriba, q_abajo = _horquilla(q, span)
        if ((salto > 0 and (salto > p_abajo or salto > q_arriba))
                or (salto < 0 and (-salto > p_arriba or -salto > q_abajo))):
            alto, bajo = sorted((p.division, q.division))
            rotas.append(f"división D{alto}–D{bajo}")
        if p.sexo and q.sexo and p.sexo != q.sexo:
            chico, chica = (p, q) if p.sexo == "CHICO" else (q, p)
            if chica.division > chico.division:
                rotas.append("chico/chica")
    edad_p, edad_q = _edad_creible(p.edad), _edad_creible(q.edad)
    if edad_p is not None and edad_q is not None:
        topes = [t for t in (_tope_edad(edad_p), _tope_edad(edad_q)) if t is not None]
        if topes and abs(edad_p - edad_q) > min(topes):
            menor, mayor = sorted((edad_p, edad_q))
            rotas.append(f"edad ({menor} y {mayor} años)")
    return rotas


def gravedad(p: Player, q: Player, span: int = 1, span_extra: int = 0,
             edad_extra: int = 0) -> int:
    """Cuánto rompe juntar a `p` y `q`: divisiones de más, años de más y 3 por
    chico/chica. 0 si no rompen nada."""
    total = 0
    if p.division is not None and q.division is not None:
        salto = q.division - p.division
        p_arriba, p_abajo = _horquilla(p, span)
        q_arriba, q_abajo = _horquilla(q, span)
        if salto > 0:
            total += max(0, salto - min(p_abajo, q_arriba) - span_extra)
        elif salto < 0:
            total += max(0, -salto - min(p_arriba, q_abajo) - span_extra)
        if p.sexo and q.sexo and p.sexo != q.sexo:
            chico, chica = (p, q) if p.sexo == "CHICO" else (q, p)
            if chica.division > chico.division:
                total += 3
    edad_p, edad_q = _edad_creible(p.edad), _edad_creible(q.edad)
    if edad_p is not None and edad_q is not None:
        topes = [t for t in (_tope_edad(edad_p), _tope_edad(edad_q)) if t is not None]
        if topes:
            total += max(0, abs(edad_p - edad_q) - min(topes) - edad_extra)
    return total


# Lo que cuesta cada unidad de `gravedad` en una pareja forzada.
W_GRAVEDAD = 500


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
                if (f, c.id) in data.ocupadas:
                    continue
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
    for f, cid in data.ocupadas:
        if (f, cid) in used:
            model.Add(used[f, cid] == 0)

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
    solos = {}

    def tope(c):
        return (c.capacity if data.capacidad_max is None
                else min(c.capacity, data.capacidad_max))

    # Quien solo entra en pista con unos jugadores (Dani Gimeno): `ded[f, e,
    # pista]` vale 1 en la pista que lleva `e`. Solo jugadores de su lista, una
    # pista como mucho, y nadie más la lleva.
    ded = {}
    for f in franjas:
        for e, lista in data.dedicados.get(f, {}).items():
            suyas = []
            for c in courts:
                suyos = [x[pid, f, c.id] for pid in lista if (pid, f, c.id) in x]
                if not suyos:
                    continue
                d = model.NewBoolVar(f"ded_{f}_{e}_{c.id}")
                model.Add(d <= sum(suyos))
                model.Add(d <= used[f, c.id])
                for p in players:
                    if p.id not in lista and (p.id, f, c.id) in x:
                        model.Add(x[p.id, f, c.id] <= 1 - d)
                ded[f, e, c.id] = d
                suyas.append(d)
            if suyas:
                model.Add(sum(suyas) <= 1)
        for c in courts:
            de_pista = [v for (ff, _e, cid), v in ded.items()
                        if ff == f and cid == c.id]
            if len(de_pista) > 1:
                model.Add(sum(de_pista) <= 1)

    def dedicada(f, cid):
        return [v for (ff, _e, c), v in ded.items() if ff == f and c == cid]

    for f in franjas:
        # Quien tiene su entrenador atado (Taberner con Dani) puede ir solo con
        # él aunque el bloque no abra individuales: viene para eso.
        atados_f = [p.id for p in players if p.id in data.con_entrenador.get(f, ())]
        for c in courts:
            occ = sum(en_pista[f, c.id])
            model.Add(occ <= tope(c) * used[f, c.id])
            solo_ok = [x[pid, f, c.id] for pid in atados_f if (pid, f, c.id) in x]
            solo_ok += dedicada(f, c.id)
            model.Add(occ >= min_occ * used[f, c.id]
                      - (min_occ - 1) * sum(solo_ok))
            e = model.NewIntVar(0, max(0, tope(c) - c.normal_density),
                                f"exc_{f}_{c.id}")
            model.Add(e >= occ - c.normal_density)
            excess[f, c.id] = e
            # Pista con un solo jugador: `solo` vale 1 cuando está abierta y
            # tiene uno. Se penaliza en el objetivo.
            solo = model.NewBoolVar(f"solo_{f}_{c.id}")
            model.Add(solo >= 2 * used[f, c.id] - occ)
            model.Add(solo <= used[f, c.id])
            solos[f, c.id] = solo

    # Pistas sin entrenador: dos jugadores como mucho y una vecina con
    # entrenador (y dos como mucho) que la vigile. Vecinas son las de la misma
    # sede con número contiguo; cada pista con entrenador vigila a una sola.
    cub = {}
    vig = {}
    fuera_de_patron = []
    del_banquillo = []
    clase_de = {}
    directiva = {}
    sin_entrenador_alto = []
    if data.entrenadores_reparto is not None:
        por_sede = defaultdict(dict)
        for c in courts:
            if c.number is not None:
                por_sede[c.venue_id][c.number] = c
        for f in franjas:
            for c in courts:
                cub[f, c.id] = model.NewBoolVar(f"cub_{f}_{c.id}")
                model.Add(cub[f, c.id] <= used[f, c.id])
            # El dedicado cuenta en el reparto solo si lleva su pista: si no,
            # está en el banquillo y no cubre ninguna otra.
            n_ded = len(data.dedicados.get(f, {}))
            ded_f = [v for (ff, _e, _c), v in ded.items() if ff == f]
            tope_cub = (max(0, data.entrenadores_reparto.get(f, 0) - n_ded)
                        + sum(ded_f))
            # Si faltan, salen los del banquillo, pagando cada uno.
            n_banq = data.banquillo.get(f, 0)
            ded_banq = [v for (ff, e, _c), v in ded.items()
                        if ff == f and e in data.banquillo_dedicados]
            clases = (data.clases_entrenador.get(f, {})
                      if data.clases_entrenador is not None else None)
            if clases is not None:
                # Cada pista con entrenador, de una clase: un color, o la
                # directiva, o el dedicado que la lleva.
                for c in courts:
                    partes = []
                    for k, n in clases.items():
                        if n > 0:
                            y = model.NewBoolVar(f"clase_{f}_{c.id}_{k}")
                            clase_de[f, c.id, k] = y
                            partes.append(y)
                    if n_banq:
                        d = model.NewBoolVar(f"dir_{f}_{c.id}")
                        directiva[f, c.id] = d
                        partes.append(d)
                    ded_c = [v for (ff, _e, cid), v in ded.items()
                             if ff == f and cid == c.id]
                    model.Add(sum(partes) + sum(ded_c) == cub[f, c.id])
                for k, n in clases.items():
                    if n > 0:
                        model.Add(sum(clase_de[f, c.id, k] for c in courts) <= n)
                if n_banq:
                    model.Add(sum(directiva[f, c.id] for c in courts)
                              <= n_banq - sum(ded_banq))
            else:
                if n_banq:
                    de_banq = model.NewIntVar(0, n_banq, f"banq_{f}")
                    model.Add(de_banq <= n_banq - sum(ded_banq))
                    tope_cub = tope_cub + de_banq
                    del_banquillo.append(de_banq)
                model.Add(sum(cub[f, c.id] for c in courts) <= tope_cub)
            for (ff, _e, cid), v in ded.items():
                if ff == f:
                    model.Add(cub[f, cid] >= v)
            vigila, vigilada = defaultdict(list), defaultdict(list)
            for c in courts:
                if c.number is None:
                    continue
                for n in (c.number - 1, c.number + 1):
                    v = por_sede[c.venue_id].get(n)
                    if v is None:
                        continue
                    # `v` (con entrenador) vigila a `c` (abierta y sin él).
                    w = model.NewBoolVar(f"vig_{f}_{v.id}_{c.id}")
                    model.Add(w <= cub[f, v.id])
                    model.Add(w <= used[f, c.id] - cub[f, c.id])
                    for pid in data.no_vigilan.get(f, ()):
                        if (pid, f, v.id) in x:
                            model.Add(w <= 1 - x[pid, f, v.id])
                    for dv in dedicada(f, v.id):
                        model.Add(w <= 1 - dv)
                    vigila[v.id].append(w)
                    vigilada[c.id].append(w)
                    vig[f, v.id, c.id] = w
            for c in courts:
                occ = sum(en_pista[f, c.id])
                extra = max(0, tope(c) - 2)
                if extra:
                    model.Add(occ <= 2 + extra * cub[f, c.id])
                model.Add(used[f, c.id] - cub[f, c.id] <= sum(vigilada[c.id]))
                if len(vigilada[c.id]) > 1:
                    model.Add(sum(vigilada[c.id]) <= 1)
                # La 2 y la 5 son las que se dejan sin entrenador: vigilar otra
                # de tierra cuesta.
                if (c.surface != "RESINA" and c.number is not None
                        and c.number not in data.vigiladas_preferidas):
                    if data.vigiladas_estrictas and not c.is_satellite:
                        model.Add(cub[f, c.id] >= used[f, c.id])
                    elif data.w_vigilada_fuera:
                        fuera_de_patron.append(used[f, c.id] - cub[f, c.id])
                if vigila[c.id]:
                    model.Add(sum(vigila[c.id]) <= 1)
                    if extra:
                        model.Add(occ <= 2 + extra * (1 - sum(vigila[c.id])))
            for pid in data.con_entrenador.get(f, ()):
                for c in courts:
                    if (pid, f, c.id) in x:
                        model.Add(cub[f, c.id] >= x[pid, f, c.id])
            if data.prioridad_cubrir and data.w_cubrir_prioridad:
                for c in courts:
                    altos = [x[pid, f, c.id] for pid in data.prioridad_cubrir
                             if (pid, f, c.id) in x]
                    if not altos:
                        continue
                    z = model.NewBoolVar(f"alto_sin_{f}_{c.id}")
                    for v in altos:
                        model.Add(z >= v - cub[f, c.id])
                    sin_entrenador_alto.append(z)
            if data.resina_con_entrenador:
                resinas = defaultdict(list)
                for c in courts:
                    if c.surface == "RESINA":
                        resinas[c.venue_id].append(c)
                for de_sede in resinas.values():
                    for c in de_sede:
                        model.Add(used[f, c.id]
                                  <= sum(cub[f, r.id] for r in de_sede))
            if data.satelite_con_entrenador:
                sedes_sat = defaultdict(list)
                for c in courts:
                    if c.is_satellite:
                        sedes_sat[c.venue_id].append(c)
                for de_sede in sedes_sat.values():
                    for c in de_sede:
                        model.Add(used[f, c.id]
                                  <= sum(cub[f, r.id] for r in de_sede))

    # Tantas pistas como entrenadores: por la tarde es un tope, por la mañana
    # una preferencia con su coste.
    exceso_pistas = {}
    for f in franjas:
        abiertas = sum(used[f, c.id] for c in courts)
        if f in data.max_pistas:
            model.Add(abiertas <= max(1, data.max_pistas[f]))
        objetivo = data.pistas_objetivo.get(f)
        if objetivo is not None and data.w_exceso_pistas:
            e = model.NewIntVar(0, len(courts), f"expis_{f}")
            model.Add(e >= abiertas - max(1, objetivo))
            exceso_pistas[f] = e

    # Los alumnos «sin prioridad» encajan al final: solo en pistas que ya abre
    # alguien con prioridad, nunca ellos solos. Sin esto, despriorizarles baja
    # su peso pero el motor les sigue abriendo pista cuando sobran.
    sin_prio = {p.id for p in players if p.sin_prioridad}
    if sin_prio:
        for f in franjas:
            for c in courts:
                bajos = [x[pid, f, c.id] for pid in sin_prio
                         if (pid, f, c.id) in x]
                if not bajos:
                    continue
                altos = [x[p.id, f, c.id] for p in players
                         if p.id not in sin_prio and (p.id, f, c.id) in x]
                if altos:
                    model.Add(sum(bajos) <= c.capacity * sum(altos))
                else:
                    model.Add(sum(bajos) == 0)

    # Suelo de colocar a alguien (16/10/2026): vale más que todo lo que cuesta
    # abrirle pista —abrirla, que sea de resina, que esté lejos, que haya más
    # pistas que entrenadores, que vaya solo…—. Así ningún peso de pista deja a
    # nadie fuera; entre repartos que colocan a los mismos, deciden los pesos.
    # La densidad (tres en pista por la mañana) queda fuera a propósito.
    max_num = max((c.number or 0 for c in courts), default=0)
    max_rango = max((c.fill_rank for c in courts if c.is_satellite), default=0)
    piso = (data.w_court + data.w_resina + data.w_orden_pista * max_num
            + data.w_exceso_pistas + data.w_individual
            + data.w_satellite * max(1, max_rango)
            + data.w_pista_division * max_num
            + max(data.coste_franja.values(), default=0) + data.w_balance
            + data.w_vigilada_fuera + data.w_cubrir_prioridad + data.w_relajar
            + data.w_banquillo + data.w_fuera_color
            + data.w_directiva_division * NIVEL_MAX + data.w_directiva_fuera
            + data.w_repeat * max(data.recent_partners.values(), default=0)
            + data.w_div_pref + 1)
    # Una pareja forzada cuesta más que todo lo que se ahorra juntando a dos
    # (una pista y dos individuales), y más cuanto más rompe.
    base_forzada = piso + data.w_individual + 1
    forzadas = []

    # Parejas incompatibles. Las duras no comparten pista jamás; las
    # relajables (una división o un año de más) se permiten pagando
    # `w_relajar`, que sale a cuenta frente a dos pistas individuales.
    relajadas = []
    for i in range(len(players)):
        for j in range(i + 1, len(players)):
            a, b = players[i], players[j]
            motivo = _motivo(a, b, data.vetoes, data.apply_neighbor,
                             data.neighbor_span, data.span_extra,
                             data.edad_extra)
            if motivo is None:
                continue
            # Pareja declarada a mano: manda sobre la regla que la separaba.
            if (frozenset((a.id, b.id)) in data.pairs_declaradas
                    and _normalise(a.id, b.id) not in data.vetoes):
                continue
            juntos = [(f, c) for f in franjas for c in courts
                      if (a.id, f, c.id) in x and (b.id, f, c.id) in x]
            if not juntos:
                continue
            if (motivo == DURO and data.forzar
                    and _normalise(a.id, b.id) not in data.vetoes
                    and (not data.forzar_con or a.id in data.forzar_con
                         or b.id in data.forzar_con)):
                forzada = model.NewBoolVar(f"forz_{a.id}_{b.id}")
                for f, c in juntos:
                    model.Add(x[a.id, f, c.id] + x[b.id, f, c.id] <= 1 + forzada)
                g = gravedad(a, b, data.neighbor_span, data.span_extra, data.edad_extra)
                forzadas.append((forzada, base_forzada + W_GRAVEDAD * max(1, g)))
                continue
            if motivo == DURO or not data.w_relajar:
                for f, c in juntos:
                    model.Add(x[a.id, f, c.id] + x[b.id, f, c.id] <= 1)
                continue
            estirado = model.NewBoolVar(f"rel_{a.id}_{b.id}")
            for f, c in juntos:
                model.Add(x[a.id, f, c.id] + x[b.id, f, c.id] <= 1 + estirado)
            relajadas.append(estirado)

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

    # Se empieza a buscar desde el reparto normal.
    if data.pista_previa:
        for (pid, f, cid), var in x.items():
            model.AddHint(var, 1 if data.pista_previa.get((pid, f)) == cid else 0)

    # --- Objective ---------------------------------------------------------
    terms = []
    # La pista individual se penaliza, pero nunca tanto como para que salga a
    # cuenta dejar al alumno en el banquillo: quien ha venido, entrena.
    w_individual = min(
        data.w_individual,
        max(0, data.w_assign + data.w_central - data.w_court - 1),
    )
    court_by_id = {c.id: c for c in courts}
    # Forzando, colocar a uno vale más que las parejas forzadas que haga falta
    # para meterle (como mucho una por cada compañero de pista).
    extra = 0
    if forzadas:
        cap = max((c.capacity for c in courts), default=2)
        extra = cap * max(coste for _v, coste in forzadas)
    for v, coste in forzadas:
        terms.append(-coste * v)
    # 1) Maximise assigned players, weighted by division/state priority.
    #    Bonus per player on central (non-satellite) courts ensures the
    #    GTennis academy courts fill first.
    for (pid, f, cid), var in x.items():
        court = court_by_id[cid]
        bonus = data.w_central if not court.is_satellite else 0
        # La división marca la pista: los de arriba, en las primeras. Cuesta
        # por cada pista de distancia, así que solo decide cuando el resto
        # empata.
        division = pidx[pid].division
        if division and court.number and not court.is_satellite:
            # (número de pista − 1) × lo bueno que es el grupo, normalizado
            # para que siga siendo un desempate y nunca una razón para dejar a
            # nadie fuera.
            bonus -= (data.w_pista_division * (court.number - 1)
                      * (NIVEL_MAX + 1 - division)) // NIVEL_MAX
        # T1 antes que T2: estar en la franja cara solo compensa cuando en la
        # barata ya no se cabe.
        bonus -= data.coste_franja.get(f, 0)
        terms.append((data.w_assign * prioridad(pidx[pid], f) + bonus + piso + extra) * var)
    for f in franjas:
        for c in courts:
            # 2) Prefer the base venue, and among satellites respect the
            #    overflow order (fill_rank).
            if c.is_satellite:
                terms.append(-data.w_satellite * max(1, c.fill_rank) * used[f, c.id])
            elif c.number and data.w_orden_pista:
                terms.append(
                    -data.w_orden_pista * (c.number - 1) * used[f, c.id])
            # Primero la tierra: la resina solo se abre cuando la tierra está
            # llena (o cuando la pide quien juega en ella).
            if c.surface == "RESINA":
                terms.append(-data.w_resina * used[f, c.id])
            # 3) Densidad y apertura de pista: se prefiere abrir otra pista antes
            #    que apretar, y agrupar de dos en dos antes que individuales.
            terms.append(-data.w_density * excess[f, c.id])
            terms.append(-data.w_court * used[f, c.id])
            terms.append(-w_individual * solos[f, c.id])
    for f, e in exceso_pistas.items():
        terms.append(-data.w_exceso_pistas * e)
    for estirado in relajadas:
        terms.append(-data.w_relajar * estirado)
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

    # 5a) Pistas de tierra vigiladas que no son la 2 ni la 5.
    for e in fuera_de_patron:
        terms.append(-data.w_vigilada_fuera * e)
    # 5a') Pistas de D1-D2 sin entrenador: las últimas en quedarse sin él.
    for z in sin_entrenador_alto:
        terms.append(-data.w_cubrir_prioridad * z)
    # 5b) Entrenadores sacados del banquillo: solo si faltan, y arriba.
    for b in del_banquillo:
        terms.append(-data.w_banquillo * b)
    for (f, cid), d in directiva.items():
        c = court_by_id[cid]
        coste = data.w_banquillo
        if c.is_satellite or c.surface == "RESINA":
            coste += data.w_directiva_fuera
        terms.append(-coste * d)
        # Cuanto más baja la división de los de su pista, más cuesta. Se
        # cuenta por pista (no por jugador) para no cargar el modelo.
        if data.w_directiva_division:
            niveles = [(pidx[pid].division - 1) * v for (pid, ff, cc), v in x.items()
                       if ff == f and cc == cid and pidx[pid].division]
            if niveles:
                tope_n = tope(c) * (NIVEL_MAX - 1)
                bajo = model.NewIntVar(0, tope_n, f"dirdiv_{f}_{cid}")
                model.Add(bajo >= sum(niveles) - tope_n * (1 - d))
                terms.append(-data.w_directiva_division * bajo)
    # 5c) Cada jugador con un entrenador de su color: en una pista con
    # entrenador de color k, cada jugador de otro color paga. Se cuenta por
    # pista y color (no por jugador) para no cargar el modelo.
    if clase_de and data.w_fuera_color:
        con_color = defaultdict(list)
        for (pid, f, cid), v in x.items():
            if data.color_jugador.get(pid):
                con_color[f, cid].append((data.color_jugador[pid], v))
        for (f, cid, k), y in clase_de.items():
            otros = [v for col, v in con_color[f, cid] if col != k]
            if not k or not otros:
                continue
            cap = tope(court_by_id[cid])
            malos = model.NewIntVar(0, cap, f"color_{f}_{cid}_{k}")
            model.Add(malos >= sum(otros) - cap * (1 - y))
            terms.append(-data.w_fuera_color * malos)

    # 5b) Los de la lista de un dedicado, juntos en su pista.
    if data.w_dedicado:
        for (f, e, cid), d in ded.items():
            for pid in data.dedicados[f][e]:
                if (pid, f, cid) not in x:
                    continue
                y = model.NewBoolVar(f"conded_{pid}_{f}_{cid}")
                model.Add(y <= d)
                model.Add(y <= x[pid, f, cid])
                terms.append(data.w_dedicado * y)

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
    solver.parameters.num_search_workers = num_workers()
    sin_mejora = (data.sin_mejora_s if data.sin_mejora_s is not None
                  else float(os.environ.get("MOTOR_SIN_MEJORA_S", "1")))
    if sin_mejora > 0:
        # Lo menos que vale colocar a uno: con menos margen entre la solución
        # y la cota, ya no cabe nadie más.
        colocados = model.NewIntVar(0, len(x), "colocados")
        model.Add(colocados == sum(x.values()))
        parar = _ParaSinMejora(solver, sin_mejora,
                               margen=(data.w_assign + piso) if data.paciencia else None,
                               colocados=colocados,
                               todos=sum(1 for p in players if del_jugador[p.id]))
        try:
            status = solver.Solve(model, parar)
        finally:
            parar.terminar()
    else:
        status = solver.Solve(model)

    por_franja: dict = {f: {} for f in franjas}
    cubiertas: dict = {f: set() for f in franjas}
    assigned: set[int] = set()
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for f in franjas:
            for c in courts:
                members = [p.id for p in players
                           if (p.id, f, c.id) in x and solver.Value(x[p.id, f, c.id])]
                if members:
                    por_franja[f][c.id] = members
                    assigned.update(members)
                    if (f, c.id) in cub and solver.Value(cub[f, c.id]):
                        cubiertas[f].add(c.id)

    dedicadas: dict = {}
    vigilancia: dict = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for (f, v, c), w in vig.items():
            if solver.Value(w):
                vigilancia.setdefault(f, {})[c] = v
        for (f, e, cid), d in ded.items():
            if solver.Value(d):
                dedicadas.setdefault(f, {})[e] = cid

    unassigned = [p.id for p in players if p.id not in assigned]
    return PairingResult(
        courts=por_franja[franjas[0]] if len(franjas) == 1 else {},
        unassigned=unassigned,
        status=solver.StatusName(status),
        objective=solver.ObjectiveValue() if status != cp_model.UNKNOWN else 0.0,
        franjas=por_franja if data.franjas else {},
        cubiertas=cubiertas if cub else {},
        dedicadas=dedicadas,
        vigilancia=vigilancia,
    )
