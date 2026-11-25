"""El head coach envía a la familia los informes de Alto rendimiento de su
color (25/11/2026): los mismos que valida. Ni los de otro color ni los de
Competición de tardes."""
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from academy.models import Aviso, Coach, Entrenador, Escuela, Jugador
from users.models import Funcion, User

from . import informes
from .models import Evaluacion, EvaluacionFisica, Informe

DEST = [{"email": "familia@example.com", "quien": "Madre"}]


@override_settings(EMAIL_HOST="smtp.prueba", CORREO_GMAIL="", ANTHROPIC_API_KEY="",
                   GOOGLE_SERVICE_ACCOUNT_JSON="", DRIVE_INFORMES_ID="", DRIVE_CT_USUARIO="",
                   DEFAULT_FROM_EMAIL="gestion@gtennis.com")
class Base(TestCase):
    """Santi (rojo, Patricio → Ana), Pablo (turquesa, Mario → Leo), un jugador
    de Alto rendimiento sin responsable y uno de tardes."""

    def setUp(self):
        pdf = mock.patch.object(informes, "pdf_de", return_value=("informe.pdf", b"%PDF-1.4 prueba"))
        pdf.start()
        self.addCleanup(pdf.stop)
        mk = lambda n, r: User.objects.create_user(username=n, password="x", role=r)  # noqa: E731
        self.dir = mk("dir", User.Role.SUPERADMIN)
        self.alberto = mk("alberto.sanz", User.Role.ENTRENADOR)
        Funcion.objects.create(usuario=self.alberto, codigo="VALIDA_INFORMES")
        self.santi = mk("santi", User.Role.COACH)
        self.pablo = mk("pablo", User.Role.COACH)
        self.u_patricio = mk("patricio", User.Role.ENTRENADOR)
        self.patricio = Entrenador.objects.create(nombre="Patricio", user=self.u_patricio)
        self.mario = Entrenador.objects.create(nombre="Mario")
        Coach.objects.create(nombre="Santi", color="rojo", user=self.santi).entrenadores.add(self.patricio)
        Coach.objects.create(nombre="Pablo", color="turquesa", user=self.pablo).entrenadores.add(self.mario)

        ar, _ = Escuela.objects.get_or_create(nombre="Alto Rendimiento")
        ct, _ = Escuela.objects.update_or_create(nombre="Competición de tardes", defaults={"solo_informes": True})
        self.ana = Jugador.objects.create(nombre="Ana Rojo", escuela=ar, entrenador_responsable=self.patricio)
        self.leo = Jugador.objects.create(nombre="Leo Turquesa", escuela=ar, entrenador_responsable=self.mario)
        self.sin = Jugador.objects.create(nombre="Sin Responsable", escuela=ar)
        self.nino = Jugador.objects.create(nombre="Nino Tardes", escuela=ct, activo=False,
                                           entrenador_responsable=self.patricio)

    def informe(self, jugador, estado="VALIDADO"):
        t = Evaluacion.objects.create(jugador=jugador, evaluador=self.dir, estado="TERMINADA")
        f = (EvaluacionFisica.objects.create(jugador=jugador, estado="TERMINADA")
             if jugador == self.nino else None)
        return Informe.objects.create(jugador=jugador, tenis=t, fisica=f, estado=estado, destinatarios=DEST,
                                      validado_en=timezone.now() if estado == "VALIDADO" else None)

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c



class HeadCoachEnviaTests(Base):
    def test_envia_ya_los_de_su_color(self):
        inf = self.informe(self.ana)
        r = self.api(self.santi).post(f"/api/informes/{inf.id}/enviar/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["puede_enviar"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["familia@example.com"])
        inf.refresh_from_db()
        self.assertEqual(inf.enviado_por, self.santi)

    def test_programa_y_cancela_los_de_su_color(self):
        inf = self.informe(self.ana)
        c = self.api(self.santi)
        r = c.post(f"/api/informes/{inf.id}/enviar/", {"cuando": "manana"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        inf.refresh_from_db()
        self.assertEqual(inf.envio_programado_por, self.santi)
        self.assertIsNotNone(inf.envio_programado)
        self.assertEqual(c.post(f"/api/informes/{inf.id}/cancelar_envio/", {}, format="json").status_code, 200)
        inf.refresh_from_db()
        self.assertIsNone(inf.envio_programado)
        self.assertEqual(mail.outbox, [])

    def test_aprobar_y_enviar_manana(self):
        inf = self.informe(self.ana, estado="PENDIENTE")
        r = self.api(self.santi).post(f"/api/informes/{inf.id}/aprobar/", {"destinatarios": DEST, "enviar": "manana"},
                                      format="json")
        self.assertEqual(r.status_code, 200, r.content)
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.validado_por, inf.envio_programado_por),
                         ("VALIDADO", self.santi, self.santi))
        self.assertFalse(Aviso.objects.filter(titulo__contains="listo para enviar").exists())

    def test_aprobar_y_enviar_ahora(self):
        inf = self.informe(self.ana, estado="PENDIENTE")
        r = self.api(self.santi).post(f"/api/informes/{inf.id}/aprobar/", {"destinatarios": DEST, "enviar": "ahora"},
                                      format="json")
        self.assertEqual(r.status_code, 200, r.content)
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.enviado_por), ("VALIDADO", self.santi))
        self.assertEqual(len(mail.outbox), 1)

    def test_no_los_de_otro_color_ni_los_de_tardes_ni_sin_responsable(self):
        for jugador in (self.leo, self.nino, self.sin):
            inf = self.informe(jugador)
            for accion in ("enviar", "cancelar_envio"):
                r = self.api(self.santi).post(f"/api/informes/{inf.id}/{accion}/", {}, format="json")
                self.assertIn(r.status_code, (403, 404), (jugador.nombre, accion))
        self.assertEqual(mail.outbox, [])
        self.assertFalse(Informe.objects.exclude(enviado_en=None).exists())

    def test_lista_por_enviar_solo_lo_suyo(self):
        mio, otro = self.informe(self.ana), self.informe(self.leo)
        ls = self.api(self.santi).get("/api/informes/", {"estado": "VALIDADO"}).json()
        self.assertEqual([(i["id"], i["puede_enviar"]) for i in ls], [(mio.id, True)])
        ls = {i["id"]: i["puede_enviar"] for i in self.api(self.dir).get("/api/informes/", {"estado": "VALIDADO"}).json()}
        self.assertEqual(ls, {mio.id: True, otro.id: True})
        self.assertTrue(self.api(self.santi).get("/api/informes/panel/").json()["puede_enviar"])

    def test_el_entrenador_y_quien_valida_tardes_siguen_sin_enviar(self):
        inf = self.informe(self.ana)
        self.assertEqual(self.api(self.u_patricio).post(f"/api/informes/{inf.id}/enviar/", {}, format="json")
                         .status_code, 403)
        ct = self.informe(self.nino)
        self.assertEqual(self.api(self.alberto).post(f"/api/informes/{ct.id}/enviar/", {}, format="json")
                         .status_code, 403)
        self.assertEqual(mail.outbox, [])


class PruebaDeEnvioTests(Base):
    """Mandar a un correo, y a nadie más, el mismo correo que recibiría la
    familia (25/11/2026), sin que cuente como enviado."""

    def test_llega_solo_a_ese_correo_y_el_informe_no_cambia(self):
        inf = self.informe(self.ana)
        antes = Informe.objects.filter(pk=inf.pk).values().get()
        r = self.api(self.santi).post(f"/api/informes/{inf.id}/prueba/", {"email": " santi@example.com "},
                                      format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["enviado_a"], "santi@example.com")
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual((m.to, m.cc, m.bcc), (["santi@example.com"], [], []))
        self.assertEqual(m.from_email, "gestion@gtennis.com")
        self.assertIn("Ana Rojo", m.subject)
        self.assertEqual(m.attachments[0][0], "informe.pdf")
        self.assertEqual(Informe.objects.filter(pk=inf.pk).values().get(), antes)

    def test_mismo_correo_que_la_familia(self):
        inf = self.informe(self.ana)
        self.api(self.santi).post(f"/api/informes/{inf.id}/prueba/", {"email": "santi@example.com"}, format="json")
        self.api(self.santi).post(f"/api/informes/{inf.id}/enviar/", {}, format="json")
        prueba, real = mail.outbox
        self.assertEqual((prueba.subject, prueba.body, prueba.reply_to, prueba.attachments),
                         (real.subject, real.body, real.reply_to, real.attachments))
        self.assertEqual(real.to, ["familia@example.com"])

    def test_quien_puede_y_que(self):
        inf = self.informe(self.ana)
        self.assertEqual(self.api(self.pablo).post(f"/api/informes/{inf.id}/prueba/", {"email": "a@b.es"},
                                                   format="json").status_code, 404)
        self.assertEqual(self.api(self.u_patricio).post(f"/api/informes/{inf.id}/prueba/", {"email": "a@b.es"},
                                                        format="json").status_code, 403)
        self.assertEqual(self.api(self.santi).post(f"/api/informes/{inf.id}/prueba/", {"email": "no"},
                                                   format="json").status_code, 400)
        pendiente = self.informe(self.ana, estado="PENDIENTE")
        self.assertEqual(self.api(self.dir).post(f"/api/informes/{pendiente.id}/prueba/", {"email": "a@b.es"},
                                                 format="json").status_code, 400)
        self.assertEqual(mail.outbox, [])
