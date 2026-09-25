"""Pure-engine tests (no DB). Run: python manage.py test engine"""
from django.test import SimpleTestCase

from .pairing import Court, PairingInput, Player, solve_pairing
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
