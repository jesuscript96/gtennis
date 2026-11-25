"""La preparación física del 1 al 10 (25/11/2026), como el tenis: primero en
Alto rendimiento y el mismo día en Competición de tardes. Las ya hechas pasan
con una regla de tres."""
import importlib

from django.apps import apps as django_apps

from users.models import ArchivoMigracion

from . import pdf
from .models import Evaluacion, EvaluacionFisica, Informe
from .tests import SIN_CAPTURA_DE_PLANTILLAS
from .tests_alto_rendimiento import FISICA, TENIS
from .tests_huecos_informes import SIN_DRIVE, ConPreparador


@SIN_CAPTURA_DE_PLANTILLAS
@SIN_DRIVE
class EscalaFisicaTests(ConPreparador):
    def nueva(self, jugador):
        r = self.api(self.josep).post("/api/evaluaciones-fisicas/", {"jugador": jugador.id}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def nota(self, ev_id, n):
        return self.api(self.josep).patch(f"/api/evaluaciones-fisicas/{ev_id}/",
                                          {"puntuaciones": {"fis_aceleracion": n}}, format="json")

    def test_alto_rendimiento_del_1_al_10(self):
        ev = self.nueva(self.ana)
        self.assertEqual(ev["escala"], 10)
        self.assertEqual(self.nota(ev["id"], 10).status_code, 200)
        r = self.nota(ev["id"], 11)
        self.assertEqual(r.status_code, 400)
        self.assertIn("del 1 al 10", str(r.content, "utf-8"))

    def test_tardes_tambien_del_1_al_10(self):
        ev = self.nueva(self.nino)
        self.assertEqual(ev["escala"], 10)
        self.assertEqual(self.nota(ev["id"], 10).status_code, 200)
        self.assertEqual(self.nota(ev["id"], 11).status_code, 400)

    def test_al_crear_tambien_se_mira_la_escala(self):
        r = self.api(self.josep).post("/api/evaluaciones-fisicas/",
                                      {"jugador": self.ana.id, "puntuaciones": {"fis_agilidad": 9}}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        r = self.api(self.josep).post("/api/evaluaciones-fisicas/",
                                      {"jugador": self.nino.id, "puntuaciones": {"fis_agilidad": 11}}, format="json")
        self.assertEqual(r.status_code, 400)

    def _informe(self, jugador, fisica, escala, validado_en=None):
        tenis = Evaluacion.objects.create(jugador=jugador, evaluador=self.u_blas, nombre_evaluador="Blas",
                                          puntuaciones=TENIS, escala=10, estado="TERMINADA")
        fis = EvaluacionFisica.objects.create(jugador=jugador, evaluador=self.josep, nombre_evaluador="Josep Mari",
                                              puntuaciones=fisica, escala=escala, estado="TERMINADA")
        return Informe.objects.create(jugador=jugador, tenis=tenis, fisica=fis,
                                      estado="VALIDADO" if validado_en else "PENDIENTE", validado_en=validado_en)

    def test_el_pdf_pinta_la_escala_de_la_fisica(self):
        inf = self._informe(self.ana, {k: 8 for k in FISICA}, 10)
        d = pdf.datos_informe(inf)["fisico"]
        self.assertEqual(d["escala"], 10)
        self.assertIn("del 1 al 10", d["sub"])
        self.assertEqual(len(d["bloques"][0]["criterios"][0]["segmentos"]), 10)
        self.assertEqual(sum(d["bloques"][0]["criterios"][0]["segmentos"]), 8)
        self.assertEqual(d["bloques"][0]["media"], "8,0")
        html = pdf.html_informe(inf)
        self.assertIn("<small>/ 10</small>", html)
        self.assertNotIn("<small>/ 5</small>", html)
        self.assertIn('class="seg diez"', html)

    def test_una_de_antes_en_el_pdf_sigue_sobre_5(self):
        inf = self._informe(self.nino, FISICA, 5)
        d = pdf.datos_informe(inf)["fisico"]
        self.assertEqual((d["escala"], len(d["bloques"][0]["criterios"][0]["segmentos"])), (5, 5))
        self.assertIn("del 1 al 5", d["sub"])

    def test_la_evolucion_lleva_el_anterior_a_la_escala_de_ahora(self):
        from django.utils import timezone
        from datetime import timedelta

        self._informe(self.ana, {k: 3 for k in FISICA}, 5, validado_en=timezone.now() - timedelta(days=90))
        inf = self._informe(self.ana, {k: 7 for k in FISICA}, 10)
        evol = pdf.datos_informe(inf)["fisico"]["bloques"][0]["evol"]
        # Antes un 3 de 5 = un 6 de 10; ahora 7: sube 1.
        self.assertEqual(evol, {"dir": "sube", "txt": "▲ 1,0"})


@SIN_CAPTURA_DE_PLANTILLAS
@SIN_DRIVE
class MigracionFisicaDiezTests(ConPreparador):
    def setUp(self):
        super().setUp()
        self.mig = importlib.import_module("evaluaciones.migrations.0017_fisica_del_1_al_10")

    def test_regla_de_tres_y_se_deshace(self):
        notas = {**{k: 3 for k in FISICA}, "fis_aceleracion": 1, "fis_potencia": 5}
        ar = EvaluacionFisica.objects.create(jugador=self.ana, nombre_evaluador="Josep Mari", puntuaciones=notas,
                                             escala=5, estado="TERMINADA")
        a_medias = EvaluacionFisica.objects.create(jugador=self.bea, nombre_evaluador="Josep Mari",
                                                   puntuaciones={"fis_agilidad": 4}, escala=5)
        ct = EvaluacionFisica.objects.create(jugador=self.nino, nombre_evaluador="Josep Mari", puntuaciones=FISICA,
                                             escala=5, estado="TERMINADA")

        self.mig.aplicar(django_apps, None)
        ar.refresh_from_db()
        self.assertEqual(ar.escala, 10)
        self.assertEqual((ar.puntuaciones["fis_aceleracion"], ar.puntuaciones["fis_potencia"],
                          ar.puntuaciones["fis_agilidad"]), (2, 10, 6))
        self.assertEqual(len(ar.puntuaciones), len(notas))
        a_medias.refresh_from_db()
        self.assertEqual((a_medias.escala, a_medias.puntuaciones), (10, {"fis_agilidad": 8}))
        ct.refresh_from_db()
        self.assertEqual((ct.escala, ct.puntuaciones), (5, FISICA))

        # Volver a aplicarla no duplica: las de 10 ya no se tocan.
        self.mig.aplicar(django_apps, None)
        ar.refresh_from_db()
        self.assertEqual(ar.puntuaciones["fis_potencia"], 10)

        self.mig.deshacer(django_apps, None)
        ar.refresh_from_db()
        a_medias.refresh_from_db()
        self.assertEqual((ar.escala, ar.puntuaciones), (5, notas))
        self.assertEqual((a_medias.escala, a_medias.puntuaciones), (5, {"fis_agilidad": 4}))
        self.assertFalse(ArchivoMigracion.objects.filter(migracion=self.mig.NOMBRE).exists())


@SIN_CAPTURA_DE_PLANTILLAS
@SIN_DRIVE
class MigracionTardesDiezTests(ConPreparador):
    def setUp(self):
        super().setUp()
        self.mig = importlib.import_module("evaluaciones.migrations.0018_tardes_del_1_al_10")

    def test_lo_que_quedaba_del_1_al_5_pasa_y_se_deshace(self):
        # Como en prod: tenis de tardes empezado (del 1 al 5) y lo de Alto
        # rendimiento ya del 1 al 10.
        ct = Evaluacion.objects.create(jugador=self.nino, evaluador=self.u_blas, nombre_evaluador="Blas",
                                       escala=5, puntuaciones={"drive_impact": 3, "drive_control": 5})
        ar = Evaluacion.objects.create(jugador=self.ana, evaluador=self.u_blas, nombre_evaluador="Blas",
                                       escala=10, puntuaciones={"drive_impact": 7})
        fis = EvaluacionFisica.objects.create(jugador=self.nino, nombre_evaluador="Josep Mari", escala=5,
                                              puntuaciones={"fis_agilidad": 2})

        self.mig.aplicar(django_apps, None)
        for ev in (ct, ar, fis):
            ev.refresh_from_db()
        self.assertEqual((ct.escala, ct.puntuaciones), (10, {"drive_impact": 6, "drive_control": 10}))
        self.assertEqual((ar.escala, ar.puntuaciones), (10, {"drive_impact": 7}))
        self.assertEqual((fis.escala, fis.puntuaciones), (10, {"fis_agilidad": 4}))

        self.mig.deshacer(django_apps, None)
        for ev in (ct, ar, fis):
            ev.refresh_from_db()
        self.assertEqual((ct.escala, ct.puntuaciones), (5, {"drive_impact": 3, "drive_control": 5}))
        self.assertEqual((ar.escala, ar.puntuaciones), (10, {"drive_impact": 7}))
        self.assertEqual((fis.escala, fis.puntuaciones), (5, {"fis_agilidad": 2}))
        self.assertFalse(ArchivoMigracion.objects.filter(migracion=self.mig.NOMBRE).exists())
