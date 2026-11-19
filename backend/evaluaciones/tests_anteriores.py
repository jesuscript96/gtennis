"""Consultar lo evaluado antes de «empezar de cero» (19/11/2026)."""
from datetime import date

from django.apps import apps
from django.test import override_settings

from users import archivo_migraciones as archivo
from users.models import User

from . import anteriores
from .models import Evaluacion, EvaluacionFisica
from .tests import SIN_CAPTURA_DE_PLANTILLAS
from .tests_alto_rendimiento import FISICA, TENIS, Base


def archivar(obj):
    """Lo mismo que hizo la migración 0015: la fila entera al archivo y borrarla."""
    archivo.guardar(apps, anteriores.MIGRACION, "borrado", obj)
    obj.delete()


@SIN_CAPTURA_DE_PLANTILLAS
@override_settings(ANTHROPIC_API_KEY="", GOOGLE_SERVICE_ACCOUNT_JSON="", DRIVE_INFORMES_ID="")
class AnterioresTests(Base):
    def setUp(self):
        super().setUp()
        self.josep = User.objects.create_user(username="josep.mari", password="x", role=User.Role.PREPARADOR)
        vieja = Evaluacion.objects.create(
            jugador=self.ana, evaluador=self.u_blas, nombre_evaluador="Blas", estado="TERMINADA", escala=5,
            fecha=date(2026, 10, 20), puntuaciones={"drive_impact": 2}, comentarios={"serve": {"original": "viejo"}})
        nueva = Evaluacion.objects.create(
            jugador=self.ana, evaluador=self.u_blas, nombre_evaluador="Blas", estado="TERMINADA", escala=10,
            fecha=date(2026, 11, 12), puntuaciones={"drive_impact": 7},
            comentarios={"serve": {"original": "Lanza mal la bola", "pulido": "Debe mejorar el lanzamiento."}},
            fortalezas=["Saque"], mejoras=["Revés"], fortalezas_original=["saque"], mejoras_original=["reves"])
        fis = EvaluacionFisica.objects.create(
            jugador=self.ana, evaluador=self.josep, nombre_evaluador="Josep", estado="TERMINADA",
            fecha=date(2026, 11, 3), puntuaciones=FISICA, textos={"puntos_fuertes": "Explosivo"})
        for o in (vieja, nueva, fis):
            archivar(o)

    def test_la_ultima_de_tenis_con_sus_comentarios(self):
        r = self.api(self.u_blas).get("/api/evaluaciones/anterior/", {"jugador": self.ana.id})
        self.assertEqual(r.status_code, 200, r.content)
        a = r.json()["anterior"]
        self.assertEqual((a["fecha"], a["evaluador"], a["escala"], a["terminada"]), ("2026-11-12", "Blas", 10, True))
        self.assertEqual(a["puntuaciones"], {"drive_impact": 7})
        self.assertEqual(a["comentarios"]["serve"], {"original": "Lanza mal la bola", "pulido": "Debe mejorar el lanzamiento."})
        self.assertEqual((a["fortalezas_original"], a["mejoras"]), (["saque"], ["Revés"]))

    def test_solo_quien_puede_evaluar_al_jugador(self):
        # Mario es de otro grupo; dirección lo ve todo.
        self.assertEqual(self.api(self.u_mario).get("/api/evaluaciones/anterior/", {"jugador": self.ana.id}).status_code, 403)
        self.assertEqual(self.api(self.dir).get("/api/evaluaciones/anterior/", {"jugador": self.ana.id}).status_code, 200)
        self.assertEqual(self.api(self.u_blas).get("/api/evaluaciones/anterior/").status_code, 400)

    def test_sin_nada_archivado(self):
        r = self.api(self.u_javi).get("/api/evaluaciones/anterior/", {"jugador": self.bea.id})
        self.assertEqual((r.status_code, r.json()), (200, {"anterior": None}))

    def test_la_fisica_la_ve_quien_evalua_fisica(self):
        r = self.api(self.josep).get("/api/evaluaciones-fisicas/anterior/", {"jugador": self.ana.id})
        self.assertEqual(r.status_code, 200, r.content)
        a = r.json()["anterior"]
        self.assertEqual((a["evaluador"], a["fecha"], a["textos"]), ("Josep", "2026-11-03", {"puntos_fuertes": "Explosivo"}))
        self.assertEqual(a["puntuaciones"], FISICA)
        # Un entrenador no entra en la parte física.
        self.assertEqual(self.api(self.u_blas).get("/api/evaluaciones-fisicas/anterior/", {"jugador": self.ana.id}).status_code, 403)

    def test_lo_de_ahora_no_se_mezcla(self):
        """Lo archivado no reaparece como evaluación: la lista sigue vacía."""
        self.assertEqual(self.api(self.dir).get("/api/evaluaciones/").json(), [])
        self.assertEqual(self.api(self.dir).get("/api/informes/").json(), [])
