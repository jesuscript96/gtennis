"""El corte del día siguiente (01/10/2026). Run: python manage.py test scheduling"""
from datetime import date, datetime, time
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from academy.models import Aviso, Coach, Entrenador, Jugador, Pista, Sede, Turno
from scheduling.corte import corte, dia_a_generar
from scheduling.models import (
    Asignacion, AusenciaJugador, GeneracionProgramada, Semana,
)
from users.models import User

LUNES = date(2026, 9, 14)
MARTES = date(2026, 9, 15)


def a_las(fecha, hora, minuto=0):
    return timezone.make_aware(datetime.combine(fecha, time(hora, minuto)))


def reloj(momento):
    return mock.patch("django.utils.timezone.now", return_value=momento)


class CorteTests(TestCase):
    def test_a_las_siete_del_dia_anterior_y_el_sabado_el_viernes_a_las_cuatro_y_media(self):
        self.assertEqual(corte(MARTES), a_las(LUNES, 19))
        sabado = date(2026, 9, 19)
        self.assertEqual(corte(sabado), a_las(date(2026, 9, 18), 16, 30))

    def test_que_dia_toca_generar(self):
        self.assertIsNone(dia_a_generar(a_las(LUNES, 18, 59)))
        self.assertEqual(dia_a_generar(a_las(LUNES, 19)), MARTES)
        self.assertEqual(dia_a_generar(a_las(date(2026, 9, 18), 16, 30)), date(2026, 9, 19))
        # El sábado por la tarde no hay nada que generar: el domingo no se entrena.
        self.assertIsNone(dia_a_generar(a_las(date(2026, 9, 19), 19)))


class FaltaTrasElCorteTests(TestCase):
    """Pasado el corte, una falta no toca el cuadrante: queda tardía, el
    jugador sale tachado y se avisa a quien puede verle."""

    def setUp(self):
        Sede.objects.update(activa=False)
        sede = Sede.objects.create(nombre="Prueba", densidad_default=2,
                                   densidad_max=2, activa=True)
        pista = Pista.objects.create(sede=sede, numero=1, superficie="TIERRA")
        self.m1, _ = Turno.objects.get_or_create(
            codigo="M1", defaults={"nombre": "M1", "bloque": Turno.Bloque.MANANA,
                                   "hora_inicio": time(8, 30), "hora_fin": time(10, 0), "orden": 1})
        self.semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)

        self.u_victor = User.objects.create_user(username="victor", password="x")
        self.victor = Entrenador.objects.create(nombre="Víctor", user=self.u_victor)
        self.u_blas = User.objects.create_user(username="blas", password="x")
        self.blas = Entrenador.objects.create(nombre="Blas", user=self.u_blas)
        self.u_dani = User.objects.create_user(
            username="dani", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Dani", user=self.u_dani).entrenadores.add(
            self.victor, self.blas)
        self.u_pablo = User.objects.create_user(
            username="pablo", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Pablo", user=self.u_pablo)  # otro grupo
        self.u_ivan = User.objects.create_user(
            username="ivan", password="x", role=User.Role.SUPERADMIN)

        self.carlos = Jugador.objects.create(nombre="Carlos", entrenador_responsable=self.victor)
        self.asig = Asignacion.objects.create(
            semana=self.semana, dia=1, turno=self.m1, pista=pista,
            jugador=self.carlos, entrenador=self.blas)
        self.api = APIClient()
        self.api.force_authenticate(self.u_victor)

    def _falta(self):
        return self.api.post("/api/ausencias-fechas/", {
            "jugador": self.carlos.id, "fecha_inicio": "2026-09-15",
            "fecha_fin": "2026-09-15", "ambito": "DIA", "estado": "AUSENCIA_JUGADOR",
            "subtipo": "ESTUDIOS",
        }, format="json")

    def test_antes_del_corte_no_avisa(self):
        with reloj(a_las(LUNES, 18)):
            r = self._falta()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertFalse(r.json()["tardia"])
        self.assertFalse(Aviso.objects.exists())

    def test_despues_del_corte_avisa_y_no_mueve_a_nadie(self):
        with reloj(a_las(LUNES, 21, 40)):
            r = self._falta()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.json()["tardia"])
        self.assertTrue(Asignacion.objects.filter(pk=self.asig.pk).exists())
        avisados = set(Aviso.objects.filter(tipo=Aviso.Tipo.CORTE)
                       .values_list("usuario__username", flat=True))
        # Dirección, su coach y el entrenador que le tiene en pista; no quien
        # lo declaró ni un coach que no le ve.
        self.assertEqual(avisados, {"ivan", "dani", "blas"})

    def test_sale_tachado_en_el_cuadrante(self):
        with reloj(a_las(LUNES, 21)):
            self._falta()
        api = APIClient()
        api.force_authenticate(self.u_ivan)
        r = api.get(f"/api/semanas/{self.semana.id}/cuadrante/?dia=1")
        fila = r.json()["asignaciones"][0]
        self.assertEqual(fila["falta"]["motivo"], "Estudios")
        self.assertTrue(fila["falta"]["tardia"])

    def test_rehacer_un_dia_cerrado_pide_confirmacion(self):
        api = APIClient()
        api.force_authenticate(self.u_dani)  # un coach también puede
        url = f"/api/semanas/{self.semana.id}/generar/"
        with reloj(a_las(LUNES, 20)):
            r = api.post(url, {"solo_dia": 1}, format="json")
            self.assertEqual(r.status_code, 409)
            self.assertTrue(r.json()["cerrado"])
            r = api.post(url, {"solo_dia": 1, "confirmar": True}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
        self.api.force_authenticate(self.u_victor)
        self.assertEqual(self.api.post(url, {"solo_dia": 3}, format="json").status_code, 403)


class ProgramadorTests(TestCase):
    def test_genera_el_dia_una_sola_vez_y_avisa_a_direccion(self):
        from scheduling.management.commands.programador import generar_dia

        User.objects.create_user(username="ivan", password="x", role=User.Role.SUPERADMIN)
        fila = generar_dia(MARTES)
        self.assertTrue(fila.ok, fila.detalle)
        self.assertIsNone(generar_dia(MARTES))
        self.assertEqual(GeneracionProgramada.objects.count(), 1)
        self.assertTrue(Semana.objects.filter(fecha_inicio=LUNES).exists())
        self.assertEqual(Aviso.objects.filter(tipo=Aviso.Tipo.GENERACION).count(), 1)
