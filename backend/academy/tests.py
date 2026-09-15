"""Reglas de la ficha del alumno que el motor tiene que respetar.

Run: python manage.py test academy
"""
from datetime import date, time

from django.test import SimpleTestCase, TestCase

from academy.models import Entrenador, HorarioJugador, Jugador, Turno
from engine.service import _available_players, entrenador_en_franja
from scheduling.models import Semana

LUNES = date(2026, 9, 14)


class EnAltaTests(SimpleTestCase):
    """El alta a mitad de mes: "entra el 16" quiere decir el 16, no el 1."""

    def test_sin_fechas_entrena_siempre(self):
        self.assertTrue(Jugador(nombre="X").en_alta(LUNES))

    def test_antes_de_su_alta_no(self):
        j = Jugador(nombre="X", fecha_alta=date(2026, 9, 16))
        self.assertFalse(j.en_alta(date(2026, 9, 15)))

    def test_el_dia_del_alta_ya_si(self):
        j = Jugador(nombre="X", fecha_alta=date(2026, 9, 16))
        self.assertTrue(j.en_alta(date(2026, 9, 16)))

    def test_despues_de_su_baja_no(self):
        j = Jugador(nombre="X", fecha_baja=date(2026, 9, 16))
        self.assertTrue(j.en_alta(date(2026, 9, 16)))
        self.assertFalse(j.en_alta(date(2026, 9, 17)))


class MotorRespetaElAltaTests(TestCase):
    """Lo mismo, pero donde importa: el alumno no puede salir en el cuadrante
    de un día en el que todavía no había empezado."""

    def setUp(self):
        # Las migraciones ya dejan sembrados los turnos del curso: se reusa el
        # que haya en vez de crear uno que choque con el código único.
        self.turno, _ = Turno.objects.get_or_create(
            codigo="M1",
            defaults={
                "nombre": "Mañana 1", "bloque": Turno.Bloque.MANANA,
                "hora_inicio": time(8, 30), "hora_fin": time(10, 0), "orden": 1,
            },
        )
        self.semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)
        # Cupo semanal holgado a propósito: el motor frena a quien ya lleva su
        # dosis, y ese freno depende del pk. Sin esto el test pasaría o fallaría
        # según qué id le tocara al alumno, que no es lo que se está midiendo.
        self.nuevo = Jugador.objects.create(
            nombre="Alta el 16", activo=True, fecha_alta=date(2026, 9, 16),
            sesiones_semana=10,
        )
        self.veterano = Jugador.objects.create(
            nombre="De siempre", activo=True, sesiones_semana=10,
        )

    def _ids(self, dia):
        # `idx_dia` es el día que va de la semana: sin él, el freno de ritmo
        # semanal deja fuera a media plantilla y el test mediría otra cosa.
        return [
            p.id for p in _available_players(
                self.semana, dia, self.turno, {}, idx_dia=dia,
            )
        ]

    def test_no_sale_antes_de_su_alta(self):
        self.assertNotIn(self.nuevo.id, self._ids(0))  # lunes 14
        self.assertNotIn(self.nuevo.id, self._ids(1))  # martes 15

    def test_entra_el_dia_de_su_alta(self):
        self.assertIn(self.nuevo.id, self._ids(2))     # miércoles 16

    def test_a_los_demas_no_les_afecta(self):
        self.assertIn(self.veterano.id, self._ids(0))


class FranjaDelEntrenadorTests(SimpleTestCase):
    """El entrenador declara franja igual que el alumno; sin declararla entra
    en cualquiera, que es lo que hace la academia."""

    def setUp(self):
        self.m1 = Turno(id=1, codigo="M1", bloque=Turno.Bloque.MANANA)
        self.m2 = Turno(id=2, codigo="M2", bloque=Turno.Bloque.MANANA)
        self.t1 = Turno(id=3, codigo="T1", bloque=Turno.Bloque.TARDE)

    def test_sin_declarar_entra_en_todas(self):
        e = Entrenador(nombre="X")
        self.assertTrue(entrenador_en_franja(e, self.m1))
        self.assertTrue(entrenador_en_franja(e, self.m2))
        self.assertTrue(entrenador_en_franja(e, self.t1))

    def test_con_franja_solo_esa(self):
        e = Entrenador(nombre="X", turno_manana_id=2)
        self.assertFalse(entrenador_en_franja(e, self.m1))
        self.assertTrue(entrenador_en_franja(e, self.m2))

    def test_la_manana_no_condiciona_la_tarde(self):
        # Declarar M2 no le saca de las tardes: cada bloque va por su cuenta.
        e = Entrenador(nombre="X", turno_manana_id=2)
        self.assertTrue(entrenador_en_franja(e, self.t1))


class DiaDistintoTests(TestCase):
    """Cada bloque de un día tiene tres respuestas. «El martes por la tarde no»
    no puede sacarle también de las mañanas del martes, que es lo que pasaba
    cuando un turno vacío valía por «no entrena»."""

    FRANJAS = {
        "M1": (Turno.Bloque.MANANA, time(8, 30), time(10, 0), 1),
        "M2": (Turno.Bloque.MANANA, time(10, 30), time(12, 30), 2),
        "T1": (Turno.Bloque.TARDE, time(14, 15), time(15, 30), 4),
        "T2": (Turno.Bloque.TARDE, time(15, 30), time(17, 30), 5),
    }

    def setUp(self):
        self.turnos = {}
        for codigo, (bloque, ini, fin, orden) in self.FRANJAS.items():
            self.turnos[codigo], _ = Turno.objects.get_or_create(
                codigo=codigo,
                defaults={"nombre": codigo, "bloque": bloque, "hora_inicio": ini,
                          "hora_fin": fin, "orden": orden},
            )
        self.semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)
        self.jug = Jugador.objects.create(
            nombre="Sin franja fija", activo=True, sesiones_semana=10,
        )

    def _donde(self, dia):
        mapa = {
            (h.jugador_id, h.dia): (h.turno_manana_id, h.turno_tarde_id,
                                    h.entrena_manana, h.entrena_tarde)
            for h in HorarioJugador.objects.all()
        }
        return {
            codigo for codigo, t in self.turnos.items()
            if any(p.id == self.jug.id for p in _available_players(
                self.semana, dia, t, {}, idx_dia=dia, horario=mapa))
        }

    def test_la_tarde_no_deja_las_mananas_como_estaban(self):
        HorarioJugador.objects.create(jugador=self.jug, dia=1, entrena_tarde=False)
        self.assertEqual(self._donde(1), {"M1", "M2"})

    def test_no_entrena_ese_dia(self):
        HorarioJugador.objects.create(
            jugador=self.jug, dia=1, entrena_manana=False, entrena_tarde=False,
        )
        self.assertEqual(self._donde(1), set())

    def test_franja_concreta_por_la_manana_y_tarde_no(self):
        HorarioJugador.objects.create(
            jugador=self.jug, dia=1, turno_manana=self.turnos["M2"],
            entrena_tarde=False,
        )
        self.assertEqual(self._donde(1), {"M2"})

    def test_el_resto_de_dias_no_cambian(self):
        HorarioJugador.objects.create(jugador=self.jug, dia=1, entrena_tarde=False)
        self.assertEqual(self._donde(3), {"M1", "M2", "T1", "T2"})
