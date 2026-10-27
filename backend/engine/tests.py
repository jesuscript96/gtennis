"""Pure-engine tests (no DB). Run: python manage.py test engine"""
import os
import time
from unittest import mock

from django.test import SimpleTestCase

from .pairing import Court, PairingInput, Player, num_workers, solve_pairing
from .service import hay_entrenamiento


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

        # Prioridad alta (lleva días en el banquillo): compensa apretar a 3.
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


class TiempoDelSolverTests(SimpleTestCase):
    """21/10/2026: el solver para cuando lleva un rato sin mejorar, en vez de
    agotar siempre su tope (un día tardaba 3 minutos)."""

    def test_para_sin_mejora_mucho_antes_del_tope(self):
        players = [Player(i, division=1 + i % 8) for i in range(1, 41)]
        data = PairingInput(players=players, courts=central(20),
                            recent_partners={frozenset((i, i + 1)): 1 for i in range(1, 40)},
                            time_limit_s=30, sin_mejora_s=0.2)
        t = time.monotonic()
        res = solve_pairing(data)
        self.assertLess(time.monotonic() - t, 10)
        self.assertIn(res.status, ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(res.unassigned, [])

    def test_sin_parada_tambien_resuelve(self):
        players = [Player(i, division=2) for i in range(1, 5)]
        res = solve_pairing(PairingInput(players=players, courts=central(4),
                                         sin_mejora_s=0))
        self.assertEqual(res.unassigned, [])

    def test_hilos_del_entorno(self):
        with mock.patch.dict(os.environ, {"MOTOR_WORKERS": "3"}):
            self.assertEqual(num_workers(), 3)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MOTOR_WORKERS", None)
            self.assertGreaterEqual(num_workers(), 1)
            self.assertLessEqual(num_workers(), 8)


class _Ent:
    """Entrenador mínimo: al emparejador solo le hace falta el id."""

    def __init__(self, id):
        self.id = id


def _emparejar(courts, entrenadores, pesos=None, duros=None, blandos=None,
               info=None, con_quien=None, sesiones=None, load=None, vetos=None,
               banquillo=frozenset(), divisiones=None, nivel=0, tolerancia=None):
    from collections import Counter

    from .service import _emparejar_entrenadores

    return _emparejar_entrenadores(
        courts, duros or {}, [_Ent(i) for i in entrenadores],
        load if load is not None else Counter(),
        pesos=pesos, con_quien=con_quien, sesiones=sesiones,
        blandos=blandos, info_pistas=info, vetos=vetos,
        solo_si_atado=banquillo, divisiones=divisiones, nivel_protegido=nivel,
        tolerancia_division=tolerancia,
    )


class BanquilloTests(SimpleTestCase):
    """Sergio, Iván y Jorge están para ponerlos a mano: el motor no los reparte,
    pero sí los usa cuando un contrato o una franja les llama por su nombre."""

    def test_no_entra_por_su_cuenta(self):
        # Antes se repite al 100 en las dos pistas que dejar entrar al 101.
        asignado, _ = _emparejar({10: [1], 11: [2]}, [100, 101],
                                 banquillo={101})
        self.assertNotIn(101, asignado.values())

    def test_entra_si_lo_pide_un_contrato(self):
        asignado, _ = _emparejar({10: [1], 11: [2]}, [100, 101],
                                 duros={2: {101}}, banquillo={101})
        self.assertEqual(asignado, {10: 100, 11: 101})

    def test_solo_en_la_pista_que_lo_pide(self):
        asignado, _ = _emparejar({10: [1], 11: [2]}, [101],
                                 duros={2: {101}}, banquillo={101})
        self.assertEqual(asignado, {11: 101})


class VetoDeEntrenadorTests(SimpleTestCase):
    """«No debe entrenar con X»: regla dura, aunque deje la pista sin nadie."""

    def test_no_le_pone_al_vetado(self):
        # Por porcentajes el 101 iría con el 1, pero el 1 le tiene vetado.
        pesos = {1: {101: 1.0}, 2: {101: 1.0}, 3: {100: 1.0}, 4: {100: 1.0}}
        asignado, _ = _emparejar(
            {10: [1, 2], 11: [3, 4]}, [100, 101], pesos=pesos,
            vetos={1: {101}})
        self.assertEqual(asignado, {10: 100, 11: 101})

    def test_antes_sin_entrenador_que_con_el_vetado(self):
        asignado, _ = _emparejar({10: [1]}, [100], vetos={1: {100}})
        self.assertEqual(asignado, {})

    def test_el_veto_gana_al_contrato_duro(self):
        # El 2 tiene contrato con el 100 y el 1, de su misma pista, le veta.
        asignado, _ = _emparejar(
            {10: [1, 2]}, [100, 101], duros={2: {100}}, vetos={1: {100}})
        self.assertEqual(asignado, {10: 101})


class SinPrioridadTests(SimpleTestCase):
    """«Despriorizar y ver dónde encaja al final»: entra en pistas que ya abre
    otro, nunca abre una él solo."""

    def _pistas(self, n):
        return [Court(id=i, venue_id=1, capacity=2) for i in range(1, n + 1)]

    def test_no_abre_pista_el_solo(self):
        res = solve_pairing(PairingInput(
            players=[Player(id=1, division=3, sin_prioridad=True),
                     Player(id=2, division=3, sin_prioridad=True)],
            courts=self._pistas(2), min_occupancy=1,
        ))
        self.assertEqual(res.courts, {})

    def test_encaja_en_la_pista_de_otro(self):
        res = solve_pairing(PairingInput(
            players=[Player(id=1, division=3),
                     Player(id=2, division=3, sin_prioridad=True)],
            courts=self._pistas(2), min_occupancy=1,
        ))
        pistas = {c: sorted(m) for c, m in res.courts.items() if m}
        self.assertEqual(list(pistas.values()), [[1, 2]])

    def test_cede_el_sitio_al_que_si_tiene_prioridad(self):
        # Una sola pista de dos: entran los dos con prioridad, no el tercero.
        res = solve_pairing(PairingInput(
            players=[Player(id=1, division=3), Player(id=2, division=3),
                     Player(id=3, division=3, sin_prioridad=True)],
            courts=self._pistas(1), min_occupancy=1,
        ))
        self.assertEqual(sorted(res.courts[1]), [1, 2])


class GruposDelEntrenadorTests(SimpleTestCase):
    """Cada entrenador tiene su grupo de divisiones y se respeta mientras se
    pueda; el grupo 1 es el más estricto."""

    def _emparejar_con_grupos(self, courts, entrenadores, divisiones, peso=1000):
        from collections import Counter

        from academy.models import Entrenador
        from .service import _emparejar_entrenadores

        gente = [Entrenador(id=i, nombre=str(i), division_desde=d, division_hasta=h)
                 for i, (d, h) in entrenadores.items()]
        return _emparejar_entrenadores(
            courts, {}, gente, Counter(), divisiones=divisiones, peso_division=peso,
        )[0]

    def test_cada_uno_a_su_grupo(self):
        # 100 lleva del 1 al 2 y 101 del 6 al 7.
        courts = {10: [1, 2], 11: [3, 4]}
        asignado = self._emparejar_con_grupos(
            courts, {100: (1, 2), 101: (6, 7)},
            {1: 1, 2: 2, 3: 6, 4: 7})
        self.assertEqual(asignado, {10: 100, 11: 101})

    def test_si_no_hay_de_su_grupo_lo_coge_igual(self):
        # Una sola pista de división 7 y solo está el del grupo 1-2.
        asignado = self._emparejar_con_grupos({10: [1, 2]}, {100: (1, 2)}, {1: 7, 2: 7})
        self.assertEqual(asignado, {10: 100})

    def test_el_grupo_uno_manda_sobre_los_de_abajo(self):
        # Los dos entrenadores están fuera de su grupo en las dos pistas: el
        # reparto se decide por la pista de división 1, que pesa más.
        courts = {10: [1, 2], 11: [3, 4]}
        asignado = self._emparejar_con_grupos(
            courts, {100: (1, 1), 101: (9, 9)},
            {1: 1, 2: 1, 3: 9, 4: 9})
        self.assertEqual(asignado, {10: 100, 11: 101})

    def test_sin_grupo_declarado_da_igual(self):
        from academy.models import Entrenador

        e = Entrenador(nombre="X")
        self.assertEqual(e.distancia_division(1), 0)
        self.assertEqual(e.distancia_division(9), 0)

    def test_la_distancia_es_hasta_el_borde_del_grupo(self):
        from academy.models import Entrenador

        dani = Entrenador(nombre="Dani", division_desde=1, division_hasta=2)
        self.assertEqual(dani.distancia_division(2), 0)
        self.assertEqual(dani.distancia_division(4), 2)
        self.assertEqual(dani.distancia_division(7), 5)


class EmparejarEntrenadoresTests(SimpleTestCase):
    """Nadie cubre dos pistas a la vez.

    En el cuadrante real de Iván, de 189 asignaciones en las bandas de alto
    rendimiento no hay una sola repetida, así que el motor tampoco repite
    mientras queden entrenadores libres.
    """

    def test_no_repite_cuando_hay_de_sobra(self):
        asignado, repetidos = _emparejar(
            {10: [1, 2], 11: [3, 4], 12: [5, 6]}, [100, 101, 102])
        self.assertEqual(len(set(asignado.values())), 3)
        self.assertEqual(repetidos, [])

    def test_repite_solo_si_no_queda_nadie(self):
        asignado, repetidos = _emparejar({10: [1], 11: [2]}, [100])
        self.assertEqual(set(asignado.values()), {100})
        self.assertEqual(len(repetidos), 1)

    def test_el_contrato_manda_sobre_los_porcentajes(self):
        # Por porcentajes el 101 iría a la pista 11, pero tiene contrato con el 1.
        pesos = {3: {101: 1.0}, 4: {101: 1.0}}
        asignado, _ = _emparejar(
            {10: [1, 2], 11: [3, 4]}, [100, 101], pesos=pesos, duros={1: {101}})
        self.assertEqual(asignado, {10: 101, 11: 100})


class PorcentajesDeEntrenamientoTests(SimpleTestCase):
    """Con quién entrena cada alumno lo dicen sus porcentajes; la división solo
    empareja alumnos."""

    def test_cada_pista_con_el_suyo(self):
        pesos = {1: {101: 1.0}, 2: {101: 1.0}, 3: {100: 1.0}, 4: {100: 1.0}}
        asignado, _ = _emparejar({10: [1, 2], 11: [3, 4]}, [100, 101], pesos=pesos)
        self.assertEqual(asignado, {10: 101, 11: 100})

    def test_gana_quien_mas_les_toca_a_todos(self):
        pesos = {1: {100: 1.0}, 2: {101: 1.0}, 3: {101: 1.0}, 4: {101: 1.0}}
        asignado, _ = _emparejar({10: [1, 2], 11: [3, 4]}, [100, 101], pesos=pesos)
        self.assertEqual(asignado, {10: 100, 11: 101})

    def test_si_el_suyo_esta_ocupado_entrena_otro(self):
        pesos = {j: {100: 1.0} for j in (1, 2, 3, 4)}
        asignado, repetidos = _emparejar(
            {10: [1, 2], 11: [3, 4]}, [100, 101], pesos=pesos)
        self.assertEqual(sorted(asignado.values()), [100, 101])
        self.assertEqual(repetidos, [])

    def test_a_lo_largo_de_la_semana_se_acerca_a_los_porcentajes(self):
        # Carlos Taberner: Víctor 60% y Dani, Javi, Blas y Emilio 10% cada uno.
        from collections import Counter

        victor, secundarios = 100, [101, 102, 103, 104]
        pesos = {1: {victor: 0.6, **{x: 0.1 for x in secundarios}}}
        con_quien, sesiones, load = Counter(), Counter(), Counter()
        for _ in range(10):
            asignado, _r = _emparejar(
                {10: [1]}, [victor, *secundarios], pesos=pesos,
                con_quien=con_quien, sesiones=sesiones, load=load)
            con_quien[(1, asignado[10])] += 1
            sesiones[1] += 1
        self.assertEqual(con_quien[(1, victor)], 6)
        self.assertEqual([con_quien[(1, x)] for x in secundarios], [1, 1, 1, 1])


class MediaJornadaCerradaTests(SimpleTestCase):
    """El club no abre los miércoles por la tarde: ahí no se coloca a nadie."""

    def test_el_miercoles_por_la_tarde_esta_cerrado(self):
        self.assertFalse(hay_entrenamiento(2, "TARDE"))

    def test_el_miercoles_por_la_manana_si(self):
        self.assertTrue(hay_entrenamiento(2, "MANANA"))

    def test_el_resto_de_tardes_si(self):
        for dia in (0, 1, 3, 4):
            self.assertTrue(hay_entrenamiento(dia, "TARDE"), dia)

    def test_el_sabado_solo_por_la_manana(self):
        self.assertTrue(hay_entrenamiento(5, "MANANA"))
        self.assertFalse(hay_entrenamiento(5, "TARDE"))


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


def _manana(players, courts, **kw):
    """Las dos franjas de una mañana (1 = M1, 2 = M2) decididas a la vez."""
    return solve_pairing(PairingInput(players=players, courts=courts, franjas=[1, 2], **kw))


def _por_franja(res):
    return {f: sum(len(m) for m in pistas.values()) for f, pistas in res.franjas.items()}


class MananaEnteraTests(SimpleTestCase):
    """La mañana se decide de una vez: los jugadores se reparten entre M1 y M2
    en vez de llenar la primera franja y dejar la segunda vacía."""

    def test_reparte_entre_las_dos_franjas(self):
        # En la primera caben los ocho, pero se reparten cuatro y cuatro.
        players = [Player(i, division=2) for i in range(1, 9)]
        res = _manana(players, central(4))
        self.assertEqual(res.unassigned, [])
        self.assertEqual(_por_franja(res), {1: 4, 2: 4})

    def test_la_franja_fija_manda_y_los_demas_compensan(self):
        # Seis tienen que ir a la segunda: los seis libres van a la primera.
        players = [Player(i, division=2) for i in range(1, 13)]
        fijos = {i: {2: 1} for i in range(1, 7)}
        res = _manana(players, central(8), franjas_de=fijos)
        self.assertEqual(_por_franja(res), {1: 6, 2: 6})
        segunda = {j for m in res.franjas[2].values() for j in m}
        self.assertTrue(set(range(1, 7)) <= segunda)

    def test_en_proporcion_a_los_entrenadores(self):
        # Con el doble de entrenadores a primera hora, el doble de jugadores.
        players = [Player(i, division=2) for i in range(1, 13)]
        res = _manana(players, central(8), entrenadores_franja={1: 4, 2: 2})
        self.assertEqual(_por_franja(res), {1: 8, 2: 4})

    def test_nadie_repite_en_la_misma_manana(self):
        players = [Player(i, division=2) for i in range(1, 5)]
        res = _manana(players, central(4))
        colocados = [j for pistas in res.franjas.values() for m in pistas.values() for j in m]
        self.assertEqual(sorted(colocados), [1, 2, 3, 4])

    def test_no_deja_a_nadie_fuera_por_equilibrar(self):
        # Todos solo pueden a primera hora: la segunda queda vacía y entran todos.
        players = [Player(i, division=2) for i in range(1, 8)]
        solo_primera = {i: {1: 1} for i in range(1, 8)}
        res = _manana(players, central(4), franjas_de=solo_primera, min_occupancy=1)
        self.assertEqual(res.unassigned, [])
        self.assertEqual(_por_franja(res), {1: 7, 2: 0})

    def test_no_parte_una_pareja_para_cuadrar(self):
        # Dos jugadores: una pista de dos, no una individual en cada franja.
        players = [Player(1, division=2), Player(2, division=2)]
        res = _manana(players, central(4), min_occupancy=1)
        tamanos = [len(m) for pistas in res.franjas.values() for m in pistas.values()]
        self.assertEqual(tamanos, [2])

    def test_quien_viene_a_las_dos_franjas_entra_en_las_dos(self):
        players = [Player(1, division=2), Player(2, division=2)]
        res = _manana(players, central(2), max_franjas={1: 2}, min_occupancy=1)
        veces = sum(1 in m for pistas in res.franjas.values() for m in pistas.values())
        self.assertEqual(veces, 2)


class VecindadPropiaTests(SimpleTestCase):
    """Hay alumnos que solo entrenan con su división o con la de encima, aunque
    el club admita una horquilla más ancha. Es regla dura."""

    def _juntos(self, res):
        return [sorted(m) for m in res.courts.values()]

    def test_con_la_de_encima_si(self):
        # Victoria (7) solo sube: con la 6 comparte pista.
        victoria = Player(1, division=7, div_arriba=1, div_abajo=0)
        res = solve_pairing(PairingInput(
            players=[victoria, Player(2, division=6)], courts=central(2), neighbor_span=2))
        self.assertEqual(self._juntos(res), [[1, 2]])

    def test_con_la_de_debajo_no(self):
        # La 8 le valdría al club (±2) pero a ella no: nadie entra.
        victoria = Player(1, division=7, div_arriba=1, div_abajo=0)
        res = solve_pairing(PairingInput(
            players=[victoria, Player(3, division=8)], courts=central(2), neighbor_span=2))
        self.assertEqual(self._juntos(res), [])
        self.assertEqual(sorted(res.unassigned), [1, 3])

    def test_manda_la_regla_del_mas_estricto(self):
        # Al de la 6 no le restringe nadie, pero la de la 7 solo sube.
        victoria = Player(1, division=7, div_arriba=1, div_abajo=0)
        res = solve_pairing(PairingInput(
            players=[victoria, Player(2, division=8), Player(3, division=9)],
            courts=central(2), neighbor_span=2))
        for miembros in res.courts.values():
            self.assertNotIn(1, miembros)

    def test_solo_su_division(self):
        solitario = Player(1, division=5, div_arriba=0, div_abajo=0)
        res = solve_pairing(PairingInput(
            players=[solitario, Player(2, division=4)], courts=central(2), neighbor_span=2))
        self.assertEqual(self._juntos(res), [])
        res = solve_pairing(PairingInput(
            players=[solitario, Player(2, division=5)], courts=central(2), neighbor_span=2))
        self.assertEqual(self._juntos(res), [[1, 2]])

    def test_sin_regla_propia_manda_la_del_club(self):
        res = solve_pairing(PairingInput(
            players=[Player(1, division=5), Player(2, division=7)],
            courts=central(2), neighbor_span=2))
        self.assertEqual(self._juntos(res), [[1, 2]])


class ChicosYChicasTests(SimpleTestCase):
    """Un chico no comparte pista con una chica de nivel más bajo. Al revés sí:
    ella puede entrenar con chicos de su nivel o de nivel más bajo."""

    def _juntos(self, res):
        return [sorted(m) for m in res.courts.values()]

    def test_el_chico_no_baja_con_una_chica(self):
        chico = Player(1, division=2, sexo="CHICO")
        chica = Player(2, division=3, sexo="CHICA")
        res = solve_pairing(PairingInput(players=[chico, chica], courts=central(2)))
        self.assertEqual(self._juntos(res), [])

    def test_la_chica_si_puede_bajar_con_un_chico(self):
        chica = Player(1, division=2, sexo="CHICA")
        chico = Player(2, division=3, sexo="CHICO")
        res = solve_pairing(PairingInput(players=[chica, chico], courts=central(2)))
        self.assertEqual(self._juntos(res), [[1, 2]])

    def test_del_mismo_nivel_si(self):
        res = solve_pairing(PairingInput(
            players=[Player(1, division=3, sexo="CHICO"), Player(2, division=3, sexo="CHICA")],
            courts=central(2)))
        self.assertEqual(self._juntos(res), [[1, 2]])

    def test_sin_declarar_no_se_aplica(self):
        res = solve_pairing(PairingInput(
            players=[Player(1, division=2, sexo="CHICO"), Player(2, division=3)],
            courts=central(2)))
        self.assertEqual(self._juntos(res), [[1, 2]])


class EdadesTests(SimpleTestCase):
    """Los críos entrenan con críos: hasta 14 años, dos de diferencia como
    mucho; de 15 a 18, tres. Manda el más estricto de los dos."""

    def _juntos(self, a, b):
        res = solve_pairing(PairingInput(players=[a, b], courts=central(2)))
        return any({1, 2} <= set(m) for m in res.courts.values())

    def test_doce_y_catorce_si(self):
        self.assertTrue(self._juntos(Player(1, division=3, edad=12), Player(2, division=3, edad=14)))

    def test_doce_y_quince_no(self):
        self.assertFalse(self._juntos(Player(1, division=3, edad=12), Player(2, division=3, edad=15)))

    def test_quince_y_dieciocho_si(self):
        self.assertTrue(self._juntos(Player(1, division=3, edad=15), Player(2, division=3, edad=18)))

    def test_el_menor_manda_aunque_el_otro_sea_mayor(self):
        # El de 19 no tiene tope, pero el de 16 sí: cuatro años son demasiados.
        self.assertFalse(self._juntos(Player(1, division=3, edad=16), Player(2, division=3, edad=20)))

    def test_entre_adultos_no_hay_tope(self):
        self.assertTrue(self._juntos(Player(1, division=3, edad=22), Player(2, division=3, edad=30)))

    def test_sin_edad_no_se_aplica(self):
        self.assertTrue(self._juntos(Player(1, division=3, edad=12), Player(2, division=3)))

    def test_una_edad_imposible_cuenta_como_no_declarada(self):
        # Un alumno con "1 año" es un error de tecleo, no un bebé.
        self.assertTrue(self._juntos(Player(1, division=3, edad=1), Player(2, division=3, edad=17)))


def _tierra_y_resina():
    return [Court(id=1, venue_id=1, capacity=2, surface="TIERRA"),
            Court(id=2, venue_id=1, capacity=2, surface="RESINA")]


class PistaSegunDivisionTests(SimpleTestCase):
    """La división manda en qué pista se entrena: los de arriba, en las
    primeras. Es un desempate, no una regla."""

    def _pista_de(self, res, jid):
        return next(c for c, m in res.courts.items() if jid in m)

    def test_los_de_arriba_van_a_las_primeras(self):
        courts = [Court(id=n, venue_id=1, capacity=2, number=n) for n in (1, 2, 3, 4)]
        players = [Player(1, division=1), Player(2, division=1),
                   Player(11, division=4), Player(12, division=4)]
        res = solve_pairing(PairingInput(players=players, courts=courts, neighbor_span=1))
        self.assertLess(self._pista_de(res, 1), self._pista_de(res, 11))

    def test_no_deja_a_nadie_fuera_por_la_pista(self):
        # Solo queda la última pista: se usa igualmente.
        courts = [Court(id=8, venue_id=1, capacity=2, number=8)]
        players = [Player(1, division=1), Player(2, division=1)]
        res = solve_pairing(PairingInput(players=players, courts=courts))
        self.assertEqual(res.unassigned, [])


class TierraAntesQueResinaTests(SimpleTestCase):
    """El club entrena en tierra. La resina es para cuando ya no queda tierra,
    o para quien la tiene declarada en su ficha."""

    def test_primero_la_tierra(self):
        players = [Player(1, division=3), Player(2, division=3)]
        res = solve_pairing(PairingInput(players=players, courts=_tierra_y_resina()))
        self.assertEqual(list(res.courts), [1])

    def test_la_resina_cuando_la_tierra_se_llena(self):
        players = [Player(i, division=3) for i in range(1, 5)]
        res = solve_pairing(PairingInput(players=players, courts=_tierra_y_resina()))
        self.assertEqual(res.unassigned, [])
        self.assertEqual(sorted(res.courts), [1, 2])

    def test_quien_la_tiene_declarada_juega_en_resina(self):
        players = [Player(1, division=3, surface_pref="RESINA"),
                   Player(2, division=3, surface_pref="RESINA")]
        res = solve_pairing(PairingInput(players=players, courts=_tierra_y_resina()))
        self.assertEqual(list(res.courts), [2])

    def test_nadie_se_queda_fuera_por_no_pisar_resina(self):
        # Solo hay resina: se usa igualmente.
        players = [Player(1, division=3), Player(2, division=3)]
        solo_resina = [Court(id=2, venue_id=1, capacity=2, surface="RESINA")]
        res = solve_pairing(PairingInput(players=players, courts=solo_resina))
        self.assertEqual(res.unassigned, [])


class EntrenadorDeReservaTests(SimpleTestCase):
    """Quien está de reserva no entra en el reparto automático; se le pone a
    mano desde el cuadrante."""

    def test_el_motivo_no_habla_de_la_reserva(self):
        # La reserva se filtra antes, al elegir a los candidatos: para el panel
        # sigue estando libre y se le puede arrastrar a una pista.
        from academy.models import Entrenador, Turno as T
        from engine.service import motivo_no_disponible

        c = Entrenador(nombre="Sergio", disponible_semana=True, reserva=True)
        turno = T(codigo="M1", bloque=T.Bloque.MANANA)
        self.assertIsNone(motivo_no_disponible(c, 0, turno, None, {}, {}, {}))


class PistasAlternasTests(SimpleTestCase):
    """Con menos entrenadores que pistas, cada pista sin entrenador tiene uno
    al lado. El ejemplo de Iván: ocho pistas y cinco entrenadores, 1-3-4-6-7."""

    def _sin_vecina(self, numeros, con):
        return [n for n in numeros
                if n not in con and (n - 1) not in con and (n + 1) not in con]

    def test_el_ejemplo_de_ivan(self):
        from .reparto_pistas import pistas_con_entrenador

        self.assertEqual(pistas_con_entrenador(range(1, 9), 5), {1, 3, 4, 6, 7})

    def test_con_entrenadores_de_sobra_van_todas(self):
        from .reparto_pistas import pistas_con_entrenador

        self.assertEqual(pistas_con_entrenador(range(1, 9), 8), set(range(1, 9)))

    def test_ninguna_huerfana_mientras_se_pueda(self):
        from .reparto_pistas import pistas_con_entrenador

        for k in (3, 4, 5, 6, 7):
            con = pistas_con_entrenador(range(1, 9), k)
            self.assertEqual(len(con), k)
            self.assertEqual(self._sin_vecina(range(1, 9), con), [], k)

    def test_una_pista_vacia_corta_la_contiguidad(self):
        from .reparto_pistas import pistas_con_entrenador

        # La 4 no tiene jugadores: la 3 y la 5 no son vecinas.
        ocupadas = [1, 2, 3, 5, 6]
        con = pistas_con_entrenador(ocupadas, 2)
        self.assertEqual(self._sin_vecina(ocupadas, con), [])
        self.assertTrue({2, 5} <= con or {2, 6} <= con or {1, 5} <= con
                        or {3, 5} <= con or {2, 5} == con)

    def test_reparto_entre_sedes(self):
        from .reparto_pistas import repartir_entre_sedes

        # Resort con 8 pistas y un satélite con 3, y 5 entrenadores: el
        # satélite necesita al menos uno; el resto, al Resort.
        reparto = repartir_entre_sedes({"R": list(range(1, 9)), "S": [1, 2, 3]},
                                       5, ["R", "S"])
        self.assertEqual(reparto, {"R": 4, "S": 1})


class ContratoBlandoTests(SimpleTestCase):
    """Blando: primero su grupo; con el jugador del contrato solo si no deja
    ninguna otra pista sin entrenador."""

    def test_no_deja_otra_pista_huerfana(self):
        # Tres pistas seguidas y un entrenador: va a la del medio y vigila las
        # dos. Con su jugador, en la 1, la 3 se quedaría sin nadie al lado.
        courts = {201: [1, 2], 202: [3, 4], 203: [5, 6]}
        info = {200 + n: ("resort", n, 0) for n in (1, 2, 3)}
        asignado, repetidos = _emparejar(courts, [100], blandos={1: {100}}, info=info)
        self.assertEqual(asignado, {202: 100})
        self.assertEqual(repetidos, [])

    def test_va_con_su_jugador_cuando_puede(self):
        # Por porcentajes el 102 iría a la 10, pero tiene contrato blando con el 3.
        pesos = {1: {102: 1.0}, 2: {102: 1.0}}
        asignado, _ = _emparejar(
            {10: [1, 2], 11: [3, 4]}, [100, 101, 102], pesos=pesos,
            blandos={3: {102}})
        self.assertEqual(asignado[11], 102)
        self.assertIn(asignado[10], {100, 101})


class RepartoConPocosEntrenadoresTests(SimpleTestCase):
    """Con menos entrenadores que pistas, las que no llevan uno lo tienen al
    lado, y a esas no se les repite a nadie."""

    def test_ocho_pistas_cinco_entrenadores(self):
        courts = {200 + n: [n * 10, n * 10 + 1] for n in range(1, 9)}
        info = {200 + n: ("resort", n, 0) for n in range(1, 9)}
        asignado, repetidos = _emparejar(courts, [100 + i for i in range(5)], info=info)
        self.assertEqual({p - 200 for p in asignado}, {1, 3, 4, 6, 7})
        self.assertEqual(len(set(asignado.values())), 5)
        self.assertEqual(repetidos, [])

    def test_nunca_repite_y_avisa_de_las_huerfanas(self):
        # Un entrenador y tres pistas: da una, y las otras dos se listan como
        # huérfanas. Antes se le repetía en las tres, que es justo lo que el
        # club no quiere.
        asignado, huerfanas = _emparejar({10: [1], 11: [2], 12: [3]}, [100])
        self.assertEqual(set(asignado), {10})
        self.assertEqual(huerfanas, [11, 12])

    def test_los_porcentajes_deciden_quien_va_a_cada_pista_elegida(self):
        # Tres pistas y dos entrenadores: van a la 1 y la 3, cada uno a la de
        # sus alumnos.
        courts = {201: [1], 202: [2], 203: [3]}
        info = {200 + n: ("resort", n, 0) for n in (1, 2, 3)}
        pesos = {1: {101: 1.0}, 3: {100: 1.0}}
        asignado, _ = _emparejar(courts, [100, 101], pesos=pesos, info=info)
        self.assertEqual(asignado, {201: 101, 203: 100})


class TardeYMananaTests(SimpleTestCase):
    """Por la tarde caben tres en una pista y por la mañana nunca; y a la
    segunda franja de la tarde solo se va cuando la primera está llena."""

    def _pistas(self, n, cap=4):
        return [Court(id=i, venue_id=1, capacity=cap, normal_density=2)
                for i in range(1, n + 1)]

    def _jugadores(self, n):
        return [Player(id=i, division=5) for i in range(1, n + 1)]

    def test_por_la_manana_nunca_tres_en_una_pista(self):
        res = solve_pairing(PairingInput(
            players=self._jugadores(6), courts=self._pistas(3),
            capacidad_max=2, min_occupancy=1,
        ))
        self.assertTrue(all(len(m) <= 2 for m in res.courts.values()))

    def test_por_la_tarde_tres_antes_que_abrir_otra_franja(self):
        # Dos pistas en T1 y seis jugadores: con tope de pistas, tres por pista.
        res = solve_pairing(PairingInput(
            players=self._jugadores(6), courts=self._pistas(4),
            franjas=[1, 2], capacidad_max=3, max_pistas={1: 2, 2: 2},
            coste_franja={1: 0, 2: 2500}, min_occupancy=1, w_assign=1000,
        ))
        en_t1 = sum(len(m) for m in res.franjas.get(1, {}).values())
        self.assertEqual(en_t1, 6)
        self.assertFalse(any(res.franjas.get(2, {}).values()))

    def test_no_abre_mas_pistas_que_entrenadores(self):
        res = solve_pairing(PairingInput(
            players=self._jugadores(6), courts=self._pistas(6),
            franjas=[1], max_pistas={1: 2}, capacidad_max=3, min_occupancy=1,
        ))
        self.assertEqual(len([m for m in res.franjas[1].values() if m]), 2)


class AntesUnaParejaQueDosIndividualesTests(SimpleTestCase):
    """Preferimos una pareja y una pista vacía; y antes de dejar a dos solos,
    se estira una división o un año."""

    def test_prefiere_pareja_a_dos_individuales(self):
        res = solve_pairing(PairingInput(
            players=[Player(id=1, division=5), Player(id=2, division=5)],
            courts=[Court(id=i, venue_id=1, capacity=2) for i in (1, 2)],
            min_occupancy=1, w_individual=1200,
        ))
        self.assertEqual([sorted(m) for m in res.courts.values() if m], [[1, 2]])

    def test_estira_la_division_antes_que_dejarlos_solos(self):
        # Dos divisiones de distancia: prohibido con ±1, pero sale más barato
        # que dos pistas individuales.
        res = solve_pairing(PairingInput(
            players=[Player(id=1, division=4), Player(id=2, division=6)],
            courts=[Court(id=i, venue_id=1, capacity=2) for i in (1, 2)],
            min_occupancy=1, w_individual=1200, span_extra=1, w_relajar=800,
        ))
        self.assertEqual([sorted(m) for m in res.courts.values() if m], [[1, 2]])

    def test_sin_estiron_siguen_separados(self):
        res = solve_pairing(PairingInput(
            players=[Player(id=1, division=4), Player(id=2, division=6)],
            courts=[Court(id=i, venue_id=1, capacity=2) for i in (1, 2)],
            min_occupancy=1, w_individual=1200,
        ))
        self.assertEqual(sorted(len(m) for m in res.courts.values() if m), [1, 1])

    def test_el_estiron_no_rompe_chico_y_chica(self):
        res = solve_pairing(PairingInput(
            players=[Player(id=1, division=4, sexo="CHICO"),
                     Player(id=2, division=6, sexo="CHICA")],
            courts=[Court(id=i, venue_id=1, capacity=2) for i in (1, 2)],
            min_occupancy=1, w_individual=1200, span_extra=1, w_relajar=800,
        ))
        self.assertEqual(sorted(len(m) for m in res.courts.values() if m), [1, 1])

    def test_el_estiron_no_toca_la_horquilla_de_la_ficha(self):
        # El 1 tiene declarado «solo su división»: no se estira por él.
        res = solve_pairing(PairingInput(
            players=[Player(id=1, division=5, div_arriba=0, div_abajo=0),
                     Player(id=2, division=6)],
            courts=[Court(id=i, venue_id=1, capacity=2) for i in (1, 2)],
            min_occupancy=1, w_individual=1200, span_extra=1, w_relajar=800,
        ))
        self.assertEqual(sorted(len(m) for m in res.courts.values() if m), [1, 1])


class GrupoAltoSiempreConEntrenadorTests(SimpleTestCase):
    """Las pistas de división 1-2 se cubren las primeras y, si no llega el
    reparto, se saca a uno del banquillo."""

    def test_cubre_antes_la_pista_de_division_alta(self):
        # Dos pistas y un entrenador: la de D1-D2 se lleva al entrenador.
        asignado, _ = _emparejar(
            {10: [1, 2], 11: [3, 4]}, [100],
            info={10: ("resort", 1, 0), 11: ("resort", 5, 0)},
            divisiones={1: 7, 2: 7, 3: 2, 4: 3}, nivel=2)
        self.assertEqual(set(asignado), {11})

    def test_saca_al_banquillo_si_no_queda_nadie(self):
        # El único del reparto se va con los suyos a la pista 10; la 11, que es
        # de grupo alto, se queda sin nadie y la cubre el del banquillo.
        pesos = {1: {100: 1.0}, 2: {100: 1.0}}
        asignado, _ = _emparejar(
            {10: [1, 2], 11: [3, 4]}, [100, 101], pesos=pesos,
            divisiones={1: 7, 2: 7, 3: 1, 4: 2}, nivel=2, banquillo={101})
        self.assertEqual(asignado, {10: 100, 11: 101})

    def test_sin_nivel_protegido_el_banquillo_sigue_fuera(self):
        pesos = {1: {100: 1.0}, 2: {100: 1.0}}
        asignado, _ = _emparejar(
            {10: [1, 2], 11: [3, 4]}, [100, 101], pesos=pesos,
            divisiones={1: 7, 2: 7, 3: 1, 4: 2}, nivel=0, banquillo={101})
        self.assertNotIn(101, asignado.values())

    def test_el_veto_gana_al_rescate(self):
        # El 3 no puede entrenar con el 101, así que su pista se queda sin
        # entrenador aunque sea de grupo alto.
        pesos = {1: {100: 1.0}, 2: {100: 1.0}}
        asignado, _ = _emparejar(
            {10: [1, 2], 11: [3, 4]}, [100, 101], pesos=pesos,
            divisiones={1: 7, 2: 7, 3: 1, 4: 2}, nivel=2, banquillo={101},
            vetos={3: {101}})
        self.assertNotIn(11, asignado)


class ParejaDeclaradaMandaTests(SimpleTestCase):
    """Lo que el club declara a mano manda sobre las reglas de emparejamiento
    —división, edad, chico/chica—, pero nunca sobre una rencilla."""

    def _pistas(self):
        return [Court(id=1, venue_id=1, capacity=2)]

    def _dos(self):
        # Un chico de división mejor y una chica de división peor: prohibido.
        return [Player(id=1, division=6, sexo="CHICO", edad=14),
                Player(id=2, division=7, sexo="CHICA", edad=14)]

    def test_sin_declarar_no_comparten_pista(self):
        res = solve_pairing(PairingInput(
            players=self._dos(), courts=self._pistas(), min_occupancy=1))
        self.assertNotEqual(sorted(res.courts.get(1, [])), [1, 2])

    def test_declarada_comparten_pista(self):
        res = solve_pairing(PairingInput(
            players=self._dos(), courts=self._pistas(), min_occupancy=1,
            pairs_declaradas={frozenset((1, 2))}, pairs_soft={frozenset((1, 2))},
            w_pair=5000))
        self.assertEqual(sorted(res.courts[1]), [1, 2])

    def test_la_rencilla_sigue_mandando(self):
        res = solve_pairing(PairingInput(
            players=self._dos(), courts=self._pistas(), min_occupancy=1,
            vetoes={(1, 2)}, pairs_declaradas={frozenset((1, 2))}))
        self.assertNotEqual(sorted(res.courts.get(1, [])), [1, 2])


class _EntGrupo:
    """Entrenador con su grupo de divisiones, para el límite de tolerancia."""

    def __init__(self, id, desde=None, hasta=None):
        self.id, self.division_desde, self.division_hasta = id, desde, hasta

    def distancia_division(self, nivel):
        if nivel is None or (self.division_desde is None and self.division_hasta is None):
            return 0
        desde = self.division_desde if self.division_desde is not None else nivel
        hasta = self.division_hasta if self.division_hasta is not None else nivel
        return max(0, desde - nivel, nivel - hasta)


def _emparejar_grupos(courts, entrenadores, divisiones, tolerancia=None, **kw):
    from collections import Counter

    from .service import _emparejar_entrenadores

    return _emparejar_entrenadores(
        courts, {}, entrenadores, Counter(), divisiones=divisiones,
        tolerancia_division=tolerancia, **kw)


class ToleranciaDeGrupoTests(SimpleTestCase):
    """El grupo del entrenador es un límite, no un coste: Dani Gimeno lleva el
    1-2 y llega hasta la 4, pero no acaba con un D7."""

    def test_no_le_dan_una_pista_fuera_de_su_grupo(self):
        # 100 lleva el grupo 1-2; 101, del 4 al 9. La pista de D7 es del 101.
        asignado, _ = _emparejar_grupos(
            {10: [1], 11: [2]}, [_EntGrupo(100, 1, 2), _EntGrupo(101, 4, 9)],
            {1: 7, 2: 2}, tolerancia=2)
        self.assertEqual(asignado, {10: 101, 11: 100})

    def test_llega_hasta_la_tolerancia(self):
        asignado, _ = _emparejar_grupos(
            {10: [1]}, [_EntGrupo(100, 1, 2)], {1: 4}, tolerancia=2)
        self.assertEqual(asignado, {10: 100})

    def test_cede_antes_que_dejar_la_pista_sin_nadie(self):
        asignado, _ = _emparejar_grupos(
            {10: [1]}, [_EntGrupo(100, 1, 2)], {1: 9}, tolerancia=2)
        self.assertEqual(asignado, {10: 100})

    def test_sin_tolerancia_se_comporta_como_antes(self):
        asignado, _ = _emparejar_grupos(
            {10: [1]}, [_EntGrupo(100, 1, 2)], {1: 9})
        self.assertEqual(asignado, {10: 100})


class PatronAlternoConBanquilloTests(SimpleTestCase):
    """Los de banquillo no cuentan para decidir el patrón alterno: si contaran,
    bastaría con tenerlos ahí para que dejara de aplicarse."""

    def test_el_patron_sigue_saliendo_con_banquillo_disponible(self):
        courts = {200 + n: [n * 10, n * 10 + 1] for n in range(1, 8)}
        info = {200 + n: ("resort", n, 0) for n in range(1, 8)}
        # Cinco del reparto y tres de banquillo, para siete pistas.
        asignado, _ = _emparejar(
            courts, [100, 101, 102, 103, 104, 900, 901, 902],
            info=info, banquillo={900, 901, 902})
        self.assertEqual({p - 200 for p in asignado}, {1, 3, 4, 6, 7})

    def test_la_protegida_entre_dos_cubiertas_no_llama_al_banquillo(self):
        courts = {201: [1], 202: [2], 203: [3]}
        info = {201: ("resort", 1, 0), 202: ("resort", 2, 0), 203: ("resort", 3, 0)}
        # La pista del medio es de grupo 1-2 pero tiene vecinas cubiertas.
        asignado, _ = _emparejar(
            courts, [100, 101, 900], info=info, banquillo={900},
            divisiones={1: 5, 2: 2, 3: 5}, nivel=2)
        self.assertEqual(set(asignado), {201, 203})
        self.assertNotIn(900, asignado.values())


class PrimerasPistasParaLosMejoresTests(SimpleTestCase):
    """Los mejores grupos, en las primeras pistas, y sin dejar huecos."""

    def _pistas(self, n):
        return [Court(id=i, venue_id=1, capacity=2, number=i) for i in range(1, n + 1)]

    def test_el_mejor_grupo_va_a_la_pista_mas_baja(self):
        res = solve_pairing(PairingInput(
            players=[Player(id=1, division=2), Player(id=2, division=2),
                     Player(id=3, division=7), Player(id=4, division=7)],
            courts=self._pistas(4), w_pista_division=50))
        pistas = {c: sorted(m) for c, m in res.courts.items() if m}
        self.assertEqual(pistas[min(pistas)], [1, 2])

    def test_no_deja_la_primera_pista_vacia(self):
        # Nadie es de división 1: antes la pista 1 se quedaba libre.
        res = solve_pairing(PairingInput(
            players=[Player(id=1, division=2), Player(id=2, division=2)],
            courts=self._pistas(5), w_pista_division=50, w_orden_pista=60))
        self.assertEqual(sorted(res.courts.get(1, [])), [1, 2])


class ArribaSiempreEnTierraTests(SimpleTestCase):
    """Las divisiones 1 y 2 no pisan resina salvo que se les declare."""

    def _pistas(self):
        return [Court(id=1, venue_id=1, capacity=2, number=1, surface="TIERRA"),
                Court(id=2, venue_id=1, capacity=2, number=2, surface="RESINA")]

    def test_un_d2_no_acaba_en_resina(self):
        # Cuatro jugadores para dos pistas: los de arriba, a la de tierra.
        res = solve_pairing(PairingInput(
            players=[Player(id=1, division=2, surface_pref="TIERRA"),
                     Player(id=2, division=2, surface_pref="TIERRA"),
                     Player(id=3, division=7), Player(id=4, division=7)],
            courts=self._pistas(), w_resina=1200))
        self.assertEqual(sorted(res.courts[1]), [1, 2])

    def test_si_se_le_declara_la_resina_va(self):
        res = solve_pairing(PairingInput(
            players=[Player(id=1, division=2, surface_pref="RESINA"),
                     Player(id=2, division=2, surface_pref="RESINA")],
            courts=self._pistas(), w_resina=1200))
        self.assertEqual(sorted(res.courts[2]), [1, 2])


class NadieSoloPorLaTardeTests(SimpleTestCase):
    """Antes una pista de tres que alguien solo."""

    def test_nueve_jugadores_salen_en_cuatro_pistas(self):
        res = solve_pairing(PairingInput(
            players=[Player(id=i, division=7) for i in range(1, 10)],
            courts=[Court(id=i, venue_id=1, capacity=3, normal_density=2,
                          number=i) for i in range(1, 8)],
            capacidad_max=3, min_occupancy=2, w_density=1000,
        ))
        tamanos = sorted(len(m) for m in res.courts.values() if m)
        self.assertEqual(tamanos, [2, 2, 2, 3])
        self.assertEqual(res.unassigned, [])


class PistaSinEntrenadorTests(SimpleTestCase):
    """Regla del club (13/10/2026): ninguna pista de tres sin entrenador; una
    de dos sin él solo al lado de otra con entrenador y dos como mucho, que la
    vigila. Cada entrenador vigila a una sola."""

    def _resolver(self, n_jugadores, entrenadores, n_pistas=4, con_entrenador=None):
        pistas = [Court(id=i, venue_id=1, capacity=3, number=i)
                  for i in range(1, n_pistas + 1)]
        return solve_pairing(PairingInput(
            players=[Player(id=i, division=5) for i in range(n_jugadores)],
            courts=pistas, franjas=[1], capacidad_max=3, time_limit_s=5,
            entrenadores_reparto={1: entrenadores},
            con_entrenador={1: con_entrenador or set()},
        ))

    def _comprobar(self, r):
        pistas, cubiertas = r.franjas[1], r.cubiertas[1]
        for pista, miembros in pistas.items():
            if pista not in cubiertas:
                self.assertLessEqual(len(miembros), 2)
                vecinas = {pista - 1, pista + 1} & cubiertas
                self.assertTrue(vecinas, f"pista {pista} sin nadie al lado")
                self.assertTrue(any(len(pistas[v]) <= 2 for v in vecinas))
        return sum(len(m) for m in pistas.values())

    def test_con_un_entrenador_caben_cuatro_y_no_cinco(self):
        # Su pista con dos y la de al lado con dos; el quinto no cabe.
        self.assertEqual(self._comprobar(self._resolver(5, 1)), 4)

    def test_con_entrenador_puede_haber_tres(self):
        r = self._resolver(3, 1)
        self.assertEqual(self._comprobar(r), 3)
        self.assertEqual(len(r.cubiertas[1]), 1)

    def test_un_entrenador_no_vigila_a_dos(self):
        # Pistas 1-2-3 y un entrenador en la 2: vigila a una sola vecina.
        self.assertEqual(self._comprobar(self._resolver(6, 1, n_pistas=3)), 4)

    def test_sin_entrenadores_de_sobra_todo_cubierto(self):
        r = self._resolver(6, 2)
        self.assertEqual(self._comprobar(r), 6)

    def test_la_pista_del_contrato_lleva_entrenador(self):
        r = self._resolver(4, 1, con_entrenador={0})
        pista = next(p for p, m in r.franjas[1].items() if 0 in m)
        self.assertIn(pista, r.cubiertas[1])

    def test_quien_viene_por_uno_no_vigila_al_lado(self):
        # Dos pistas, dos «entrenadores»: el de la 1 viene solo por el 0. La 2,
        # con dos y sin vigilancia posible, tiene que llevar el otro.
        r = solve_pairing(PairingInput(
            players=[Player(id=0, division=1)] + [Player(id=i, division=6) for i in (1, 2)],
            courts=[Court(id=i, venue_id=1, capacity=3, number=i) for i in (1, 2)],
            franjas=[1], capacidad_max=3, time_limit_s=5,
            entrenadores_reparto={1: 1}, con_entrenador={1: {0}}, no_vigilan={1: {0}},
        ))
        # Con un solo entrenador no se abren las dos pistas: la del 0 no
        # puede vigilar a la otra.
        self.assertEqual(len(r.franjas[1]), 1)

    def test_el_atado_puede_ir_solo_aunque_no_haya_individuales(self):
        # Un D1 sin nadie de su nivel y su entrenador atado: va solo con él.
        r = solve_pairing(PairingInput(
            players=[Player(id=1, division=1), Player(id=2, division=6),
                     Player(id=3, division=6)],
            courts=[Court(id=i, venue_id=1, capacity=3, number=i) for i in (1, 2)],
            franjas=[1], capacidad_max=3, min_occupancy=2, time_limit_s=5,
            entrenadores_reparto={1: 2}, con_entrenador={1: {1}},
        ))
        self.assertEqual(sorted(len(m) for m in r.franjas[1].values()), [1, 2])


class CubrirConLosQueSobranTests(SimpleTestCase):
    """Si el motor deja una pista vigilada pero sobra un entrenador, se le
    pone: vigilada está bien, con entrenador está mejor."""

    def test_el_que_sobra_va_a_la_vigilada(self):
        from collections import Counter

        from .service import _emparejar_entrenadores

        uno, dos = _Ent(1), _Ent(2)
        asig, _ = _emparejar_entrenadores(
            {10: [100], 11: [101, 102]}, {}, [uno, dos], Counter(),
            info_pistas={10: (1, 1, 0), 11: (1, 2, 0)}, cubrir={11},
        )
        self.assertEqual(set(asig), {10, 11})


class PatronVigiladasYResinaTests(SimpleTestCase):
    """14/10/2026: en tierra, con entrenador la 1, 3, 4 y 6 y vigiladas la 2
    y la 5; en resina siempre hay algún entrenador; y quien cuida dos pistas
    va en el cuadrante con la que menos jugadores tiene."""

    def _resolver(self, pistas, n_jugadores, entrenadores, **kw):
        return solve_pairing(PairingInput(
            players=[Player(id=i, division=5) for i in range(n_jugadores)],
            courts=pistas, franjas=[1], capacidad_max=3, time_limit_s=5,
            entrenadores_reparto={1: entrenadores}, **kw,
        ))

    def test_con_cuatro_entrenadores_la_2_y_la_5_vigiladas(self):
        pistas = [Court(id=i, venue_id=1, capacity=3, number=i, surface="TIERRA")
                  for i in range(1, 7)]
        r = self._resolver(pistas, 12, 4, vigiladas_preferidas=frozenset({2, 5}),
                           w_vigilada_fuera=300)
        self.assertEqual(len(r.franjas[1]), 6)
        self.assertEqual(r.cubiertas[1], {1, 3, 4, 6})
        self.assertEqual(r.vigilancia[1], {2: r.vigilancia[1][2], 5: r.vigilancia[1][5]})

    def test_la_resina_no_la_vigila_la_tierra(self):
        pistas = [Court(id=6, venue_id=1, capacity=3, number=6, surface="TIERRA"),
                  Court(id=7, venue_id=1, capacity=3, number=7, surface="RESINA")]
        r = self._resolver(pistas, 4, 1, resina_con_entrenador=True)
        self.assertEqual(len(r.franjas[1]), 2)
        self.assertEqual(r.cubiertas[1], {7})

    def test_el_entrenador_va_con_la_pista_de_menos(self):
        from .service import _con_la_de_menos

        pistas = {1: [10, 11], 2: [12]}
        tierra = Court(id=0, venue_id=1, surface="TIERRA")
        por_id = {1: tierra, 2: tierra}
        entrenador_de = {1: 99}
        _con_la_de_menos(entrenador_de, pistas, {2: 1}, por_id, {}, {}, set())
        self.assertEqual(entrenador_de, {2: 99})
        # Con un veto en la pista de menos, se queda donde estaba.
        entrenador_de = {1: 99}
        _con_la_de_menos(entrenador_de, pistas, {2: 1}, por_id, {}, {12: {99}}, set())
        self.assertEqual(entrenador_de, {1: 99})


class AltosConEntrenadorYColorTests(SimpleTestCase):
    """16/10/2026: las pistas con D1-D2 son las últimas en quedarse sin
    entrenador (aunque eso rompa el patrón 1-3-4-6), y cada entrenador va
    preferentemente con los alumnos de su color, por encima de los
    porcentajes."""

    def test_la_pista_de_los_d1_lleva_el_entrenador_aunque_sea_la_2(self):
        # Dos pistas y un entrenador; la 2 es la que el patrón deja vigilada.
        # Los D1 solo caben en la 2 (en la 1 juega quien la pide en resina).
        pistas = [Court(id=1, venue_id=1, capacity=2, number=1, surface="RESINA"),
                  Court(id=2, venue_id=1, capacity=2, number=2, surface="TIERRA")]
        jugadores = ([Player(id=i, division=6, surface_pref="RESINA") for i in (1, 2)]
                     + [Player(id=i, division=1, surface_pref="TIERRA") for i in (3, 4)])
        datos = dict(players=jugadores, courts=pistas, franjas=[1], capacidad_max=2,
                     time_limit_s=5, entrenadores_reparto={1: 1},
                     vigiladas_preferidas=frozenset({2}), w_vigilada_fuera=300)
        sin = solve_pairing(PairingInput(**datos))
        con = solve_pairing(PairingInput(**datos, prioridad_cubrir={3, 4},
                                         w_cubrir_prioridad=800))
        self.assertEqual(sin.cubiertas[1], {1})
        self.assertEqual(con.cubiertas[1], {2})

    def test_el_color_gana_a_los_porcentajes(self):
        from collections import Counter

        from .service import _emparejar_entrenadores

        javi, mario = _Ent(1), _Ent(2)
        # El alumno 100 es de Blas (amarillo, como Javi), pero sus porcentajes
        # tiran hacia Mario (turquesa).
        asig, _ = _emparejar_entrenadores(
            {10: [100]}, {}, [javi, mario], Counter(),
            pesos={100: {2: 0.9, 1: 0.1}},
            responsable_de={100: 3}, color_de={1: "amarillo", 2: "turquesa", 3: "amarillo"},
        )
        self.assertEqual(asig, {10: 1})
        # Sin colores, mandan los porcentajes.
        asig, _ = _emparejar_entrenadores(
            {10: [100]}, {}, [javi, mario], Counter(), pesos={100: {2: 0.9, 1: 0.1}})
        self.assertEqual(asig, {10: 2})


class ColocarAntesQueCostesYForzarTests(SimpleTestCase):
    """16/10/2026: colocar a alguien vale más que todo lo que cuesta abrirle
    pista (Nik se quedaba fuera por no abrir una de resina); y si sin romper
    reglas alguien se queda fuera, se fuerza con el reparto que menos rompe
    (una pista D2-D4 en vez de dos D9 metidas con un D2 y un D4)."""

    PESOS = dict(w_assign=1000, w_central=100, w_court=900, w_resina=1200,
                 w_orden_pista=60, w_individual=1200, w_exceso_pistas=600,
                 w_density=15000, capacidad_max=2, time_limit_s=5, franjas=[1])

    def test_abre_la_de_resina_antes_que_dejar_a_alguien_fuera(self):
        pistas = [Court(id=1, venue_id=1, capacity=2, number=1, surface="TIERRA"),
                  Court(id=8, venue_id=1, capacity=2, number=8, surface="RESINA")]
        jugadores = [Player(id=1, division=5), Player(id=2, division=5),
                     Player(id=3, division=9)]
        r = solve_pairing(PairingInput(players=jugadores, courts=pistas,
                                       min_occupancy=1, pistas_objetivo={1: 1},
                                       **self.PESOS))
        self.assertEqual(r.unassigned, [])

    def test_forzar_elige_el_reparto_que_menos_rompe(self):
        pistas = [Court(id=i, venue_id=1, capacity=2, number=i, surface="TIERRA")
                  for i in (1, 2)]
        jugadores = [Player(id=1, division=2, edad=24), Player(id=2, division=4, edad=22),
                     Player(id=3, division=9, edad=16), Player(id=4, division=9, edad=13)]
        normal = solve_pairing(PairingInput(players=jugadores, courts=pistas,
                                            min_occupancy=1, **self.PESOS))
        self.assertTrue(normal.unassigned)
        forzado = solve_pairing(PairingInput(players=jugadores, courts=pistas,
                                             min_occupancy=1, forzar=True, **self.PESOS))
        self.assertEqual(forzado.unassigned, [])
        juntos = {frozenset(m) for m in forzado.franjas[1].values()}
        self.assertEqual(juntos, {frozenset({1, 2}), frozenset({3, 4})})

    def test_no_fuerza_solo_por_ahorrarse_una_pista(self):
        # Hay pistas para todos: un D2 y un D9 van cada uno a la suya.
        pistas = [Court(id=i, venue_id=1, capacity=2, number=i, surface="TIERRA")
                  for i in (1, 2)]
        r = solve_pairing(PairingInput(
            players=[Player(id=1, division=2), Player(id=2, division=9)],
            courts=pistas, min_occupancy=1, forzar=True, **self.PESOS))
        self.assertEqual(len(r.franjas[1]), 2)


class SoloLaDosYLaCincoSinEntrenadorTests(SimpleTestCase):
    """22/10/2026: en la tierra del Resort solo la 2 y la 5 se quedan sin
    entrenador; los satélites abiertos llevan uno; y si faltan, salen los del
    banquillo, pagando."""

    def _resolver(self, pistas, n_jugadores, entrenadores, banquillo=0, **kw):
        return solve_pairing(PairingInput(
            players=[Player(id=i, division=5) for i in range(n_jugadores)],
            courts=pistas, franjas=[1], capacidad_max=2, time_limit_s=5,
            entrenadores_reparto={1: entrenadores},
            vigiladas_preferidas=frozenset({2, 5}), vigiladas_estrictas=True,
            banquillo={1: banquillo}, w_banquillo=2000, **kw,
        ))

    def tierra(self, *numeros, venue=1, satelite=False):
        return [Court(id=venue * 100 + n, venue_id=venue, capacity=2, number=n,
                      surface="TIERRA", is_satellite=satelite) for n in numeros]

    def test_la_4_no_se_queda_sin_entrenador(self):
        # Dos entrenadores para las pistas 1-4: la 1 y la 3 con él, la 2
        # vigilada; la 4 no se puede abrir vigilada desde la 3.
        r = self._resolver(self.tierra(1, 2, 3, 4), 8, 2)
        abiertas = {c for c in r.franjas[1]}
        self.assertNotIn(104, abiertas - r.cubiertas[1])
        self.assertEqual(len(abiertas), 3)
        self.assertEqual(len(r.unassigned), 2)

    def test_si_faltan_sale_uno_del_banquillo(self):
        r = self._resolver(self.tierra(1, 2, 3, 4), 8, 2, banquillo=1)
        self.assertEqual(r.unassigned, [])
        self.assertEqual(r.cubiertas[1], {101, 103, 104})

    def test_el_banquillo_no_sale_si_no_hace_falta(self):
        r = self._resolver(self.tierra(1, 2, 3), 6, 2, banquillo=2)
        self.assertEqual(r.unassigned, [])
        self.assertEqual(r.cubiertas[1], {101, 103})

    def test_el_satelite_abierto_lleva_entrenador(self):
        pistas = self.tierra(1) + self.tierra(1, 2, venue=2, satelite=True)
        r = self._resolver(pistas, 6, 1, satelite_con_entrenador=True)
        # Un entrenador: o el Resort o Sta. Bárbara, no los dos.
        self.assertEqual(len(r.unassigned), 2)
        r = self._resolver(pistas, 6, 1, banquillo=1, satelite_con_entrenador=True)
        self.assertEqual(r.unassigned, [])
        self.assertEqual(len(r.cubiertas[1] & {201, 202}), 1)


class OrdenDelBanquilloTests(SimpleTestCase):
    """22/10/2026: cuando el motor manda cubrir más pistas que entrenadores del
    reparto, salen los del banquillo por su orden (Dani, Sergio, Iván,
    Jorge García), y antes uno fuera de su grupo que la pista sin nadie."""

    def _emparejar(self, courts, entrenadores, banquillo, orden, cubrir, divisiones,
                   tolerancia=None):
        from collections import Counter

        from .service import _emparejar_entrenadores

        return _emparejar_entrenadores(
            courts, {}, entrenadores, Counter(), divisiones=divisiones,
            solo_si_atado=banquillo, banquillo_orden=orden, cubrir=cubrir,
            tolerancia_division=tolerancia,
            info_pistas={p: (1, n, 0) for n, p in enumerate(courts, start=1)})

    def test_salen_por_su_orden(self):
        asig, _ = self._emparejar(
            {10: [1], 11: [2], 12: [3]},
            [_Ent(100), _Ent(201), _Ent(202), _Ent(203)],
            banquillo={201, 202, 203}, orden={202: 1, 201: 2, 203: 3},
            cubrir={10, 12}, divisiones={})
        self.assertEqual(set(asig.values()), {100, 202})

    def test_sin_cubrir_no_salen(self):
        asig, _ = self._emparejar(
            {10: [1], 11: [2]}, [_Ent(100), _Ent(201)],
            banquillo={201}, orden={201: 1}, cubrir={10}, divisiones={})
        self.assertEqual(asig, {10: 100})

    def test_antes_fuera_de_su_grupo_que_sin_nadie(self):
        # La resina con D9 y solo Dani (grupo 1-2) libre: la lleva él.
        asig, _ = self._emparejar(
            {10: [1]}, [_EntGrupo(100, 1, 2), _EntGrupo(101, 4, 9)],
            banquillo={100}, orden={100: 1}, cubrir={10}, divisiones={1: 9},
            tolerancia=2)
        self.assertEqual(asig, {10: 101})
        asig, _ = self._emparejar(
            {10: [1], 11: [2]}, [_EntGrupo(100, 1, 2), _EntGrupo(101, 4, 9)],
            banquillo={100}, orden={100: 1}, cubrir={10, 11},
            divisiones={1: 9, 2: 9}, tolerancia=2)
        self.assertEqual(set(asig.values()), {100, 101})

    def test_antes_uno_del_reparto_fuera_de_su_grupo_que_el_banquillo(self):
        # 100 (grupo 7-9) no encaja con D2; 200, del banquillo y del 1-3, sí;
        # pero no faltan entrenadores, así que no sale.
        asig, _ = self._emparejar(
            {10: [1]}, [_EntGrupo(100, 7, 9), _EntGrupo(200, 1, 3)],
            banquillo={200}, orden={200: 1}, cubrir={10}, divisiones={1: 2},
            tolerancia=2)
        self.assertEqual(asig, {10: 100})

    def test_el_orden_manda_sobre_el_grupo(self):
        # Hace falta uno del banquillo para la pista de D6: sale Sergio (1º, grupo
        # 1-3) aunque a Iván (2º, grupo 1-4) le encaje mejor.
        asig, _ = self._emparejar(
            {10: [1]}, [_EntGrupo(200, 1, 3), _EntGrupo(300, 1, 4)],
            banquillo={200, 300}, orden={200: 1, 300: 2}, cubrir={10},
            divisiones={1: 6}, tolerancia=2)
        self.assertEqual(asig, {10: 200})


class DirectivaArribaYColoresTests(SimpleTestCase):
    """22/10/2026: la directiva (los del banquillo) entrena a las divisiones más
    altas y nunca va a la resina o a otra sede si otro puede ir; y el
    entrenador se elige por escalones: color, grupo, porcentajes."""

    def _emparejar(self, courts, entrenadores, cubrir, divisiones, info,
                   banquillo=frozenset(), orden=None, **kw):
        from collections import Counter

        from .service import _emparejar_entrenadores

        return _emparejar_entrenadores(
            courts, {}, entrenadores, Counter(), divisiones=divisiones,
            solo_si_atado=banquillo, banquillo_orden=orden or {}, cubrir=cubrir,
            info_pistas=info, **kw)

    def test_la_directiva_a_la_pista_de_los_mejores(self):
        # 100 lleva el grupo 1-3 y encajaría mejor con el D1; aun así va Dani
        # (directiva) arriba y 100 baja a la de D5.
        asig, _ = self._emparejar(
            {10: [1], 11: [2]}, [_EntGrupo(100, 1, 3), _EntGrupo(200, 1, 2)],
            cubrir={10, 11}, divisiones={1: 1, 2: 5},
            info={10: (1, 1, 0), 11: (1, 3, 0)}, banquillo={200}, orden={200: 1})
        self.assertEqual(asig, {10: 200, 11: 100})

    def test_a_la_resina_va_otro(self):
        asig, _ = self._emparejar(
            {10: [1], 12: [2]}, [_Ent(100), _Ent(200)],
            cubrir={10, 12}, divisiones={1: 6, 2: 9},
            info={10: (1, 4, 0), 12: (1, 7, 0)}, banquillo={200}, orden={200: 1},
            fuera_del_resort={12})
        self.assertEqual(asig, {10: 200, 12: 100})

    def test_el_color_manda_sobre_el_grupo_y_los_porcentajes(self):
        # El D3 es del bloque turquesa (su responsable es 101) y el D6, del
        # amarillo: el color pesa más que el grupo de cada uno y que los
        # porcentajes, que tiran al revés.
        asig, _ = self._emparejar(
            {10: [1], 11: [2]}, [_EntGrupo(100, 1, 3), _EntGrupo(101, 4, 6)],
            cubrir={10, 11}, divisiones={1: 3, 2: 6},
            info={10: (1, 1, 0), 11: (1, 3, 0)},
            responsable_de={1: 101, 2: 100},
            color_de={100: "amarillo", 101: "turquesa"},
            pesos={1: {100: 1.0}, 2: {101: 1.0}}, peso_division=1000)
        self.assertEqual(asig, {10: 101, 11: 100})

    def test_el_solver_junta_por_colores(self):
        colores = {0: "amarillo", 1: "turquesa", 2: "amarillo", 3: "turquesa"}
        r = solve_pairing(PairingInput(
            players=[Player(id=i, division=5) for i in range(4)],
            courts=[Court(id=n, venue_id=1, capacity=2, number=n, surface="TIERRA")
                    for n in (1, 3)],
            franjas=[1], capacidad_max=2, time_limit_s=5,
            entrenadores_reparto={1: 2}, vigiladas_preferidas=frozenset({2, 5}),
            vigiladas_estrictas=True,
            clases_entrenador={1: {"amarillo": 1, "turquesa": 1}},
            color_jugador=colores, w_fuera_color=300,
        ))
        self.assertEqual(r.unassigned, [])
        for miembros in r.franjas[1].values():
            self.assertEqual(len({colores[j] for j in miembros}), 1)

    def test_el_solver_deja_la_directiva_arriba(self):
        r = solve_pairing(PairingInput(
            players=[Player(id=i, division=d) for i, d in enumerate((5, 5, 2, 2))],
            courts=[Court(id=n, venue_id=1, capacity=2, number=n, surface="TIERRA")
                    for n in (1, 3)],
            franjas=[1], capacidad_max=2, time_limit_s=5,
            entrenadores_reparto={1: 1}, vigiladas_preferidas=frozenset({2, 5}),
            vigiladas_estrictas=True, banquillo={1: 1}, w_banquillo=2000,
            clases_entrenador={1: {"turquesa": 1}},
            color_jugador={0: "turquesa", 1: "turquesa", 2: "amarillo", 3: "amarillo"},
            w_fuera_color=300, w_directiva_division=150,
        ))
        self.assertEqual(r.unassigned, [])
        # Los dos turquesa (D5) con su entrenador y los D2, amarillos sin
        # entrenador de su color, juntos con la directiva.
        self.assertIn(sorted(next(iter(r.franjas[1].values()))), ([0, 1], [2, 3]))
        self.assertEqual(len(r.franjas[1]), 2)


class CompactarFranjaTests(SimpleTestCase):
    """22/10/2026: si reemparejando a los de una franja salen menos pistas, se
    compacta: el solver, con poco tiempo, dejaba individuales que podían ir
    juntos o parejas que, cambiadas, dejaban a todos de dos en dos."""

    class _Cfg:
        peso_pareja, peso_repeticion = 5000, 50

    def _tierra(self, *numeros):
        return {n: Court(id=n, venue_id=1, capacity=2, number=n, surface="TIERRA")
                for n in numeros}

    def _compactar(self, grupos, por_id, courts, cubiertas=None, vigilancia=None,
                   intocables=(), con_entrenador=(), pairs_hard=(), vetoes=(),
                   pairs_soft=(), finos=None):
        from .service import _compactar_franja, puntos_pareja

        reglas = PairingInput(players=[], courts=[], vetoes=set(vetoes))

        def puntos(a, b, misma=False):
            return puntos_pareja(a, b, finos or {}, set(pairs_soft), {}, {}, self._Cfg(), misma)

        return _compactar_franja(
            grupos, cubiertas, vigilancia or {}, set(intocables), por_id, courts,
            reglas, set(con_entrenador), set(pairs_hard), puntos,
            lambda j: (finos or {}).get(j))

    def test_dos_individuales_compatibles_se_juntan(self):
        por_id = {1: Player(id=1, division=5), 2: Player(id=2, division=5),
                  3: Player(id=3, division=9), 4: Player(id=4, division=9)}
        courts = self._tierra(1, 2, 3)
        res = self._compactar({1: [1], 3: [2], 2: [3, 4]}, por_id, courts,
                              cubiertas={1, 3}, vigilancia={2: 1})
        grupos, cub, vig, cerradas = res
        self.assertEqual(cerradas, 1)
        self.assertEqual(sorted(sorted(m) for m in grupos.values()), [[1, 2], [3, 4]])
        # Los D5 (mejores) en la 1, cubierta; la 2 sigue vigilada por la 1.
        self.assertEqual(grupos[1], [1, 2])
        self.assertEqual((cub, vig), ({1}, {2: 1}))

    def test_cambia_una_pareja_para_que_todos_vayan_de_dos(self):
        # (Vicent D4, Marc D3) + Nazim D5 solo + Enzo D3 solo → (Vicent, Nazim)
        # y (Marc, Enzo): una pista menos.
        por_id = {1: Player(id=1, division=4), 2: Player(id=2, division=3),
                  3: Player(id=3, division=5), 4: Player(id=4, division=3)}
        courts = self._tierra(1, 3, 7)
        courts[7] = Court(id=7, venue_id=1, capacity=2, number=7, surface="RESINA")
        res = self._compactar({7: [1, 2], 1: [3], 3: [4]}, por_id, courts,
                              cubiertas={1, 3, 7})
        grupos, cub, _vig, cerradas = res
        self.assertEqual(cerradas, 1)
        self.assertEqual(sorted(sorted(m) for m in grupos.values()), [[1, 3], [2, 4]])
        self.assertNotIn(7, grupos)  # se cierra la resina, la última
        self.assertEqual(cub, {1, 3})

    def test_individuales_incompatibles_se_quedan(self):
        por_id = {1: Player(id=1, division=2), 2: Player(id=2, division=7)}
        self.assertIsNone(self._compactar({1: [1], 3: [2]}, por_id, self._tierra(1, 3),
                                          cubiertas={1, 3}))

    def test_si_se_cierra_la_que_vigilaba_la_vecina_la_vigila_otra_o_lleva_entrenador(self):
        por_id = {1: Player(id=1, division=5), 2: Player(id=2, division=5),
                  3: Player(id=3, division=7), 4: Player(id=4, division=7)}
        courts = self._tierra(1, 2, 3)
        # La 3 (cubierta, con un D5) vigila a la 2; la 1 (cubierta) lleva al otro D5.
        res = self._compactar({1: [1], 3: [2], 2: [3, 4]}, por_id, courts,
                              cubiertas={1, 3}, vigilancia={2: 3})
        grupos, cub, vig, _n = res
        self.assertEqual(set(grupos), {1, 2})
        self.assertEqual((cub, vig), ({1}, {2: 1}))
        # Sin otra vecina con entrenador, la vigilada pasa a llevarlo ella (y
        # no hacen falta más entrenadores que antes: dos).
        courts = self._tierra(1, 4, 5)
        res = self._compactar({1: [1], 5: [2], 4: [3, 4]}, por_id, courts,
                              cubiertas={1, 5}, vigilancia={4: 5})
        grupos, cub, vig, _n = res
        self.assertEqual(set(grupos), {1, 4})
        self.assertEqual((cub, vig), ({1, 4}, {}))

    def test_no_toca_la_pareja_obligatoria_ni_la_pista_del_dedicado(self):
        por_id = {i: Player(id=i, division=5) for i in range(1, 6)}
        courts = self._tierra(1, 2, 3, 4)
        res = self._compactar({1: [1], 2: [2], 3: [3], 4: [4, 5]}, por_id, courts,
                              cubiertas={1, 3, 4}, vigilancia={2: 1},
                              intocables={1}, pairs_hard={frozenset((4, 5))})
        grupos, _cub, _vig, cerradas = res
        self.assertEqual(cerradas, 1)
        self.assertEqual(grupos[1], [1])
        self.assertEqual(grupos[4], [4, 5])
        self.assertEqual(sorted(m for m in grupos.values() if len(m) == 2), [[2, 3], [4, 5]])

    def test_una_rencilla_no_se_junta(self):
        por_id = {1: Player(id=1, division=5), 2: Player(id=2, division=5)}
        self.assertIsNone(self._compactar({1: [1], 3: [2]}, por_id, self._tierra(1, 3),
                                          cubiertas={1, 3}, vetoes={(1, 2)}))

    def test_emparejamiento_maximo(self):
        from .pairing import emparejamiento_maximo

        ps = [Player(id=1, division=2), Player(id=2, division=3),
              Player(id=3, division=4), Player(id=4, division=9)]
        data = PairingInput(players=ps, courts=[])
        parejas = emparejamiento_maximo(ps, data)
        self.assertEqual(len(parejas), 1)
        # A igual número, manda el peso: con 2 y 3 juntos, 1 se queda solo.
        parejas = emparejamiento_maximo(ps, data, {frozenset((2, 3)): 10})
        self.assertEqual(parejas, [frozenset((2, 3))])

    def test_a_igual_numero_de_pistas_deshace_una_pareja_forzada(self):
        # (D3, D9) forzados + D3 solo + D9 solo → (D3, D3) y (D9, D9).
        por_id = {1: Player(id=1, division=3), 2: Player(id=2, division=9),
                  3: Player(id=3, division=3), 4: Player(id=4, division=9)}
        courts = self._tierra(1, 3, 4)
        res = self._compactar({1: [1, 2], 3: [3], 4: [4]}, por_id, courts,
                              cubiertas={1, 3, 4})
        grupos, _cub, _vig, cerradas = res
        self.assertEqual(cerradas, 1)
        self.assertEqual(sorted(sorted(m) for m in grupos.values()), [[1, 3], [2, 4]])
        # Y sin ahorrar pista tampoco: (D3, D9) forzados + (D3, D9) forzados.
        res = self._compactar({1: [1, 2], 3: [3, 4]}, por_id, courts, cubiertas={1, 3})
        grupos, _cub, _vig, cerradas = res
        self.assertEqual(cerradas, 0)
        self.assertEqual(sorted(sorted(m) for m in grupos.values()), [[1, 3], [2, 4]])



class RankingEnLasParejasTests(SimpleTestCase):
    """27/10/2026: el ranking dentro de cada división es preferencia al hacer
    las parejas: por delante de no repetir y del color, por detrás de una
    pareja declarada; nunca abre pista ni deja a nadie fuera."""

    class _Cfg:
        peso_pareja, peso_repeticion = 5000, 50

    def puntos(self, a, b, finos=None, declaradas=(), recent=None, colores=None):
        from .service import puntos_pareja

        return puntos_pareja(a, b, finos or {}, set(declaradas), recent or {},
                             colores or {}, self._Cfg())

    def test_mas_cerca_en_el_ranking_vale_mas(self):
        a, b, c = (Player(id=i, division=5) for i in (1, 2, 3))
        finos = {1: 5.05, 2: 5.15, 3: 5.95}
        self.assertGreater(self.puntos(a, b, finos), self.puntos(a, c, finos))

    def test_el_ultimo_de_d2_y_el_primero_de_d3_estan_pegados(self):
        ultimo_d2, primero_d3, primero_d2 = (Player(id=1, division=2), Player(id=2, division=3),
                                             Player(id=3, division=2))
        finos = {1: 2.95, 2: 3.05, 3: 2.05}
        self.assertGreater(self.puntos(ultimo_d2, primero_d3, finos),
                           self.puntos(ultimo_d2, primero_d2, finos))

    def test_escalones(self):
        a, b, c = (Player(id=i, division=5) for i in (1, 2, 3))
        finos = {1: 5.1, 2: 5.2, 3: 5.9}
        # La pareja declarada gana al ranking.
        self.assertGreater(self.puntos(a, c, finos, declaradas={frozenset((1, 3))}),
                           self.puntos(a, b, finos))
        # El ranking gana a no repetir (cuatro veces) y al color.
        self.assertGreater(self.puntos(a, b, finos, recent={frozenset((1, 2)): 4}),
                           self.puntos(a, c, finos, colores={1: "x", 3: "x"}))

    def test_preferencia_hacia_arriba(self):
        d3 = Player(id=1, division=3, division_pref=-1)
        d2, d4 = Player(id=2, division=2), Player(id=3, division=4)
        self.assertGreater(self.puntos(d3, d2), self.puntos(d3, d4))

    def test_el_repaso_de_la_manana_junta_por_ranking(self):
        from .service import _compactar_franja, puntos_pareja

        por_id = {i: Player(id=i, division=5) for i in range(1, 5)}
        finos = {1: 5.125, 2: 5.375, 3: 5.625, 4: 5.875}
        courts = {n: Court(id=n, venue_id=1, capacity=2, number=n, surface="TIERRA")
                  for n in (1, 3)}

        def puntos(a, b, misma=False):
            return puntos_pareja(a, b, finos, set(), {}, {}, self._Cfg(), misma)

        res = _compactar_franja({1: [1, 4], 3: [2, 3]}, {1, 3}, {}, set(), por_id, courts,
                                PairingInput(players=[], courts=[]), set(), set(), puntos,
                                finos.get)
        grupos, cub, _vig, cerradas = res
        self.assertEqual(cerradas, 0)
        self.assertEqual((grupos[1], grupos[3]), ([1, 2], [3, 4]))
        self.assertEqual(cub, {1, 3})

    def test_con_impares_el_ranking_decide_quien_va_solo(self):
        from .service import _compactar_franja, puntos_pareja

        # El último de D2 (2,9), el primero de D3 (3,1) y el último de D3
        # (3,9): con ranking van juntos los dos primeros; sin él, los D3.
        por_id = {1: Player(id=1, division=2), 2: Player(id=2, division=3),
                  3: Player(id=3, division=3)}
        courts = {n: Court(id=n, venue_id=1, capacity=2, number=n, surface="TIERRA")
                  for n in (1, 3)}
        for finos, juntos in (({1: 2.9, 2: 3.1, 3: 3.9}, [1, 2]), ({}, [2, 3])):
            def puntos(a, b, misma=False, finos=finos):
                return puntos_pareja(a, b, finos, set(), {}, {}, self._Cfg(), misma)

            res = _compactar_franja({1: [1], 3: [2, 3]}, {1, 3}, {}, set(), por_id, courts,
                                    PairingInput(players=[], courts=[]), set(), set(), puntos,
                                    finos.get)
            grupos = res[0] if res else {1: [1], 3: [2, 3]}
            self.assertIn(juntos, [sorted(m) for m in grupos.values()], finos)

    def test_la_tarde_cambia_de_pista_para_juntar_por_ranking(self):
        from .service import _afinar_franja, puntos_pareja

        por_id = {i: Player(id=i, division=5) for i in range(1, 7)}
        finos = {i: 5 + (i - 0.5) / 6 for i in range(1, 7)}
        courts = {n: Court(id=n, venue_id=1, capacity=3, number=n, surface="TIERRA")
                  for n in (1, 2)}

        def puntos(a, b, misma=False):
            return puntos_pareja(a, b, finos, set(), {}, {}, self._Cfg(), misma)

        res = _afinar_franja({1: [1, 5, 6], 2: [2, 3, 4]}, set(), por_id, courts,
                             PairingInput(players=[], courts=[]), set(), {1, 2}, set(), puntos)
        self.assertEqual({tuple(sorted(m)) for m in res.values()}, {(1, 2, 3), (4, 5, 6)})
        # Cada pista sigue con tres.
        self.assertEqual([len(m) for m in res.values()], [3, 3])
