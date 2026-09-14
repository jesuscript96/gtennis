"""Reglas de la ficha del alumno que el motor tiene que respetar.

Run: python manage.py test academy
"""
from datetime import date, time

from django.test import SimpleTestCase, TestCase

from academy.models import Jugador, Turno
from engine.service import _available_players
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
