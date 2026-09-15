"""Pure-engine tests (no DB). Run: python manage.py test engine"""
from django.test import SimpleTestCase

from .pairing import Court, PairingInput, Player, solve_pairing
from .service import cupo_por_horario, hay_entrenamiento


def central(n):
    return [Court(id=i, venue_id=1, capacity=2) for i in range(1, n + 1)]


class PairingTests(SimpleTestCase):
    def test_neighbour_rule(self):
        # Div 1 and Div 5 can never share a court; Div 2 and 3 can.
        players = [
            Player(1, division=1), Player(2, division=5),
            Player(3, division=2), Player(4, division=3),
        ]
        res = solve_pairing(PairingInput(players=players, courts=central(4)))
        for members in res.courts.values():
            if 1 in members:
                self.assertNotIn(2, members)

    def test_veto_respected(self):
        players = [Player(1, division=2), Player(2, division=2)]
        res = solve_pairing(
            PairingInput(players=players, courts=central(2), vetoes={(1, 2)})
        )
        for members in res.courts.values():
            self.assertFalse({1, 2}.issubset(set(members)))

    def test_no_half_courts(self):
        players = [Player(i, division=2) for i in range(1, 5)]
        res = solve_pairing(PairingInput(players=players, courts=central(8)))
        for members in res.courts.values():
            self.assertGreaterEqual(len(members), 2)

    def test_individual_court_when_nobody_pairs(self):
        # Div 1 y Div 8 no pueden emparejarse: con individuales permitidos
        # cada uno entrena en su pista en vez de quedarse fuera.
        players = [Player(1, division=1), Player(2, division=8)]
        res = solve_pairing(
            PairingInput(players=players, courts=central(4), min_occupancy=1)
        )
        self.assertEqual(res.unassigned, [])
        self.assertTrue(all(len(m) == 1 for m in res.courts.values()))

    def test_density_penalty_keeps_courts_at_two(self):
        # 4 jugadores compatibles y 2 pistas de capacidad 4 pero densidad
        # normal 2: se reparten 2 y 2 en vez de apretar 4 en una.
        players = [Player(i, division=2) for i in range(1, 5)]
        courts = [
            Court(id=i, venue_id=1, capacity=4, normal_density=2)
            for i in (1, 2)
        ]
        res = solve_pairing(
            PairingInput(players=players, courts=courts, w_density=50_000)
        )
        self.assertEqual(sorted(len(m) for m in res.courts.values()), [2, 2])

    def test_density_yields_when_the_marginal_player_is_worth_it(self):
        # Una sola pista para 3 jugadores. Lo que compite con la penalización
        # de densidad es el jugador MARGINAL (el 3º), no el mejor de la pista.
        courts = [Court(id=1, venue_id=1, capacity=4, normal_density=2)]

        # Prioridad alta (déficit de cupo): compensa apretar a 3.
        altos = [Player(i, division=2, priority=40) for i in (1, 2, 3)]
        res = solve_pairing(
            PairingInput(players=altos, courts=courts, w_density=15_000)
        )
        self.assertEqual(len(res.courts[1]), 3)

        # Prioridad baja: el tercero se queda fuera y la pista sigue a 2.
        bajos = [Player(i, division=2, priority=1) for i in (1, 2, 3)]
        res = solve_pairing(
            PairingInput(players=bajos, courts=courts, w_density=15_000)
        )
        self.assertEqual(len(res.courts[1]), 2)
        self.assertEqual(len(res.unassigned), 1)

    def test_overflow_to_satellite(self):
        # 4 compatible players, only 1 central court (cap 2) -> spill to satellite.
        players = [Player(i, division=2) for i in range(1, 5)]
        courts = [
            Court(id=1, venue_id=1, capacity=2),
            Court(id=2, venue_id=2, capacity=2, is_satellite=True),
        ]
        res = solve_pairing(PairingInput(players=players, courts=courts))
        self.assertEqual(res.unassigned, [])
        self.assertIn(2, res.courts)  # satellite used


class _Ent:
    """Entrenador mínimo: al emparejador solo le hace falta el id."""

    def __init__(self, id):
        self.id = id


class EmparejarEntrenadoresTests(SimpleTestCase):
    """Nadie cubre dos pistas a la vez.

    En el cuadrante real de Iván, de 189 asignaciones en las bandas de alto
    rendimiento no hay una sola repetida, así que el motor tampoco repite
    mientras queden entrenadores capacitados libres.
    """

    def _emparejar(self, courts, niveles, divisiones, sponsors=None):
        from collections import Counter

        from .service import _emparejar_entrenadores

        elegibles = [_Ent(i) for i in sorted(niveles)]
        return _emparejar_entrenadores(
            courts, sponsors or {}, elegibles, niveles, divisiones, Counter()
        )

    def test_no_repite_cuando_hay_de_sobra(self):
        courts = {10: [1, 2], 11: [3, 4], 12: [5, 6]}
        divisiones = {1: 2, 2: 2, 3: 5, 4: 5, 5: 7, 6: 7}
        niveles = {100: None, 101: None, 102: None}   # None = todas
        asignado, repetidos = self._emparejar(courts, niveles, divisiones)
        self.assertEqual(len(set(asignado.values())), 3)
        self.assertEqual(repetidos, [])

    def test_encuentra_el_reparto_aunque_el_avido_falle(self):
        # La pista fácil (div 2) la puede llevar cualquiera; la difícil (div 7)
        # solo el 101. Repartiendo por orden, la fácil se llevaría al 101 y la
        # difícil se quedaría sin nadie.
        courts = {10: [1, 2], 11: [3, 4]}
        divisiones = {1: 2, 2: 2, 3: 7, 4: 7}
        niveles = {100: {2}, 101: {2, 7}}
        asignado, repetidos = self._emparejar(courts, niveles, divisiones)
        self.assertEqual(asignado, {10: 100, 11: 101})
        self.assertEqual(repetidos, [])

    def test_repite_solo_si_no_queda_nadie(self):
        courts = {10: [1], 11: [2]}
        divisiones = {1: 7, 2: 7}
        niveles = {100: {7}}                          # un solo capacitado
        asignado, repetidos = self._emparejar(courts, niveles, divisiones)
        self.assertEqual(set(asignado.values()), {100})
        self.assertEqual(len(repetidos), 1)

    def test_el_contrato_manda_sobre_el_emparejamiento(self):
        # El 101 sirve para todo y es el que la pista difícil se rifaría, pero
        # tiene contrato con el jugador 1, que está en la pista fácil.
        courts = {10: [1, 2], 11: [3, 4]}
        divisiones = {1: 2, 2: 2, 3: 7, 4: 7}
        niveles = {100: {2, 7}, 101: None}
        asignado, _ = self._emparejar(
            courts, niveles, divisiones, sponsors={1: {101}}
        )
        self.assertEqual(asignado[10], 101)
        self.assertEqual(asignado[11], 100)


class MediaJornadaCerradaTests(SimpleTestCase):
    """El club no abre los miércoles por la tarde: ahí no se coloca a nadie."""

    def test_el_miercoles_por_la_tarde_esta_cerrado(self):
        self.assertFalse(hay_entrenamiento(2, "TARDE"))

    def test_el_miercoles_por_la_manana_si(self):
        self.assertTrue(hay_entrenamiento(2, "MANANA"))

    def test_el_resto_de_tardes_si(self):
        for dia in (0, 1, 3, 4, 5):
            self.assertTrue(hay_entrenamiento(dia, "TARDE"), dia)


class PreferenciaDivisionTests(SimpleTestCase):
    """Dentro del ±1, quien lo pide tira hacia su lado. La D1 es la más alta:
    «hacia arriba» es la división de número menor."""

    def _pista_de(self, res, jid):
        return next(m for m in res.courts.values() if jid in m)

    def test_hacia_arriba_prefiere_la_division_mejor(self):
        players = [Player(1, division=4, division_pref=-1), Player(2, division=3),
                   Player(3, division=5), Player(4, division=4)]
        res = solve_pairing(PairingInput(players=players, courts=central(2)))
        self.assertIn(2, self._pista_de(res, 1))

    def test_hacia_abajo_prefiere_la_division_de_debajo(self):
        players = [Player(1, division=4, division_pref=1), Player(2, division=3),
                   Player(3, division=5), Player(4, division=4)]
        res = solve_pairing(PairingInput(players=players, courts=central(2)))
        self.assertIn(3, self._pista_de(res, 1))

    def test_nunca_salta_la_vecindad(self):
        # Pedir arriba no le empareja a dos divisiones de distancia.
        players = [Player(1, division=5, division_pref=-1), Player(2, division=3)]
        res = solve_pairing(PairingInput(players=players, courts=central(2)))
        for miembros in res.courts.values():
            self.assertFalse({1, 2} <= set(miembros))


class CupoPorHorarioTests(SimpleTestCase):
    """El cupo sale del horario solo si el horario describe la semana entera."""

    def test_una_excepcion_suelta_no_fija_el_cupo(self):
        horario = {(7, 1): (None, None, True, False)}
        self.assertNotIn(7, cupo_por_horario(horario, [0, 1, 2, 3, 4]))

    def test_semana_entera_sin_la_tarde_del_miercoles(self):
        horario = {(7, d): (None, None, True, True) for d in range(5)}
        # Cinco mañanas y cuatro tardes: el miércoles por la tarde no abre.
        self.assertEqual(cupo_por_horario(horario, [0, 1, 2, 3, 4])[7], 9)
