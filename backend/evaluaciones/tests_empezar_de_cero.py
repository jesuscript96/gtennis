"""Empezar de cero a evaluar (19/11/2026): la migración borra todo y se
deshace exacta, PDF de Drive incluidos."""
import importlib
from unittest import mock

from django.apps import apps
from django.test import TestCase
from django.utils import timezone

from academy.models import Escuela, Jugador
from users.models import ArchivoMigracion, User

from . import drive
from .models import AsignacionFisica, Evaluacion, EvaluacionFisica, Informe

migracion = importlib.import_module("evaluaciones.migrations.0015_empezar_de_cero")


class EmpezarDeCeroTests(TestCase):
    def setUp(self):
        ct = Escuela.objects.create(nombre="Competición de tardes", solo_informes=True)
        self.nino = Jugador.objects.create(nombre="Nino", escuela=ct, activo=False)
        self.ana = Jugador.objects.create(nombre="Ana")
        self.u = User.objects.create_user(username="josep.mari", password="x", role=User.Role.PREPARADOR)
        t = Evaluacion.objects.create(jugador=self.nino, evaluador=self.u, estado="TERMINADA",
                                      puntuaciones={"drive_1": 4}, comentarios={"drive": {"original": "Bien"}})
        f = EvaluacionFisica.objects.create(jugador=self.nino, evaluador=self.u, estado="TERMINADA",
                                            puntuaciones={"fis_aceleracion": 3})
        self.validado = Informe.objects.create(jugador=self.nino, tenis=t, fisica=f, estado="VALIDADO",
                                               validado_en=timezone.now(), drive_file_id="pdf1",
                                               drive_file_id_es="pdf1es", destinatarios=[{"email": "a@b.es"}])
        suelta = Evaluacion.objects.create(jugador=self.ana, evaluador=self.u, estado="BORRADOR")
        Informe.objects.create(jugador=self.ana, tenis=suelta, estado="EN_CURSO")
        AsignacionFisica.objects.create(jugador=self.nino, evaluador=self.u)

    def test_borra_todo_y_se_deshace_exacto(self):
        antes = {m: list(m.objects.order_by("id").values()) for m in (Informe, Evaluacion, EvaluacionFisica)}
        with mock.patch.object(drive, "a_la_papelera") as papelera:
            migracion.aplicar(apps, None)
        self.assertEqual(sorted(c.args[0] for c in papelera.call_args_list), ["pdf1", "pdf1es"])
        for m in (Informe, Evaluacion, EvaluacionFisica):
            self.assertFalse(m.objects.exists(), m.__name__)
        # Lo demás se queda.
        self.assertTrue(AsignacionFisica.objects.filter(jugador=self.nino).exists())
        self.assertEqual(ArchivoMigracion.objects.filter(migracion=migracion.NOMBRE).count(), 5)

        with mock.patch.object(drive, "sacar_de_papelera") as sacar:
            migracion.deshacer(apps, None)
        self.assertEqual(sorted(c.args[0] for c in sacar.call_args_list), ["pdf1", "pdf1es"])
        despues = {m: list(m.objects.order_by("id").values()) for m in (Informe, Evaluacion, EvaluacionFisica)}
        self.assertEqual(despues, antes)
        self.assertFalse(ArchivoMigracion.objects.filter(migracion=migracion.NOMBRE).exists())
