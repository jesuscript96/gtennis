"""Informes de Alto rendimiento (12/11/2026): el entrenador evalúa el tenis de
su grupo y el head coach todo su color, sin reparto, del 1 al 10; lo validan
dirección y el head coach de su color; el PDF va a su carpeta del Drive del
club; foto y recordatorios como en tardes."""
from datetime import timedelta
from io import BytesIO
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from academy.models import Aviso, Coach, Entrenador, Escuela, Invitado, Jugador
from users.models import Funcion, User

from . import catalogo, drive, pdf, recordatorios
from .models import Evaluacion, Informe
from .tests import SIN_CAPTURA_DE_PLANTILLAS, FakeDrive, FakeResp

TENIS = {k: 7 for k in catalogo.CRITERIOS}
FISICA = {k: 4 for k in catalogo.CRITERIOS_FISICO}


class Base(TestCase):
    """Dos colores: amarillo (head coach Dani; Blas y Javi) y turquesa (head
    coach Pablo; Mario). Dirección, alguien con «Valida informes» (tardes) y
    un jugador de Competición de tardes."""

    def setUp(self):
        self.dir = User.objects.create_user(username="dir", password="x", role=User.Role.SUPERADMIN)
        self.valida = User.objects.create_user(username="valida", password="x", role=User.Role.ENTRENADOR)
        Funcion.objects.create(usuario=self.valida, codigo="VALIDA_INFORMES")
        self.u_dani = User.objects.create_user(username="dani", password="x", role=User.Role.COACH)
        self.u_pablo = User.objects.create_user(username="pablo", password="x", role=User.Role.COACH)
        self.u_blas, self.blas = self._entrenador("blas", "Blas")
        self.u_javi, self.javi = self._entrenador("javi", "Javi")
        self.u_mario, self.mario = self._entrenador("mario", "Mario")
        amarillo = Coach.objects.create(nombre="Dani", color="amarillo", user=self.u_dani)
        amarillo.entrenadores.set([self.blas, self.javi])
        turquesa = Coach.objects.create(nombre="Pablo", color="turquesa", user=self.u_pablo)
        turquesa.entrenadores.set([self.mario])
        ar, _ = Escuela.objects.get_or_create(nombre="Alto Rendimiento")
        self.ana = Jugador.objects.create(nombre="Ana Blas", escuela=ar, entrenador_responsable=self.blas)
        self.bea = Jugador.objects.create(nombre="Bea Javi", escuela=ar, entrenador_responsable=self.javi)
        self.leo = Jugador.objects.create(nombre="Leo Mario", escuela=ar, entrenador_responsable=self.mario)
        ct, _ = Escuela.objects.update_or_create(nombre="Competición de tardes", defaults={"solo_informes": True})
        self.nino = Jugador.objects.create(nombre="Nino Tardes", escuela=ct, activo=False,
                                           entrenador_responsable=self.blas)

    def _entrenador(self, username, nombre):
        u = User.objects.create_user(username=username, password="x", role=User.Role.ENTRENADOR)
        return u, Entrenador.objects.create(nombre=nombre, user=u)

    def api(self, user):
        c = APIClient()
        c.force_authenticate(User.objects.get(pk=user.pk))
        return c

    def evaluar(self, user, jugador):
        """Crea y termina una evaluación de tenis; devuelve su id."""
        c = self.api(user)
        r = c.post("/api/evaluaciones/", {"jugador": jugador.id}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        ev_id = r.json()["id"]
        c.patch(f"/api/evaluaciones/{ev_id}/", {"puntuaciones": TENIS, "fortalezas_original": ["Saque"],
                                               "mejoras_original": ["Revés"]}, format="json")
        r = c.post(f"/api/evaluaciones/{ev_id}/terminar/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return ev_id


@SIN_CAPTURA_DE_PLANTILLAS
@override_settings(ANTHROPIC_API_KEY="", GOOGLE_SERVICE_ACCOUNT_JSON="", DRIVE_INFORMES_ID="")
class QuienEvaluaTests(Base):
    def _puede(self, user):
        # Las migraciones cargan además los alumnos reales: solo cuentan los de la prueba.
        nuestros = {"Ana Blas", "Bea Javi", "Leo Mario"}
        return [j["nombre"] for j in self.api(user).get("/api/evaluaciones/jugadores/").json()
                if not j["solo_informes"] and j["nombre"] in nuestros]

    def test_el_entrenador_su_grupo_y_el_head_coach_su_color(self):
        self.assertEqual(self._puede(self.u_blas), ["Ana Blas"])
        self.assertEqual(self._puede(self.u_dani), ["Ana Blas", "Bea Javi"])
        self.assertEqual(self._puede(self.u_pablo), ["Leo Mario"])
        self.assertEqual(self._puede(self.dir), ["Ana Blas", "Bea Javi", "Leo Mario"])
        # Crear: su grupo sí; el de un compañero de color o de otro color, no.
        c = self.api(self.u_blas)
        self.assertEqual(c.post("/api/evaluaciones/", {"jugador": self.ana.id}, format="json").status_code, 201)
        for j in (self.bea, self.leo):
            self.assertEqual(c.post("/api/evaluaciones/", {"jugador": j.id}, format="json").status_code, 403)
        self.assertEqual(self.api(self.u_dani).post("/api/evaluaciones/", {"jugador": self.bea.id},
                                                    format="json").status_code, 201)
        self.assertEqual(self.api(self.u_dani).post("/api/evaluaciones/", {"jugador": self.leo.id},
                                                    format="json").status_code, 403)

    def test_gestion_compartida_si_entrenarle_no(self):
        from academy.models import ResponsableJugador

        ResponsableJugador.objects.create(jugador=self.bea, entrenador=self.blas, prioridad=2)
        self.assertEqual(self._puede(self.u_blas), ["Ana Blas"])
        self.bea.cogestores.add(self.blas)
        self.assertEqual(self._puede(self.u_blas), ["Ana Blas", "Bea Javi"])

    def test_ni_invitados_ni_tardes_ni_bajas(self):
        kira = Jugador.objects.create(nombre="Kira (invitado)", entrenador_responsable=self.blas)
        Invitado.objects.create(nombre="Kira", entrenador_solicitante=self.blas, jugador_creado=kira)
        Jugador.objects.create(nombre="Baja Blas", entrenador_responsable=self.blas, activo=False)
        nombres = [j["nombre"] for j in self.api(self.u_blas).get("/api/evaluaciones/jugadores/").json()
                   if not j["solo_informes"]]
        self.assertEqual(nombres, ["Ana Blas"])

    def test_cada_uno_ve_las_de_su_grupo_y_las_suyas(self):
        mia = self.evaluar(self.u_blas, self.ana)
        de_javi = self.evaluar(self.u_javi, self.bea)
        self.evaluar(self.u_mario, self.leo)

        def ve(u):
            return sorted(e["jugador_nombre"] for e in self.api(u).get("/api/evaluaciones/").json())

        self.assertEqual(ve(self.u_blas), ["Ana Blas"])
        self.assertEqual(ve(self.u_dani), ["Ana Blas", "Bea Javi"])
        self.assertEqual(ve(self.dir), ["Ana Blas", "Bea Javi", "Leo Mario"])
        self.assertEqual(self.api(self.u_blas).get(f"/api/evaluaciones/{de_javi}/").status_code, 404)
        # Si Ana cambia de grupo, Blas sigue viendo la que hizo él.
        self.ana.entrenador_responsable = self.javi
        self.ana.save()
        self.assertEqual(self.api(self.u_blas).get(f"/api/evaluaciones/{mia}/").status_code, 200)
        # Quien valida los de tardes no ve las de Alto rendimiento.
        self.assertEqual(ve(self.valida), [])


@SIN_CAPTURA_DE_PLANTILLAS
@override_settings(ANTHROPIC_API_KEY="", GOOGLE_SERVICE_ACCOUNT_JSON="", DRIVE_INFORMES_ID="")
class ValidaDireccionTests(Base):
    def test_lo_validan_direccion_y_el_head_coach_de_su_color(self):
        ev_id = self.evaluar(self.u_blas, self.ana)
        inf = Informe.objects.get(jugador=self.ana)
        self.assertEqual((inf.circuito, inf.estado, inf.tenis_id), ("alto_rendimiento", "PENDIENTE", ev_id))
        listo = Aviso.objects.filter(titulo__contains="listo para validar")
        self.assertEqual(set(listo.values_list("usuario__username", flat=True)), {"dir", "dani"})
        self.assertIn("Blas", listo.first().mensaje)
        # Ni el head coach de otro color, ni quien valida tardes, ni el autor.
        for u in (self.u_pablo, self.valida, self.u_blas):
            r = self.api(u).post(f"/api/informes/{inf.id}/aprobar/", {}, format="json")
            self.assertIn(r.status_code, (403, 404), u.username)
        # Dani lo ve en su «Por validar» y puede validarlo; Pablo no lo ve.
        r = self.api(self.u_dani).get("/api/informes/", {"estado": "PENDIENTE"}).json()
        self.assertEqual([(i["jugador_nombre"], i["puede_validar"]) for i in r], [("Ana Blas", True)])
        self.assertEqual(self.api(self.u_pablo).get("/api/informes/", {"estado": "PENDIENTE"}).json(), [])
        # Dirección lo devuelve: le llega a Blas con la nota y puede corregirla.
        d = self.api(self.dir)
        r = d.post(f"/api/informes/{inf.id}/devolver/", {"partes": ["tenis"], "nota": "Más detalle en el revés"},
                   format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(Aviso.objects.filter(usuario=self.u_blas, titulo__contains="devuelto").exists())
        ev = self.api(self.u_blas).get(f"/api/evaluaciones/{ev_id}/").json()
        self.assertEqual((ev["informe"]["estado"], ev["informe"]["nota_devolucion"]),
                         ("DEVUELTO", "Más detalle en el revés"))
        self.assertEqual(self.api(self.u_blas).post(f"/api/evaluaciones/{ev_id}/terminar/", {}, format="json")
                         .status_code, 200)
        inf.refresh_from_db()
        self.assertEqual(inf.estado, "PENDIENTE")
        # Esta vez lo aprueba el head coach de su color.
        r = self.api(self.u_dani).post(f"/api/informes/{inf.id}/aprobar/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.validado_por), ("VALIDADO", self.u_dani))
        self.assertTrue(Aviso.objects.filter(usuario=self.u_blas, titulo__contains="validado").exists())

    def test_el_head_coach_entra_en_informes_sin_ver_tardes(self):
        me = self.api(self.u_pablo).get("/api/auth/me/").json()
        self.assertEqual((me["ve_informes"], me["ve_tardes"], me["valida_alto_rendimiento"]), (True, False, True))
        panel = self.api(self.u_pablo).get("/api/informes/panel/").json()
        self.assertEqual((panel["jugadores"], panel["ve_tardes"], panel["puede_validar"]), ([], False, True))
        # Un entrenador sin más sigue sin entrar.
        self.assertEqual(self.api(self.u_blas).get("/api/informes/panel/").status_code, 403)

    def test_tardes_sigue_con_quien_valida(self):
        from .models import EvaluacionFisica

        tenis = Evaluacion.objects.create(jugador=self.nino, evaluador=self.u_blas, estado="TERMINADA")
        fisica = EvaluacionFisica.objects.create(jugador=self.nino, estado="TERMINADA")
        inf = Informe.objects.create(jugador=self.nino, tenis=tenis, fisica=fisica, estado="PENDIENTE")
        r = self.api(self.valida).post(f"/api/informes/{inf.id}/aprobar/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_una_empezada_antes_entra_al_terminarla(self):
        """Las de Alto rendimiento empezadas antes del circuito no tienen
        informe: al terminarlas se cuelgan de uno y pasan a validar."""
        ev = Evaluacion.objects.create(jugador=self.ana, evaluador=self.u_blas, nombre_evaluador="Blas",
                                       puntuaciones=TENIS, fortalezas_original=["Saque"],
                                       mejoras_original=["Revés"])
        r = self.api(self.u_blas).post(f"/api/evaluaciones/{ev.id}/terminar/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Informe.objects.get(jugador=self.ana).estado, "PENDIENTE")

    def test_pdf_de_alto_rendimiento_con_su_cabecera(self):
        self.evaluar(self.u_blas, self.ana)
        inf = Informe.objects.get(jugador=self.ana)
        datos = pdf.datos_informe(inf)
        self.assertEqual(datos["t"]["academia"], "Alto rendimiento")
        self.assertIsNone(datos["fisico"])
        # Del 1 al 10: diez segmentos, textos y anillos con su escala.
        self.assertEqual(datos["escala"], 10)
        self.assertEqual(len(datos["bloques"][0]["criterios"][0]["segmentos"]), 10)
        self.assertIn("del 1 al 10", datos["t"]["escala_corta"])
        self.assertEqual(datos["bloques"][0]["ancho"], "70.0")
        # La portada destaca lo que escribió el entrenador.
        self.assertEqual(datos["punto_fuerte"]["texto"], "Saque")
        self.assertEqual(datos["a_trabajar"]["texto"], "Revés")


class EscalaTests(Base):
    def test_del_1_al_10_en_alto_rendimiento_y_en_tardes(self):
        c = self.api(self.u_blas)
        ar = c.post("/api/evaluaciones/", {"jugador": self.ana.id}, format="json").json()
        self.assertEqual(ar["escala"], 10)
        url = f"/api/evaluaciones/{ar['id']}/"
        self.assertEqual(c.patch(url, {"puntuaciones": {"drive_impact": 10}}, format="json").status_code, 200)
        self.assertEqual(c.patch(url, {"puntuaciones": {"drive_impact": 11}}, format="json").status_code, 400)
        # Tardes, también del 1 al 10 desde el 25/11/2026.
        ct = self.api(self.dir).post("/api/evaluaciones/", {"jugador": self.nino.id}, format="json").json()
        self.assertEqual(ct["escala"], 10)
        url = f"/api/evaluaciones/{ct['id']}/"
        self.assertEqual(self.api(self.dir).patch(url, {"puntuaciones": {"drive_impact": 10}}, format="json")
                         .status_code, 200)
        self.assertEqual(self.api(self.dir).patch(url, {"puntuaciones": {"drive_impact": 11}}, format="json")
                         .status_code, 400)

    @SIN_CAPTURA_DE_PLANTILLAS
    @override_settings(ANTHROPIC_API_KEY="", GOOGLE_SERVICE_ACCOUNT_JSON="", DRIVE_INFORMES_ID="")
    def test_la_evolucion_compara_en_la_misma_escala(self):
        """Un informe anterior del 1 al 5 se lleva al 1 al 10 para comparar."""
        antes = Evaluacion.objects.create(jugador=self.ana, evaluador=self.u_blas, escala=5, estado="TERMINADA",
                                          puntuaciones={k: 3 for k in catalogo.CRITERIOS})
        Informe.objects.create(jugador=self.ana, tenis=antes, estado="VALIDADO",
                               validado_en=timezone.now() - timedelta(days=90))
        self.evaluar(self.u_blas, self.ana)  # todo a 7 sobre 10
        datos = pdf.datos_informe(Informe.objects.get(jugador=self.ana, estado="PENDIENTE"))
        self.assertEqual(datos["evol_media"]["dir"], "sube")  # 6 → 7, no 3 → 7
        self.assertEqual(datos["evol_media"]["txt"], "▲ 1,0")


@override_settings(ANTHROPIC_API_KEY="", GOOGLE_SERVICE_ACCOUNT_JSON="", DRIVE_INFORMES_ID="")
class BorrarTests(Base):
    @SIN_CAPTURA_DE_PLANTILLAS
    def test_borrar_la_evaluacion_borra_su_informe_y_su_pdf(self):
        ev_id = self.evaluar(self.u_blas, self.ana)
        inf = Informe.objects.get(jugador=self.ana)
        inf.drive_file_id = "pdf-en-drive"
        inf.save()
        with mock.patch.object(drive, "a_la_papelera") as papelera:
            r = self.api(self.dir).delete(f"/api/evaluaciones/{ev_id}/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Informe.objects.filter(pk=inf.pk).exists())
        papelera.assert_called_once_with("pdf-en-drive")


@override_settings(ANTHROPIC_API_KEY="", GOOGLE_SERVICE_ACCOUNT_JSON="", DRIVE_INFORMES_ID="")
class FotoTests(Base):
    def _foto(self):
        from PIL import Image
        buf = BytesIO()
        Image.new("RGB", (1200, 1200), "blue").save(buf, "PNG")
        buf.seek(0)
        buf.name = "foto.png"
        return buf

    def test_la_sube_quien_le_evalua(self):
        url = f"/api/informes/foto/{self.ana.id}/"
        self.assertEqual(self.api(self.u_blas).post(url, {"foto": self._foto()}, format="multipart").status_code, 200)
        self.assertEqual(self.api(self.u_dani).get(url)["Content-Type"], "image/jpeg")
        # El de otro grupo, no.
        self.assertEqual(self.api(self.u_javi).post(url, {"foto": self._foto()}, format="multipart").status_code, 403)
        self.assertEqual(self.api(self.u_pablo).get(url).status_code, 403)
        # Y el PDF la usa.
        self.evaluar(self.u_blas, self.ana)
        self.assertTrue(pdf.datos_informe(Informe.objects.get(jugador=self.ana))["foto"].startswith("data:image/jpeg"))


class RecordatoriosAltoRendimientoTests(Base):
    def test_sin_aviso_inicial_y_lo_vencido_a_direccion(self):
        hoy = timezone.localdate()
        self.nino.delete()  # los de tardes tienen su propio aviso del primer informe
        # Sin informe validado no se recuerda nada (el club no quiere aviso inicial).
        self.assertEqual(recordatorios.revisar(hoy), 0)
        ev = Evaluacion.objects.create(jugador=self.ana, evaluador=self.u_blas, estado="TERMINADA")
        Informe.objects.create(jugador=self.ana, tenis=ev, estado="VALIDADO",
                               validado_en=timezone.now() - timedelta(days=76))
        self.assertEqual(recordatorios.revisar(hoy), 1)
        self.assertTrue(Aviso.objects.filter(usuario=self.u_blas, titulo__contains="pronto").exists())
        self.assertIn("Rendimiento → Evaluaciones", Aviso.objects.get(usuario=self.u_blas).mensaje)
        self.assertFalse(Aviso.objects.filter(usuario=self.dir).exists())
        self.assertEqual(recordatorios.revisar(hoy + timedelta(days=14)), 1)
        self.assertTrue(Aviso.objects.filter(usuario=self.dir, titulo__contains="vencido").exists())
        self.assertFalse(Aviso.objects.filter(usuario=self.valida).exists())


@override_settings(GOOGLE_SERVICE_ACCOUNT_JSON="{}", DRIVE_INFORMES_ID="", DRIVE_CT_USUARIO="gestion@gtennis.com",
                   DRIVE_AR_RUTA="GTENNIS 2.0 - OPERACIONES › Gestion deportiva › Alto rendimiento › 26/27 › "
                                 "Seguimiento y evaluaciones")
class DriveAltoRendimientoTests(Base):
    """En «Mi unidad» de gestion@, dentro de «Gestion deportiva › Alto
    rendimiento», que ya existe; lo de debajo lo crea la app."""

    def _sesion(self, arbol):
        class Sesion(FakeDrive):
            def get(self, url, params=None):
                q = (params or {}).get("q", "")
                if q:
                    padre = q.split("'")[1]
                    return FakeResp({"files": [{"id": i, "name": n} for i, n in arbol.get(padre, [])]})
                return super().get(url, params)
        return Sesion()

    def test_crea_su_seccion_bajo_alto_rendimiento(self):
        arbol = {"root": [("a", "GTENNIS 2.0 - OPERACIONES")], "a": [("b", "Gestion deportiva")],
                 "b": [("c", "Competicion tardes"), ("d", "Alto rendimiento")],
                 "d": [("e", "Jugadores activos"), ("f", "Metodologia")]}
        s = self._sesion(arbol)
        drive._carpeta_ar(s, "pendientes")
        # «26/27», «Seguimiento y evaluaciones» y «Por validar».
        self.assertEqual(len(s.creados), 3)
        # Sin «Alto rendimiento» no se inventa la ruta: avisa.
        from .models import CarpetaDrive
        CarpetaDrive.objects.all().delete()
        arbol["b"] = [("c", "Competicion tardes")]
        with self.assertRaises(drive.DriveNoDisponible):
            drive._carpeta_ar(self._sesion(arbol), "validados")

    @SIN_CAPTURA_DE_PLANTILLAS
    def test_el_informe_va_a_su_carpeta(self):
        with mock.patch.object(drive, "_sesion", side_effect=drive.DriveNoDisponible("sin red en la prueba")):
            self.evaluar(self.u_blas, self.ana)
        inf = Informe.objects.get(jugador=self.ana)
        with mock.patch.object(drive, "_sesion", return_value=FakeDrive()), \
                mock.patch.object(drive, "_carpeta_ar", return_value="carpeta-ar") as ar, \
                mock.patch.object(drive, "_carpeta_ct") as ct, \
                mock.patch.object(pdf, "generar_informe", return_value=b"%PDF"):
            drive.subir_informe(inf)
        ar.assert_called_once()
        ct.assert_not_called()
        self.assertEqual(inf.drive_carpeta, "pendientes")


@SIN_CAPTURA_DE_PLANTILLAS
@override_settings(ANTHROPIC_API_KEY="", GOOGLE_SERVICE_ACCOUNT_JSON="", DRIVE_INFORMES_ID="")
class FisicaAltoRendimientoTests(Base):
    """17/11/2026: la parte física también para Alto rendimiento. Se suma al
    informe de tenis (no hace falta para validarlo, pero si se empieza hay que
    terminarla) y sale en el mismo PDF."""

    def setUp(self):
        super().setUp()
        self.josep = User.objects.create_user(username="josep.mari", password="x", role=User.Role.PREPARADOR)

    def fisica(self, jugador, terminar=True):
        c = self.api(self.josep)
        r = c.post("/api/evaluaciones-fisicas/", {"jugador": jugador.id}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        ev_id = r.json()["id"]
        if terminar:
            c.patch(f"/api/evaluaciones-fisicas/{ev_id}/", {"puntuaciones": FISICA}, format="json")
            r = c.post(f"/api/evaluaciones-fisicas/{ev_id}/terminar/", {}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
        return ev_id

    def test_la_fisica_se_suma_al_informe_pendiente_y_al_pdf(self):
        self.evaluar(self.u_blas, self.ana)
        inf = Informe.objects.get(jugador=self.ana)
        self.assertEqual(inf.estado, "PENDIENTE")
        self.assertIsNone(pdf.datos_informe(inf)["fisico"])
        fis_id = self.fisica(self.ana)
        inf.refresh_from_db()
        # Sigue siendo el mismo informe, pendiente, ahora con la física.
        self.assertEqual((inf.estado, inf.fisica_id), ("PENDIENTE", fis_id))
        self.assertEqual(Informe.objects.filter(jugador=self.ana).count(), 1)
        datos = pdf.datos_informe(inf)
        self.assertEqual(datos["fisico"]["evaluador"], "josep.mari")
        self.assertIn("josep.mari", pdf.html_informe(inf))
        # Quien valida se entera de que el PDF ya la lleva.
        avisos = Aviso.objects.filter(titulo__contains="parte física terminada")
        self.assertEqual(set(avisos.values_list("usuario__username", flat=True)), {"dir", "dani"})

    def test_quien_hizo_la_fisica_ve_el_informe_y_un_entrenador_no_la_ve(self):
        self.evaluar(self.u_blas, self.ana)
        self.fisica(self.ana)
        ver = self.api(self.josep).get("/api/informes/").json()
        self.assertEqual([i["jugador_nombre"] for i in ver], ["Ana Blas"])
        self.assertEqual(self.api(self.u_blas).get("/api/evaluaciones-fisicas/").status_code, 403)
        # En el desplegable salen los de las dos escuelas.
        lista = self.api(self.josep).get("/api/evaluaciones-fisicas/jugadores/").json()
        self.assertEqual({j["nombre"]: j["solo_informes"] for j in lista if j["nombre"] in ("Ana Blas", "Nino Tardes")},
                         {"Ana Blas": False, "Nino Tardes": True})

    def test_a_medias_no_sale_en_el_pdf_ni_deja_aprobar(self):
        self.evaluar(self.u_blas, self.ana)
        inf = Informe.objects.get(jugador=self.ana)
        fis_id = self.fisica(self.ana, terminar=False)
        inf.refresh_from_db()
        self.assertIsNone(pdf.datos_informe(inf)["fisico"])
        r = self.api(self.dir).post(f"/api/informes/{inf.id}/aprobar/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("física", r.json()["detail"])
        c = self.api(self.josep)
        c.patch(f"/api/evaluaciones-fisicas/{fis_id}/", {"puntuaciones": FISICA}, format="json")
        self.assertEqual(c.post(f"/api/evaluaciones-fisicas/{fis_id}/terminar/", {}, format="json").status_code, 200)
        r = self.api(self.dir).post(f"/api/informes/{inf.id}/aprobar/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        inf.refresh_from_db()
        self.assertEqual(inf.estado, "VALIDADO")
        # Aprobado, la física ya no se toca sin reabrir.
        r = c.patch(f"/api/evaluaciones-fisicas/{fis_id}/", {"textos": {"notas_fisio": "tarde"}}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_sin_fisica_se_valida_como_siempre(self):
        self.evaluar(self.u_blas, self.ana)
        inf = Informe.objects.get(jugador=self.ana)
        r = self.api(self.dir).post(f"/api/informes/{inf.id}/aprobar/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_terminar_la_fisica_no_da_por_corregido_el_tenis(self):
        self.evaluar(self.u_blas, self.ana)
        inf = Informe.objects.get(jugador=self.ana)
        r = self.api(self.dir).post(f"/api/informes/{inf.id}/devolver/", {"partes": ["tenis"], "nota": "Revés"},
                                    format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.fisica(self.ana)
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.devuelto_partes), ("DEVUELTO", ["tenis"]))

    def test_primero_la_fisica_y_luego_el_tenis(self):
        fis_id = self.fisica(self.ana)
        inf = Informe.objects.get(jugador=self.ana)
        self.assertEqual((inf.estado, inf.tenis_id, inf.fisica_id), ("EN_CURSO", None, fis_id))
        self.evaluar(self.u_blas, self.ana)
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.fisica_id), ("PENDIENTE", fis_id))
        self.assertEqual(Informe.objects.filter(jugador=self.ana).count(), 1)


@SIN_CAPTURA_DE_PLANTILLAS
@override_settings(ANTHROPIC_API_KEY="", GOOGLE_SERVICE_ACCOUNT_JSON="", DRIVE_INFORMES_ID="")
class InformeEnEspanolYEnInglesTests(Base):
    """17/11/2026: si la familia recibe el informe en inglés, quien lo hace
    también lo tiene en español (en la app y en Drive)."""

    def setUp(self):
        super().setUp()
        from .models import DatosInforme
        self.evaluar(self.u_blas, self.ana)
        self.inf = Informe.objects.get(jugador=self.ana)
        DatosInforme.objects.update_or_create(jugador=self.ana, defaults={"idioma": "EN"})
        self.ana.refresh_from_db()

    def _guardar(self, estado):
        self.inf.estado = estado
        self.inf.save()
        subidas = []

        def subir(inf, idioma="ES", copia_es=False):
            subidas.append((idioma, copia_es))
            if copia_es:
                inf.drive_file_id_es, inf.drive_url_es = "es1", "https://drive/es"
            else:
                inf.drive_file_id, inf.drive_url, inf.drive_carpeta = "main1", "https://drive/main", "x"

        with mock.patch.object(drive, "configurado", return_value=True), \
                mock.patch.object(drive, "subir_informe", side_effect=subir), \
                mock.patch.object(drive, "a_la_papelera") as papelera, \
                mock.patch("evaluaciones.traduccion.tenis"):
            from . import informes
            aviso = informes.guardar_en_drive(self.inf)
        return subidas, papelera, aviso

    def test_validado_en_ingles_deja_tambien_la_copia_en_espanol(self):
        subidas, papelera, aviso = self._guardar(Informe.Estado.VALIDADO)
        self.assertEqual(subidas, [("EN", False), ("ES", True)])
        self.assertIsNone(aviso)
        self.inf.refresh_from_db()
        self.assertEqual((self.inf.drive_file_id_es, self.inf.drive_url_es), ("es1", "https://drive/es"))
        papelera.assert_not_called()

    def test_pendiente_va_solo_en_espanol_y_quita_la_copia_vieja(self):
        self.inf.drive_file_id_es, self.inf.drive_url_es = "es-viejo", "https://drive/viejo"
        self.inf.save()
        subidas, papelera, _ = self._guardar(Informe.Estado.PENDIENTE)
        self.assertEqual(subidas, [("ES", False)])
        papelera.assert_called_once_with("es-viejo")
        self.inf.refresh_from_db()
        self.assertEqual((self.inf.drive_file_id_es, self.inf.drive_url_es), ("", ""))

    def test_si_falla_la_copia_se_avisa_sin_perder_el_informe(self):
        self.inf.estado = Informe.Estado.VALIDADO
        self.inf.save()

        def subir(inf, idioma="ES", copia_es=False):
            if copia_es:
                raise drive.DriveNoDisponible("No se ha podido guardar en Drive.")
            inf.drive_file_id, inf.drive_url, inf.drive_carpeta = "main1", "https://drive/main", "validados"

        with mock.patch.object(drive, "configurado", return_value=True), \
                mock.patch.object(drive, "subir_informe", side_effect=subir), \
                mock.patch("evaluaciones.traduccion.tenis"):
            from . import informes
            aviso = informes.guardar_en_drive(self.inf)
        self.assertIn("copia en español", aviso)
        self.inf.refresh_from_db()
        self.assertEqual(self.inf.drive_file_id, "main1")

    @override_settings(GOOGLE_SERVICE_ACCOUNT_JSON="{}", DRIVE_CT_USUARIO="gestion@gtennis.com")
    def test_la_copia_es_otro_fichero_en_la_misma_carpeta(self):
        fake = FakeDrive()
        with mock.patch.object(drive, "_sesion", return_value=fake), \
                mock.patch.object(drive, "_carpeta_ar", return_value="carpeta-ar"), \
                mock.patch.object(pdf, "generar_informe", return_value=b"%PDF"):
            drive.subir_informe(self.inf, "EN")
            drive.subir_informe(self.inf, "ES", copia_es=True)
        self.assertEqual(len(fake.creados), 2)
        self.assertNotEqual(self.inf.drive_file_id, self.inf.drive_file_id_es)
        self.assertTrue(self.inf.drive_file_id and self.inf.drive_file_id_es)

    def test_el_pdf_de_la_evaluacion_se_pide_en_cada_idioma(self):
        ev = self.inf.tenis
        c = self.api(self.u_blas)
        with mock.patch.object(pdf, "generar_informe", return_value=b"%PDF"):
            es = c.get(f"/api/evaluaciones/{ev.id}/pdf/", {"idioma": "ES"})
            en = c.get(f"/api/evaluaciones/{ev.id}/pdf/", {"idioma": "EN"})
        self.assertIn("-ES.pdf", es["Content-Disposition"])
        self.assertIn("-EN.pdf", en["Content-Disposition"])

    def test_el_informe_enseña_los_dos_enlaces_de_drive(self):
        self.inf.drive_url, self.inf.drive_url_es = "https://drive/en", "https://drive/es"
        self.inf.save()
        d = self.api(self.dir).get(f"/api/informes/{self.inf.id}/").json()
        self.assertEqual((d["drive_url"], d["drive_url_es"]), ("https://drive/en", "https://drive/es"))
