"""Huecos de los informes vistos en prod el 24/11/2026: la física que llega
después de aprobar el tenis, el aviso a quien envía y el correo escrito al
aprobar, que ahora se queda en la ficha."""
import importlib
from datetime import timedelta

from django.apps import apps as django_apps
from django.test import override_settings
from django.utils import timezone

from academy.models import Aviso, Jugador
from users.models import ArchivoMigracion, Funcion, User

from . import pdf
from .models import DatosInforme, EvaluacionFisica, Informe
from .tests import SIN_CAPTURA_DE_PLANTILLAS
from .tests_alto_rendimiento import FISICA, Base

SIN_DRIVE = override_settings(ANTHROPIC_API_KEY="", GOOGLE_SERVICE_ACCOUNT_JSON="", DRIVE_INFORMES_ID="",
                              DRIVE_CT_USUARIO="", CORREO_GMAIL="")


class ConPreparador(Base):
    def setUp(self):
        super().setUp()
        self.josep = User.objects.create_user(username="josep.mari", password="x", role=User.Role.PREPARADOR)

    def fisica(self, jugador, terminar=True, esperado=201):
        c = self.api(self.josep)
        r = c.post("/api/evaluaciones-fisicas/", {"jugador": jugador.id}, format="json")
        self.assertEqual(r.status_code, esperado, r.content)
        if esperado != 201:
            return r.json()
        ev_id = r.json()["id"]
        if terminar:
            self.terminar_fisica(ev_id)
        return ev_id

    def terminar_fisica(self, ev_id):
        c = self.api(self.josep)
        self.assertEqual(c.patch(f"/api/evaluaciones-fisicas/{ev_id}/", {"puntuaciones": FISICA}, format="json")
                         .status_code, 200)
        r = c.post(f"/api/evaluaciones-fisicas/{ev_id}/terminar/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def aprobado(self, jugador, quien=None, destinatarios=()):
        """Tenis evaluado por su entrenador y aprobado (por el head coach, Dani)."""
        self.evaluar({self.ana.pk: self.u_blas, self.bea.pk: self.u_javi}[jugador.pk], jugador)
        inf = Informe.objects.get(jugador=jugador)
        r = self.api(quien or self.u_dani).post(f"/api/informes/{inf.id}/aprobar/",
                                                {"destinatarios": list(destinatarios)}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        inf.refresh_from_db()
        self.assertEqual(inf.estado, "VALIDADO")
        return inf


@SIN_CAPTURA_DE_PLANTILLAS
@SIN_DRIVE
class FisicaTardiaTests(ConPreparador):
    def test_la_fisica_tras_aprobar_se_suma_al_informe_aprobado(self):
        inf = self.aprobado(self.ana)
        fis_id = self.fisica(self.ana, terminar=False)
        inf.refresh_from_db()
        # El mismo informe, reabierto como versión 2 con la física; no uno nuevo.
        self.assertEqual(Informe.objects.filter(jugador=self.ana).count(), 1)
        self.assertEqual((inf.estado, inf.version, inf.fisica_id, inf.validado_por), ("EN_CURSO", 2, fis_id, None))
        aviso = Aviso.objects.get(titulo__contains="se le suma la parte física")
        self.assertEqual(aviso.usuario, self.u_dani)
        self.assertNotIn("cancelado", aviso.mensaje)
        # Josep puede seguir con su física (el informe ya no está cerrado).
        self.terminar_fisica(fis_id)
        inf.refresh_from_db()
        self.assertEqual(inf.estado, "PENDIENTE")
        self.assertEqual(pdf.datos_informe(inf)["fisico"]["evaluador"], "josep.mari")
        listo = Aviso.objects.filter(titulo__contains="listo para validar", mensaje__contains="preparación física")
        self.assertEqual(set(listo.values_list("usuario__username", flat=True)), {"dir", "dani"})
        r = self.api(self.u_dani).post(f"/api/informes/{inf.id}/aprobar/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.version, inf.fisica_id), ("VALIDADO", 2, fis_id))

    def test_no_deja_empezar_otra_fisica_mientras(self):
        self.aprobado(self.ana)
        fis_id = self.fisica(self.ana, terminar=False)
        r = self.fisica(self.ana, esperado=400)
        self.assertEqual(str(r["existente"]), str(fis_id))

    def test_si_ya_se_envio_es_para_el_siguiente_informe(self):
        inf = self.aprobado(self.ana)
        Informe.objects.filter(pk=inf.pk).update(enviado_en=timezone.now())
        fis_id = self.fisica(self.ana, terminar=False)
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.version, inf.fisica_id), ("VALIDADO", 1, None))
        nuevo = Informe.objects.exclude(pk=inf.pk).get(jugador=self.ana)
        self.assertEqual((nuevo.estado, nuevo.fisica_id, nuevo.tenis_id), ("EN_CURSO", fis_id, None))

    def test_si_es_de_otro_trimestre_es_para_el_siguiente_informe(self):
        inf = self.aprobado(self.ana)
        Informe.objects.filter(pk=inf.pk).update(validado_en=timezone.now() - timedelta(days=80))
        self.fisica(self.ana, terminar=False)
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.fisica_id), ("VALIDADO", None))
        self.assertEqual(Informe.objects.filter(jugador=self.ana).count(), 2)

    def test_cancela_el_envio_programado_y_avisa_a_quien_lo_programo(self):
        inf = self.aprobado(self.ana)
        Informe.objects.filter(pk=inf.pk).update(envio_programado=timezone.now() + timedelta(hours=10),
                                                 envio_programado_por=self.dir)
        self.fisica(self.ana, terminar=False)
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.envio_programado, inf.envio_programado_por), ("EN_CURSO", None, None))
        avisos = Aviso.objects.filter(titulo__contains="se le suma la parte física")
        self.assertEqual(set(avisos.values_list("usuario__username", flat=True)), {"dani", "dir"})
        self.assertIn("se ha cancelado el envío programado", avisos.first().mensaje)

    def test_si_se_borra_la_fisica_el_tenis_vuelve_a_validar(self):
        inf = self.aprobado(self.ana)
        fis_id = self.fisica(self.ana, terminar=False)
        r = self.api(self.josep).delete(f"/api/evaluaciones-fisicas/{fis_id}/")
        self.assertEqual(r.status_code, 204, r.content)
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.fisica_id, inf.version), ("PENDIENTE", None, 2))
        self.assertEqual(Informe.objects.filter(jugador=self.ana).count(), 1)


@SIN_CAPTURA_DE_PLANTILLAS
@SIN_DRIVE
class AvisoParaEnviarTests(ConPreparador):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(username="administracion", password="x",
                                              role=User.Role.ADMINISTRACION)
        self.envia = User.objects.create_user(username="envia", password="x", role=User.Role.ENTRENADOR)
        Funcion.objects.create(usuario=self.envia, codigo="ENVIA_INFORMES")

    def test_si_aprueba_el_head_coach_se_avisa_a_quien_envia(self):
        self.aprobado(self.ana, destinatarios=[{"email": "madre@ejemplo.com", "quien": "Madre"}])
        avisos = Aviso.objects.filter(titulo__contains="listo para enviar")
        self.assertEqual(set(avisos.values_list("usuario__username", flat=True)), {"dir", "administracion", "envia"})
        self.assertIn("Por enviar", avisos.first().mensaje)
        self.assertNotIn("no tiene correo", avisos.first().mensaje)

    def test_dice_si_falta_el_correo(self):
        self.aprobado(self.ana)
        self.assertIn("no tiene correo", Aviso.objects.filter(titulo__contains="listo para enviar").first().mensaje)

    def test_si_aprueba_quien_envia_no_se_avisa(self):
        self.aprobado(self.ana, quien=self.dir)
        self.assertFalse(Aviso.objects.filter(titulo__contains="listo para enviar").exists())

    def test_el_panel_dice_quien_envia(self):
        self.assertTrue(self.api(self.dir).get("/api/informes/panel/").json()["puede_enviar"])
        self.assertFalse(self.api(self.u_dani).get("/api/informes/panel/").json()["puede_enviar"])


@SIN_CAPTURA_DE_PLANTILLAS
@SIN_DRIVE
class CorreoEnLaFichaTests(ConPreparador):
    def test_los_correos_escritos_al_aprobar_se_quedan_en_la_ficha(self):
        self.aprobado(self.ana, destinatarios=[{"email": "madre@ejemplo.com", "quien": "Madre"},
                                               {"email": "padre@ejemplo.com", "quien": "Padre"}])
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.email, "madre@ejemplo.com")
        datos = DatosInforme.objects.get(jugador=self.ana)
        self.assertEqual((datos.email_2, datos.quien_2, datos.idioma), ("padre@ejemplo.com", "Padre", "ES"))

    def test_no_cambia_ni_quita_los_que_ya_habia(self):
        Jugador.objects.filter(pk=self.ana.pk).update(email="ficha@ejemplo.com")
        DatosInforme.objects.create(jugador=self.ana, idioma="EN", email_2="dos@ejemplo.com", quien_2="Padre")
        self.aprobado(self.ana, destinatarios=[{"email": "otro@ejemplo.com", "quien": "Abuela"}])
        self.ana.refresh_from_db()
        datos = DatosInforme.objects.get(jugador=self.ana)
        self.assertEqual((self.ana.email, datos.email_2, datos.quien_2, datos.idioma),
                         ("ficha@ejemplo.com", "dos@ejemplo.com", "Padre", "EN"))

    def test_con_el_primero_en_la_ficha_el_nuevo_va_de_segundo(self):
        Jugador.objects.filter(pk=self.ana.pk).update(email="ficha@ejemplo.com")
        self.aprobado(self.ana, destinatarios=[{"email": "FICHA@ejemplo.com", "quien": "Familia"},
                                               {"email": "no es un correo", "quien": "x"},
                                               {"email": "nuevo@ejemplo.com", "quien": "Familia"}])
        datos = DatosInforme.objects.get(jugador=self.ana)
        self.assertEqual((datos.email_2, datos.quien_2), ("nuevo@ejemplo.com", ""))


@SIN_CAPTURA_DE_PLANTILLAS
@SIN_DRIVE
class MigracionFisicaTardiaTests(ConPreparador):
    """La migración de datos arregla lo que ya estaba así en prod y se deshace entera."""

    def setUp(self):
        super().setUp()
        self.mig = importlib.import_module("evaluaciones.migrations.0016_fisica_tardia_y_correos")

    def test_aplica_y_deshace(self):
        # Como en prod: tenis aprobado con el correo escrito a mano, y la física
        # colgada después de un informe nuevo.
        inf = self.aprobado(self.ana, destinatarios=[{"email": "madre@ejemplo.com", "quien": "Madre"}])
        Jugador.objects.filter(pk=self.ana.pk).update(email="")
        fis = EvaluacionFisica.objects.create(jugador=self.ana, evaluador=self.josep, nombre_evaluador="Josep Mari",
                                              puntuaciones=FISICA, estado="TERMINADA")
        vacio = Informe.objects.create(jugador=self.ana, fisica=fis)
        otro = self.aprobado(self.bea)
        Aviso.objects.all().delete()

        self.mig.aplicar(django_apps, None)
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.version, inf.fisica_id, inf.validado_en), ("PENDIENTE", 2, fis.pk, None))
        self.assertFalse(Informe.objects.filter(pk=vacio.pk).exists())
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.email, "madre@ejemplo.com")
        sumada = Aviso.objects.filter(titulo__contains="se le ha sumado la parte física")
        self.assertEqual(set(sumada.values_list("usuario__username", flat=True)), {"dir", "dani"})
        sin_enviar = Aviso.objects.get(titulo="1 informe aprobado sin enviar")
        self.assertEqual(sin_enviar.usuario, self.dir)
        self.assertIn("Bea Javi", sin_enviar.mensaje)
        otro.refresh_from_db()
        self.assertEqual(otro.estado, "VALIDADO")

        self.mig.deshacer(django_apps, None)
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.version, inf.fisica_id), ("VALIDADO", 1, None))
        self.assertIsNotNone(inf.validado_en)
        self.assertEqual(Informe.objects.get(pk=vacio.pk).fisica_id, fis.pk)
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.email, "")
        self.assertFalse(Aviso.objects.exists())
        self.assertFalse(ArchivoMigracion.objects.filter(migracion=self.mig.NOMBRE).exists())

    def test_no_toca_lo_enviado_ni_lo_que_ya_tiene_fisica(self):
        inf = self.aprobado(self.ana)
        Informe.objects.filter(pk=inf.pk).update(enviado_en=timezone.now())
        fis = EvaluacionFisica.objects.create(jugador=self.ana, evaluador=self.josep, nombre_evaluador="Josep",
                                              puntuaciones=FISICA, estado="TERMINADA")
        vacio = Informe.objects.create(jugador=self.ana, fisica=fis)
        self.mig.aplicar(django_apps, None)
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.fisica_id), ("VALIDADO", None))
        self.assertTrue(Informe.objects.filter(pk=vacio.pk).exists())
