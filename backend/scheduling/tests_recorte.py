"""Quitar solo unos días de una falta (20/10/2026). Run: python manage.py test scheduling"""
from datetime import date, datetime, time
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from academy.models import Coach, Entrenador, Jugador, PreferenciaSuperficie
from scheduling.models import AusenciaJugador
from users.models import User

LUNES = date(2026, 9, 14)
SABADO = date(2026, 9, 19)


def reloj(fecha, hora):
    return mock.patch("django.utils.timezone.now", return_value=timezone.make_aware(
        datetime.combine(fecha, time(hora))))


class QuitarDiasTests(TestCase):
    """Torneo del lunes al sábado del que vuelve antes: se quitan solo los
    días que ya no valen, no la falta entera."""

    def setUp(self):
        self.u_victor = User.objects.create_user(username="victor", password="x")
        self.victor = Entrenador.objects.create(nombre="Víctor", user=self.u_victor)
        self.carlos = Jugador.objects.create(nombre="Carlos", entrenador_responsable=self.victor)
        self.api = APIClient()
        self.api.force_authenticate(self.u_victor)
        with reloj(date(2026, 9, 10), 12):
            r = self.api.post("/api/ausencias-fechas/", {
                "jugador": self.carlos.id, "fecha_inicio": "2026-09-14",
                "fecha_fin": "2026-09-19", "ambito": "DIA", "estado": "EN_TORNEO",
                "nota": "Torneo en Murcia",
            }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.falta = AusenciaJugador.objects.get()

    def _quitar(self, desde, hasta=None, usuario=None):
        if usuario:
            self.api.force_authenticate(usuario)
        cuerpo = {"desde": desde, **({"hasta": hasta} if hasta else {})}
        with reloj(LUNES, 12):
            return self.api.post(
                f"/api/ausencias-fechas/{self.falta.id}/quitar_dias/", cuerpo, format="json")

    def _rangos(self):
        return list(AusenciaJugador.objects.order_by("fecha_inicio")
                    .values_list("fecha_inicio", "fecha_fin"))

    def test_ha_vuelto_el_miercoles_se_queda_lunes_y_martes(self):
        r = self._quitar("2026-09-16")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._rangos(), [(LUNES, date(2026, 9, 15))])
        self.assertEqual(len(r.json()["quedan"]), 1)

    def test_un_dia_en_medio_parte_la_falta_en_dos(self):
        r = self._quitar("2026-09-16", "2026-09-17")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._rangos(), [
            (LUNES, date(2026, 9, 15)), (date(2026, 9, 18), SABADO)])
        # La parte de detrás sigue siendo lo que se declaró, cuando se declaró.
        detras = AusenciaJugador.objects.get(fecha_inicio=date(2026, 9, 18))
        self.assertEqual(detras.estado, "EN_TORNEO")
        self.assertEqual(detras.nota, "Torneo en Murcia")
        self.assertEqual(detras.declarada_por, self.victor)
        self.assertEqual(detras.created_at, self.falta.created_at)
        self.assertFalse(detras.tardia)

    def test_al_principio_la_acorta_por_delante(self):
        self._quitar("2026-09-14", "2026-09-15")
        self.assertEqual(self._rangos(), [(date(2026, 9, 16), SABADO)])

    def test_todos_sus_dias_la_quitan_entera(self):
        r = self._quitar("2026-09-10", "2026-09-25")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["quedan"], [])
        self.assertFalse(AusenciaJugador.objects.exists())

    def test_dias_fuera_de_la_falta_no_tocan_nada(self):
        r = self._quitar("2026-09-21", "2026-09-22")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._rangos(), [(LUNES, SABADO)])

    def test_un_coach_que_no_le_ve_no_puede(self):
        otro = User.objects.create_user(username="pablo", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Pablo", user=otro)
        r = self._quitar("2026-09-16", usuario=otro)
        self.assertIn(r.status_code, (403, 404))
        self.assertEqual(self._rangos(), [(LUNES, SABADO)])

    def test_superficie_por_fechas_igual(self):
        pref = PreferenciaSuperficie.objects.create(
            jugador=self.carlos, superficie="RESINA",
            fecha_desde=LUNES, fecha_hasta=SABADO)
        r = self.api.post(f"/api/preferencias-superficie/{pref.id}/quitar_dias/",
                          {"desde": "2026-09-16", "hasta": "2026-09-16"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(
            list(PreferenciaSuperficie.objects.order_by("fecha_desde")
                 .values_list("fecha_desde", "fecha_hasta")),
            [(LUNES, date(2026, 9, 15)), (date(2026, 9, 17), SABADO)])
