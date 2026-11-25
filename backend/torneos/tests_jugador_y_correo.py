"""25/11/2026: circuito de validación en dos pasos, página y PDF del jugador
y el correo del día 1 a las familias."""
from datetime import date, datetime, timedelta
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from academy.models import Aviso, Coach, Entrenador, Jugador, ResponsableJugador
from evaluaciones.models import DatosInforme
from users.models import User

from . import mensual
from .models import CorreoTorneos, NormasTorneos, Participante, Torneo

PDF_FALSO = b"%PDF-1.4 falso"


class Base(TestCase):
    def setUp(self):
        self.blas = Entrenador.objects.create(nombre="Blas")
        self.mario = Entrenador.objects.create(nombre="Mario")
        self.ana = Jugador.objects.create(nombre="Ana Pérez", entrenador_responsable=self.blas, email="familia.ana@x.es")
        self.leo = Jugador.objects.create(nombre="Leo", entrenador_responsable=self.mario)
        ResponsableJugador.objects.create(jugador=self.ana, entrenador=self.blas, prioridad=1)
        ResponsableJugador.objects.create(jugador=self.leo, entrenador=self.mario, prioridad=1)
        self.u_blas = User.objects.create_user(username="blas", password="x", role=User.Role.ENTRENADOR)
        self.blas.user = self.u_blas
        self.blas.save(update_fields=["user"])
        self.u_pablo = User.objects.create_user(username="pablo", password="x", role=User.Role.COACH,
                                                email="pablo@gtennis.com")
        Coach.objects.create(nombre="Pablo", user=self.u_pablo, color="turquesa").entrenadores.set([self.blas])
        self.u_santi = User.objects.create_user(username="santi", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Santi", user=self.u_santi, color="naranja").entrenadores.set([self.mario])
        self.u_dir = User.objects.create_user(username="dir", password="x", role=User.Role.SUPERADMIN)
        hoy = date.today()
        self.t = Torneo.objects.create(nombre="ITF J30 Silla", lugar="Silla", circuito="ITF Junior",
                                       fecha_inicio=hoy + timedelta(days=14), fecha_fin=hoy + timedelta(days=20),
                                       cierre_inscripcion=hoy + timedelta(days=5))
        self.otro = Torneo.objects.create(nombre="ITF J30 Valencia", fecha_inicio=hoy + timedelta(days=21),
                                          fecha_fin=hoy + timedelta(days=27),
                                          cierre_inscripcion=hoy - timedelta(days=1))
        self.pasado = Torneo.objects.create(nombre="W15 Villena", fecha_inicio=hoy - timedelta(days=10),
                                            fecha_fin=hoy - timedelta(days=4))

    def api(self, u):
        c = APIClient()
        c.force_authenticate(u)
        return c

    def apuntar(self, u, jugador, torneo=None):
        return self.api(u).post("/api/torneos-participantes/", {"torneo": (torneo or self.t).id,
                                                               "jugador": jugador.id}, format="json")


class CircuitoTests(Base):
    def test_validar_varios_y_aviso_a_direccion(self):
        p1 = self.apuntar(self.u_blas, self.ana).data["id"]
        p2 = self.apuntar(self.u_blas, self.ana, self.otro).data["id"]
        p3 = Participante.objects.create(torneo=self.t, jugador=self.leo, nombre="Leo",
                                         certeza=Participante.Certeza.PENDIENTE).id
        Aviso.objects.all().delete()
        r = self.api(self.u_pablo).post("/api/torneos-participantes/validar/", {"ids": [p1, p2, p3]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["validados"], 2)
        self.assertEqual(r.data["saltados"], ["Leo: no es de tu grupo"])
        self.assertEqual(set(Participante.objects.filter(certeza="VALIDADO_COACH").values_list("id", flat=True)),
                         {p1, p2})
        aviso = Aviso.objects.get()
        self.assertTrue(aviso.para_direccion)
        self.assertIn("valida 2 inscripciones", aviso.titulo)
        # Dirección, el visto bueno final (también al de otro grupo).
        r = self.api(self.u_dir).post("/api/torneos-participantes/validar/", {"ids": [p1, p2, p3]}, format="json")
        self.assertEqual(r.data["validados"], 3)
        self.assertEqual(Participante.objects.filter(certeza="CONFIRMADO", confirmado_por=self.u_dir).count(), 3)
        self.assertEqual(Aviso.objects.count(), 1)

    def test_el_entrenador_no_valida(self):
        pid = self.apuntar(self.u_blas, self.ana).data["id"]
        r = self.api(self.u_blas).post("/api/torneos-participantes/validar/", {"ids": [pid]}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_si_el_head_coach_mueve_uno_confirmado_vuelve_a_dirección(self):
        pid = self.apuntar(self.u_dir, self.ana).data["id"]
        self.assertEqual(Participante.objects.get(pk=pid).certeza, "CONFIRMADO")
        self.api(self.u_pablo).patch(f"/api/torneos-participantes/{pid}/", {"torneo": self.otro.id}, format="json")
        p = Participante.objects.get(pk=pid)
        self.assertEqual((p.torneo, p.certeza, p.confirmado_por), (self.otro, "VALIDADO_COACH", None))

    def test_deshacer_la_validacion(self):
        pid = self.apuntar(self.u_blas, self.ana).data["id"]
        self.api(self.u_pablo).post("/api/torneos-participantes/validar/", {"ids": [pid]}, format="json")
        r = self.api(self.u_pablo).post("/api/torneos-cambios/deshacer/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        p = Participante.objects.get(pk=pid)
        self.assertEqual((p.certeza, p.validado_coach_por), ("PENDIENTE", None))
        # Y al revés: deshacer en una foto con el visto bueno lo devuelve.
        self.api(self.u_pablo).post("/api/torneos-participantes/validar/", {"ids": [pid]}, format="json")
        self.api(self.u_pablo).patch(f"/api/torneos-participantes/{pid}/", {"detalle": "con hotel"}, format="json")
        self.api(self.u_pablo).post("/api/torneos-cambios/deshacer/", {}, format="json")
        p = Participante.objects.get(pk=pid)
        self.assertEqual((p.certeza, p.validado_coach_por, p.detalle), ("VALIDADO_COACH", self.u_pablo, ""))


class PaginaJugadorTests(Base):
    def test_sus_torneos_por_delante(self):
        Participante.objects.create(torneo=self.pasado, jugador=self.ana, nombre="Ana Pérez")
        Participante.objects.create(torneo=self.t, jugador=self.ana, nombre="Ana Pérez", detalle="con Blas")
        Participante.objects.create(torneo=self.otro, jugador=self.ana, nombre="Ana Pérez", certeza="PENDIENTE")
        self.t.acompanantes.add(self.blas)
        r = self.api(self.u_blas).get(f"/api/torneos/jugador/{self.ana.id}/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["jugador"]["nombre"], "Ana Pérez")
        self.assertEqual(r.data["jugados"], 1)
        self.assertEqual([(t["nombre"], t["confirmado"], t["espera"], t["inscripcion_abierta"])
                          for t in r.data["torneos"]],
                         [("ITF J30 Silla", True, None, True), ("ITF J30 Valencia", False, "head_coach", False)])
        self.assertEqual(r.data["torneos"][0]["acompanantes"], ["Blas"])
        self.assertEqual((r.data["resumen"]["total"], r.data["resumen"]["confirmados"],
                          r.data["resumen"]["proximo_cierre"]), (2, 1, self.t.cierre_inscripcion))

    def test_el_pdf(self):
        Participante.objects.create(torneo=self.t, jugador=self.ana, nombre="Ana Pérez", detalle="NOTA INTERNA")
        with mock.patch("torneos.pdf.foto_de", return_value=""):
            from torneos import pdf, por_jugador

            html = pdf.html(por_jugador.ficha(self.ana), por_jugador.torneos_de(self.ana))
            self.assertIn("ITF J30 Silla", html)
            self.assertIn("Inscripción hasta", html)
            self.assertNotIn("NOTA INTERNA", html)
            with mock.patch("torneos.pdf.generar", return_value=PDF_FALSO) as gen:
                r = self.api(self.u_blas).get(f"/api/torneos/jugador/{self.ana.id}/pdf/?idioma=EN")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertIn("Torneos%20Ana%20P%C3%A9rez.pdf", r["Content-Disposition"])
        self.assertEqual(gen.call_args.kwargs["idioma"], "EN")

    def test_el_pdf_de_verdad(self):
        """WeasyPrint saca un PDF (sin red: sin foto)."""
        Participante.objects.create(torneo=self.t, jugador=self.ana, nombre="Ana Pérez")
        from torneos import pdf, por_jugador

        contenido = pdf.generar(por_jugador.ficha(self.ana), por_jugador.torneos_de(self.ana),
                                normas="Puntualidad.\n- Llevar dos raquetas\n- Avisar si no vas")
        self.assertTrue(contenido.startswith(b"%PDF"))


@override_settings(EMAIL_HOST="smtp.prueba", CORREO_GMAIL="", DEFAULT_FROM_EMAIL="gestion@gtennis.com")
class CorreoMensualTests(Base):
    def setUp(self):
        super().setUp()
        self.mes = date.today().replace(day=1)
        Participante.objects.create(torneo=self.t, jugador=self.ana, nombre="Ana Pérez")
        Participante.objects.create(torneo=self.otro, jugador=self.ana, nombre="Ana Pérez", certeza="VALIDADO_COACH")
        Participante.objects.create(torneo=self.t, jugador=self.leo, nombre="Leo")
        NormasTorneos.objects.create(texto="Normas del club:\n- Puntualidad\n- Dos raquetas")
        self.p_foto = mock.patch("torneos.pdf.foto_de", return_value="")
        self.p_pdf = mock.patch("torneos.pdf.generar", return_value=PDF_FALSO)
        self.p_foto.start()
        self.p_pdf.start()
        self.addCleanup(self.p_foto.stop)
        self.addCleanup(self.p_pdf.stop)

    def test_se_prepara_el_dia_1_una_vez_y_avisa(self):
        self.assertEqual(mensual.revisar(timezone.make_aware(datetime(2026, 12, 2, 9, 0))), 0)
        self.assertEqual(mensual.revisar(timezone.make_aware(datetime(2026, 12, 1, 7, 59))), 0)
        n = mensual.generar(self.mes)
        self.assertEqual(n, 2)
        self.assertEqual(mensual.generar(self.mes), 0)
        titulos = {(a.usuario_id, a.para_direccion): a.titulo for a in Aviso.objects.all()}
        self.assertIn((None, True), titulos)
        self.assertIn("1 de tu grupo", titulos[(self.u_pablo.id, False)])
        self.assertIn("1 de tu grupo", titulos[(self.u_santi.id, False)])

    def test_no_a_los_de_baja_ni_sin_torneos(self):
        self.leo.activo = False
        self.leo.save()
        Jugador.objects.create(nombre="Sin torneos", entrenador_responsable=self.blas)
        mensual.generar(self.mes)
        self.assertEqual(list(CorreoTorneos.objects.values_list("jugador__nombre", flat=True)), ["Ana Pérez"])

    def test_cada_head_coach_ve_y_valida_los_suyos(self):
        mensual.generar(self.mes)
        url = f"/api/torneos-correos/?mes={self.mes:%Y-%m}"
        self.assertEqual([f["nombre"] for f in self.api(self.u_pablo).get(url).data["filas"]], ["Ana Pérez"])
        self.assertEqual(len(self.api(self.u_dir).get(url).data["filas"]), 2)
        self.assertEqual(self.api(self.u_blas).get(url).status_code, 403)
        leo = CorreoTorneos.objects.get(jugador=self.leo)
        r = self.api(self.u_pablo).post("/api/torneos-correos/validar/", {"ids": [leo.id]}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_la_vista_previa(self):
        mensual.generar(self.mes)
        c = CorreoTorneos.objects.get(jugador=self.ana)
        r = self.api(self.u_pablo).get(f"/api/torneos-correos/{c.id}/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("Ana Pérez", r.data["asunto"])
        self.assertIn("ITF J30 Silla", r.data["html"])
        # La inscripción abierta, destacada; la que ya cerró, no.
        self.assertIn("Inscripción hasta", r.data["html"])
        self.assertIn("Inscripción cerrada", r.data["html"])
        self.assertIn("Por confirmar", r.data["html"])
        self.assertIn("Dos raquetas", r.data["html"])
        self.assertIn("◀", r.data["texto"])
        self.assertEqual(r.data["destinatarios"], [{"email": "familia.ana@x.es", "quien": "Familia"}])
        self.assertEqual(r.data["responder_a"], ["gestion@gtennis.com", "pablo@gtennis.com"])
        self.assertEqual((r.data["n_torneos"], r.data["por_confirmar"], r.data["inscripciones_abiertas"]), (2, 1, 1))

    def test_validar_congela_y_el_programador_lo_envia(self):
        mensual.generar(self.mes)
        c = CorreoTorneos.objects.get(jugador=self.ana)
        r = self.api(self.u_pablo).post("/api/torneos-correos/validar/", {"ids": [c.id]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        c.refresh_from_db()
        self.assertEqual((c.estado, c.validado_por), ("VALIDADO", self.u_pablo))
        # Lo que cambie después ya no entra en este correo.
        Participante.objects.filter(jugador=self.ana, torneo=self.otro).delete()
        self.assertEqual(mensual.enviar_validados(), 1)
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ["familia.ana@x.es"])
        self.assertEqual(m.reply_to, ["gestion@gtennis.com", "pablo@gtennis.com"])
        self.assertIn("ITF J30 Valencia", m.body)
        html = m.alternatives[0][0]
        self.assertIn("ITF J30 Valencia", html)
        self.assertEqual(m.attachments[0][1], PDF_FALSO)
        self.assertTrue(m.attachments[0][0].startswith("Torneos Ana Pérez"))
        c.refresh_from_db()
        self.assertEqual(c.estado, "ENVIADO")
        self.assertEqual(mensual.enviar_validados(), 0)

    def test_sin_correo_no_se_valida_salvo_que_se_escriba(self):
        mensual.generar(self.mes)
        c = CorreoTorneos.objects.get(jugador=self.leo)
        r = self.api(self.u_santi).post("/api/torneos-correos/validar/", {"ids": [c.id]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("no tiene correo", r.data["detail"])
        r = self.api(self.u_santi).post("/api/torneos-correos/validar/",
                                        {"ids": [c.id], "destinatarios": [{"email": "no-vale"}]}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.api(self.u_santi).post("/api/torneos-correos/validar/",
                                        {"ids": [c.id], "destinatarios": [{"email": "papa.leo@x.es", "quien": "Padre"}]},
                                        format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.leo.refresh_from_db()
        self.assertEqual(self.leo.email, "papa.leo@x.es")

    def test_en_ingles_si_la_familia_es_de_ingles(self):
        DatosInforme.objects.create(jugador=self.ana, idioma="EN")
        NormasTorneos.objects.update(texto_en="Club rules:\n- Be on time")
        mensual.generar(self.mes)
        c = CorreoTorneos.objects.get(jugador=self.ana)
        asunto, texto, html = mensual.mensaje(c)
        self.assertIn("tournaments", asunto)
        self.assertIn("Entries until", html)
        self.assertIn("Be on time", html)

    def test_un_envio_que_falla_avisa_y_se_reintenta(self):
        mensual.generar(self.mes)
        c = CorreoTorneos.objects.get(jugador=self.ana)
        self.api(self.u_pablo).post("/api/torneos-correos/validar/", {"ids": [c.id]}, format="json")
        Aviso.objects.all().delete()
        with mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("Gmail caído")):
            self.assertEqual(mensual.enviar_validados(), 0)
        c.refresh_from_db()
        self.assertEqual((c.estado, c.envio_error), ("VALIDADO", "Gmail caído"))
        self.assertEqual(Aviso.objects.get().usuario, self.u_pablo)
        self.assertEqual(mensual.enviar_validados(), 0)  # no se reintenta solo
        r = self.api(self.u_pablo).post(f"/api/torneos-correos/{c.id}/reintentar/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(mensual.enviar_validados(), 1)

    def test_sin_correo_configurado_esperan_sin_avisar(self):
        mensual.generar(self.mes)
        c = CorreoTorneos.objects.get(jugador=self.ana)
        self.api(self.u_pablo).post("/api/torneos-correos/validar/", {"ids": [c.id]}, format="json")
        Aviso.objects.all().delete()
        with override_settings(EMAIL_HOST="", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            self.assertEqual(mensual.enviar_validados(), 0)
            self.assertEqual(mensual.enviar_validados(), 0)
        c.refresh_from_db()
        self.assertEqual((c.estado, c.envio_error), ("VALIDADO", ""))
        self.assertFalse(Aviso.objects.exists())
        self.assertEqual(mensual.enviar_validados(), 1)

    def test_descartar_y_recuperar(self):
        mensual.generar(self.mes)
        c = CorreoTorneos.objects.get(jugador=self.ana)
        self.assertEqual(self.api(self.u_pablo).post(f"/api/torneos-correos/{c.id}/descartar/").data["estado"],
                         "DESCARTADO")
        self.assertEqual(mensual.enviar_validados(), 0)
        self.assertEqual(self.api(self.u_pablo).post(f"/api/torneos-correos/{c.id}/recuperar/").data["estado"],
                         "PENDIENTE")

    def test_normas_las_escribe_direccion(self):
        url = "/api/torneos-correos/normas/"
        self.assertEqual(self.api(self.u_pablo).get(url).data["puede_editar"], False)
        self.assertEqual(self.api(self.u_pablo).put(url, {"texto": "x"}, format="json").status_code, 403)
        r = self.api(self.u_dir).put(url, {"texto": "Nuevas normas"}, format="json")
        self.assertEqual((r.status_code, r.data["texto"]), (200, "Nuevas normas"))

    def test_generar_a_mano_solo_direccion(self):
        url = "/api/torneos-correos/generar/"
        self.assertEqual(self.api(self.u_pablo).post(url, {}, format="json").status_code, 403)
        r = self.api(self.u_dir).post(url, {"mes": f"{self.mes:%Y-%m}"}, format="json")
        self.assertEqual(r.data["creados"], 2)


@override_settings(EMAIL_HOST="smtp.prueba", CORREO_GMAIL="", DEFAULT_FROM_EMAIL="gestion@gtennis.com")
class CompeticionTardesTests(Base):
    """25/11/2026: quien coordina Competición de tardes (Alberto Sanz) da de
    alta torneos y lleva en ellos a los de tardes, como un head coach."""

    def setUp(self):
        super().setUp()
        from academy.models import Escuela
        from users.models import Funcion

        ct = Escuela.objects.create(nombre="Competición de tardes", solo_informes=True)
        # Los de tardes tienen la ficha inactiva y no tienen entrenador.
        self.asier = Jugador.objects.create(nombre="Asier", escuela=ct, activo=False, email="asier@x.es")
        self.u_alberto = User.objects.create_user(username="alberto.sanz", password="x", role=User.Role.ENTRENADOR,
                                                  email="alberto@gtennis.com")
        Entrenador.objects.create(nombre="Alberto Sanz", user=self.u_alberto)
        Funcion.objects.create(usuario=self.u_alberto, codigo="COORDINA_TARDES")

    def test_da_de_alta_torneos(self):
        r = self.api(self.u_alberto).post("/api/torneos/", {"nombre": "Copa Tardes", "fecha_inicio": "2027-01-10",
                                                           "fecha_fin": "2027-01-11"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.api(self.u_alberto).get("/api/auth/me/").data["lleva_torneos"], True)

    def test_apunta_a_los_de_tardes_y_espera_a_direccion(self):
        lista = self.api(self.u_alberto).get(f"/api/torneos-participantes/jugadores/?torneo={self.t.id}").data
        self.assertEqual([j["nombre"] for j in lista], ["Asier"])
        r = self.apuntar(self.u_alberto, self.asier)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["certeza"], r.data["de_baja"]), ("VALIDADO_COACH", False))
        # A los de la academia no.
        self.assertEqual(self.apuntar(self.u_alberto, self.ana).status_code, 403)
        # Lo ve dirección para el visto bueno final, y Alberto puede moverlo.
        urls = "/api/torneos-participantes/por_confirmar/"
        self.assertEqual([x["nombre"] for x in self.api(self.u_dir).get(urls).data], ["Asier"])
        self.assertEqual(self.api(self.u_alberto).patch(f"/api/torneos-participantes/{r.data['id']}/",
                                                        {"torneo": self.otro.id}, format="json").status_code, 200)

    def test_los_head_coaches_no_los_tocan(self):
        lista = self.api(self.u_pablo).get(f"/api/torneos-participantes/jugadores/?torneo={self.t.id}").data
        self.assertNotIn("Asier", [j["nombre"] for j in lista])
        self.assertEqual(self.apuntar(self.u_pablo, self.asier).status_code, 403)
        self.assertEqual(self.apuntar(self.u_dir, self.asier).status_code, 201)

    def test_dado_de_baja_en_tardes(self):
        self.asier.fecha_baja = date.today() - timedelta(days=1)
        self.asier.save()
        self.assertEqual(self.apuntar(self.u_alberto, self.asier).status_code, 400)

    def test_su_pagina_y_su_correo(self):
        Participante.objects.create(torneo=self.t, jugador=self.asier, nombre="Asier", certeza="PENDIENTE")
        r = self.api(self.u_alberto).get(f"/api/torneos/jugador/{self.asier.id}/")
        self.assertEqual((r.data["jugador"]["de_baja"], len(r.data["torneos"])), (False, 1))
        self.assertIn("Asier", [f["nombre"] for f in self.api(self.u_dir).get("/api/torneos/por_jugador/").data
                                if not f["de_baja"]])
        mes = date.today().replace(day=1)
        with mock.patch("torneos.pdf.foto_de", return_value=""), \
                mock.patch("torneos.pdf.generar", return_value=PDF_FALSO):
            mensual.generar(mes)
            c = CorreoTorneos.objects.get(jugador=self.asier)
            self.assertIn("1 de tu grupo", Aviso.objects.get(usuario=self.u_alberto).titulo)
            self.assertEqual([f["nombre"] for f in self.api(self.u_alberto).get(
                f"/api/torneos-correos/?mes={mes:%Y-%m}").data["filas"]], ["Asier"])
            # Las respuestas de la familia, a gestion@ y a quien coordina tardes.
            self.assertEqual(self.api(self.u_alberto).get(f"/api/torneos-correos/{c.id}/").data["responder_a"],
                             ["gestion@gtennis.com", "alberto@gtennis.com"])
            r = self.api(self.u_alberto).post("/api/torneos-correos/validar/", {"ids": [c.id]}, format="json")
            self.assertEqual(r.data["validados"], 1)
            self.assertEqual(mensual.enviar_validados(), 1)
        self.assertEqual(mail.outbox[0].to, ["asier@x.es"])
        # Pablo (head coach) no ve el correo de un jugador de tardes.
        self.assertEqual(self.api(self.u_pablo).get(f"/api/torneos-correos/?mes={mes:%Y-%m}").data["filas"], [])
