"""Correo a las familias (19/11/2026): por Gmail con la cuenta de servicio,
respuestas a gestion@ y al head coach, texto de Alto rendimiento y envío ya o
a las 8:30 del día siguiente."""
import base64
from datetime import datetime, time, timedelta
from unittest import mock

from django.core import mail
from django.core.mail import EmailMessage
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from academy.models import Aviso, Coach, Entrenador, Escuela, Jugador
from users.models import Funcion, User

from . import gmail, informes
from .models import Evaluacion, EvaluacionFisica, Informe

DEST = [{"email": "familia@example.com", "quien": "Madre"}]


@override_settings(EMAIL_HOST="smtp.prueba", CORREO_GMAIL="", ANTHROPIC_API_KEY="",
                   GOOGLE_SERVICE_ACCOUNT_JSON="", DRIVE_INFORMES_ID="", DRIVE_CT_USUARIO="",
                   DEFAULT_FROM_EMAIL="gestion@gtennis.com")
class CorreoFamiliasTests(TestCase):
    def setUp(self):
        pdf = mock.patch.object(informes, "pdf_de", return_value=("informe.pdf", b"%PDF-1.4 prueba"))
        pdf.start()
        self.addCleanup(pdf.stop)
        mk = lambda n, r, **kw: User.objects.create_user(username=n, password="x", role=r, **kw)  # noqa: E731
        self.dir = mk("dir", User.Role.SUPERADMIN)
        self.alberto = mk("alberto.sanz", User.Role.ENTRENADOR, email="alberto@gtennis.com")
        Funcion.objects.create(usuario=self.alberto, codigo="COORDINA_TARDES")
        self.santi = mk("santi", User.Role.COACH, email="santi@gtennis.com", first_name="Santi")
        coach = Coach.objects.create(nombre="Santi", user=self.santi)
        self.ent = Entrenador.objects.create(nombre="Patricio")
        coach.entrenadores.add(self.ent)

        ct = Escuela.objects.create(nombre="Competición de tardes", solo_informes=True)
        self.nino = Jugador.objects.create(nombre="Nino Tardes", escuela=ct, activo=False)
        self.ana = Jugador.objects.create(nombre="Ana Alto", entrenador_responsable=self.ent)
        self.ct = self._validado(self.nino, fisica=True)
        self.ar = self._validado(self.ana, fisica=False)

    def _validado(self, jugador, fisica):
        t = Evaluacion.objects.create(jugador=jugador, evaluador=self.dir, estado="TERMINADA")
        f = EvaluacionFisica.objects.create(jugador=jugador, evaluador=self.dir, estado="TERMINADA") if fisica else None
        return Informe.objects.create(jugador=jugador, tenis=t, fisica=f, estado="VALIDADO",
                                      validado_en=timezone.now(), destinatarios=DEST)

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_tardes_responde_a_gestion_y_al_coordinador(self):
        r = self.api(self.dir).post(f"/api/informes/{self.ct.id}/enviar/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        m = mail.outbox[-1]
        self.assertEqual(m.to, ["familia@example.com"])
        self.assertEqual(m.reply_to, ["gestion@gtennis.com", "alberto@gtennis.com"])
        self.assertIn("El coordinador se pondrá en contacto", m.body)
        self.assertEqual(m.attachments[0][0], "informe.pdf")
        self.assertEqual(r.data["responder_a"], ["gestion@gtennis.com", "alberto@gtennis.com"])

    def test_alto_rendimiento_su_texto_y_su_head_coach(self):
        self.api(self.dir).post(f"/api/informes/{self.ar.id}/enviar/", {}, format="json")
        m = mail.outbox[-1]
        self.assertEqual(m.reply_to, ["gestion@gtennis.com", "santi@gtennis.com"])
        self.assertIn("con la valoración de su entrenador.", m.body)
        self.assertNotIn("preparador físico", m.body)
        self.assertNotIn("coordinador", m.body)
        # Con la física terminada, la nombra.
        self.ar.fisica = EvaluacionFisica.objects.create(jugador=self.ana, evaluador=self.dir, estado="TERMINADA")
        self.ar.save()
        self.api(self.dir).post(f"/api/informes/{self.ar.id}/enviar/", {}, format="json")
        self.assertIn("de su entrenador y de su preparador físico", mail.outbox[-1].body)

    def test_head_coach_sin_correo(self):
        self.santi.email = ""
        self.santi.save()
        d = self.api(self.dir).get(f"/api/informes/{self.ar.id}/").data
        self.assertEqual(d["responder_a"], ["gestion@gtennis.com"])
        self.assertEqual(d["sin_correo_head_coach"], ["Santi"])

    def test_manana_a_las_ocho_y_media(self):
        r = self.api(self.dir).post(f"/api/informes/{self.ar.id}/enviar/", {"cuando": "manana"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(mail.outbox), 0)
        self.ar.refresh_from_db()
        salida = timezone.localtime(self.ar.envio_programado)
        self.assertEqual((salida.date(), salida.time()), (timezone.localdate() + timedelta(days=1), time(8, 30)))
        self.assertEqual(r.data["envio_programado_por_nombre"], "dir")
        # Antes de la hora no sale; a la hora, sí, y en nombre de quien lo programó.
        self.assertEqual(informes.enviar_programados(self.ar.envio_programado - timedelta(minutes=1)), 0)
        self.assertEqual(informes.enviar_programados(self.ar.envio_programado + timedelta(minutes=1)), 1)
        self.ar.refresh_from_db()
        self.assertEqual((self.ar.enviado_por, self.ar.envio_programado), (self.dir, None))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(informes.enviar_programados(timezone.now() + timedelta(days=2)), 0)

    def test_aprobar_y_enviar_manana(self):
        self.ar.estado = "PENDIENTE"
        self.ar.save()
        r = self.api(self.dir).post(f"/api/informes/{self.ar.id}/aprobar/",
                                    {"destinatarios": DEST, "enviar": "manana"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNotNone(r.data["envio_programado"])
        self.assertEqual(len(mail.outbox), 0)
        # «Aprobar y enviar» de siempre sale ya.
        self.ct.estado = "PENDIENTE"
        self.ct.save()
        self.api(self.dir).post(f"/api/informes/{self.ct.id}/aprobar/",
                                {"destinatarios": DEST, "enviar": True}, format="json")
        self.assertEqual(len(mail.outbox), 1)

    def test_cancelar_y_reabrir_quitan_lo_programado(self):
        c = self.api(self.dir)
        c.post(f"/api/informes/{self.ar.id}/enviar/", {"cuando": "manana"}, format="json")
        r = c.post(f"/api/informes/{self.ar.id}/cancelar_envio/", {}, format="json")
        self.assertIsNone(r.data["envio_programado"])
        c.post(f"/api/informes/{self.ar.id}/enviar/", {"cuando": "manana"}, format="json")
        informes.reabrir(self.ar, self.dir)
        self.ar.refresh_from_db()
        self.assertIsNone(self.ar.envio_programado)
        self.assertEqual(informes.enviar_programados(timezone.now() + timedelta(days=2)), 0)

    def test_sin_destinatarios_no_se_programa_y_un_fallo_avisa(self):
        self.ar.destinatarios = []
        self.ar.save()
        r = self.api(self.dir).post(f"/api/informes/{self.ar.id}/enviar/", {"cuando": "manana"}, format="json")
        self.assertEqual(r.status_code, 400)
        informes.programar(self.ct, self.dir, cuando=timezone.now())
        with mock.patch.object(EmailMessage, "send", side_effect=RuntimeError("buzón lleno")):
            self.assertEqual(informes.enviar_programados(), 0)
        self.ct.refresh_from_db()
        self.assertIsNone(self.ct.envio_programado)
        self.assertIn("buzón lleno", self.ct.envio_error)
        self.assertTrue(Aviso.objects.filter(usuario=self.dir, titulo__contains="No se ha enviado").exists())

    def test_quien_programa_y_cancela(self):
        for accion in ("enviar", "cancelar_envio"):
            r = self.api(self.alberto).post(f"/api/informes/{self.ct.id}/{accion}/", {"cuando": "manana"},
                                            format="json")
            self.assertEqual(r.status_code, 403, accion)

    def test_correo_del_personal(self):
        c = self.api(self.dir)
        r = c.patch(f"/api/auth/personal/{self.santi.id}/", {"email": " nuevo@gtennis.com "}, format="json")
        self.assertEqual((r.status_code, r.data["email"]), (200, "nuevo@gtennis.com"))
        self.santi.refresh_from_db()
        self.assertEqual((self.santi.email, self.santi.role), ("nuevo@gtennis.com", "COACH"))
        self.assertEqual(c.patch(f"/api/auth/personal/{self.santi.id}/", {"email": "no"}, format="json").status_code,
                         400)
        self.assertEqual(self.api(self.alberto).patch(f"/api/auth/personal/{self.santi.id}/", {"email": "a@b.es"},
                                                      format="json").status_code, 403)

    def test_comprobar_la_conexion_solo_direccion(self):
        self.assertEqual(self.api(self.alberto).get("/api/informes/correo/").status_code, 403)
        r = self.api(self.dir).get("/api/informes/correo/")
        self.assertEqual((r.status_code, r.data["via"], r.data["ok"]), (200, "smtp", True))


class GmailTests(TestCase):
    @override_settings(CORREO_GMAIL="gestion@gtennis.com", GOOGLE_SERVICE_ACCOUNT_JSON="{}")
    def test_envia_por_la_api_de_gmail(self):
        sesion = mock.MagicMock()
        sesion.post.return_value.ok = True
        with mock.patch.object(gmail, "_credenciales"), \
                mock.patch("google.auth.transport.requests.AuthorizedSession", return_value=sesion):
            m = EmailMessage("Asunto", "Hola", "G Tenis <gestion@gtennis.com>", ["familia@example.com"],
                             reply_to=["gestion@gtennis.com", "santi@gtennis.com"])
            m.attach("informe.pdf", b"%PDF", "application/pdf")
            self.assertEqual(gmail.GmailBackend().send_messages([m]), 1)
        url, = sesion.post.call_args.args
        self.assertEqual(url, gmail.ENVIAR)
        crudo = base64.urlsafe_b64decode(sesion.post.call_args.kwargs["json"]["raw"]).decode()
        self.assertIn("To: familia@example.com", crudo)
        self.assertIn("Reply-To: gestion@gtennis.com, santi@gtennis.com", crudo)
        self.assertIn("informe.pdf", crudo)

    @override_settings(CORREO_GMAIL="gestion@gtennis.com", GOOGLE_SERVICE_ACCOUNT_JSON="{}")
    def test_un_error_de_gmail_se_dice(self):
        sesion = mock.MagicMock()
        sesion.post.return_value.ok = False
        sesion.post.return_value.status_code = 403
        sesion.post.return_value.text = "Delegation denied"
        with mock.patch.object(gmail, "_credenciales"), \
                mock.patch("google.auth.transport.requests.AuthorizedSession", return_value=sesion):
            with self.assertRaises(gmail.GmailNoDisponible):
                gmail.GmailBackend().send_messages([EmailMessage("A", "B", "x@y.es", ["z@y.es"])])

    @override_settings(CORREO_GMAIL="gestion@gtennis.com", GOOGLE_SERVICE_ACCOUNT_JSON="{}")
    def test_comprobar_explica_lo_que_falta(self):
        cred = mock.MagicMock()
        cred.refresh.side_effect = Exception("unauthorized_client: Client is unauthorized to retrieve access tokens")
        with mock.patch.object(gmail, "_credenciales", return_value=cred):
            ok, detalle = gmail.comprobar()
        self.assertFalse(ok)
        self.assertIn("gmail.send", detalle)
        cred.refresh.side_effect = None
        with mock.patch.object(gmail, "_credenciales", return_value=cred):
            self.assertEqual(gmail.comprobar(), (True, "Envía como gestion@gtennis.com."))
        self.assertTrue(informes.correo_configurado())

    @override_settings(CORREO_GMAIL="", GOOGLE_SERVICE_ACCOUNT_JSON="{}", EMAIL_HOST="")
    def test_sin_cuenta_no_esta_configurado(self):
        self.assertFalse(gmail.configurado())
        self.assertEqual(gmail.comprobar()[0], False)


class DatosFamiliasTests(TestCase):
    """El Excel de correos de las familias (19/11/2026): sale y vuelve por aquí."""

    def setUp(self):
        self.dir = User.objects.create_user(username="dir", password="x", role=User.Role.SUPERADMIN)
        self.ent = User.objects.create_user(username="ent", password="x", role=User.Role.ENTRENADOR)
        ct = Escuela.objects.create(nombre="Competición de tardes", solo_informes=True)
        self.nino = Jugador.objects.create(nombre="Nino Tardes", escuela=ct, activo=False, email="a@b.es")
        self.ana = Jugador.objects.create(nombre="Ana Alto")

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_leer_y_guardar(self):
        url = "/api/informes/datos-familias/"
        self.assertEqual(self.api(self.ent).get(url).status_code, 403)
        filas = {f["jugador"]: f for f in self.api(self.dir).get(url).data}
        self.assertEqual((filas[self.nino.id]["email"], filas[self.nino.id]["circuito"]), ("a@b.es", "tardes"))
        self.assertEqual((filas[self.ana.id]["email"], filas[self.ana.id]["idioma"]), ("", "ES"))
        r = self.api(self.dir).post(url, {"filas": [
            {"jugador": self.ana.id, "email": " madre@ana.es ", "quien_1": "Madre", "idioma": "EN"},
            {"jugador": self.nino.id, "email_2": "padre@nino.es", "quien_2": "Padre"},
            {"jugador": self.nino.id, "email": "mal"},
            {"jugador": 999999, "email": "x@y.es"},
        ]}, format="json")
        self.assertEqual(r.data["guardados"], 2)
        self.assertEqual(len(r.data["errores"]), 2)
        self.ana.refresh_from_db()
        self.nino.refresh_from_db()
        self.assertEqual((self.ana.email, self.ana.datos_informe.idioma, self.ana.datos_informe.quien_1),
                         ("madre@ana.es", "EN", "Madre"))
        # Lo que no venía no se toca.
        self.assertEqual((self.nino.email, self.nino.datos_informe.email_2), ("a@b.es", "padre@nino.es"))
        self.assertEqual(informes.destinatarios_propuestos(self.nino),
                         [{"email": "a@b.es", "quien": "Familia"}, {"email": "padre@nino.es", "quien": "Padre"}])
