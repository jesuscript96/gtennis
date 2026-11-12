"""Informes de Alto rendimiento (12/11/2026): el entrenador evalúa el tenis de
su grupo y el head coach todo su color, sin reparto; lo valida dirección; el
PDF va a su carpeta del Drive del club; foto y recordatorios como en tardes."""
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

TENIS = {k: 3 for k in catalogo.CRITERIOS}


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
    def test_lo_valida_direccion_y_nadie_mas(self):
        ev_id = self.evaluar(self.u_blas, self.ana)
        inf = Informe.objects.get(jugador=self.ana)
        self.assertEqual((inf.circuito, inf.estado, inf.tenis_id), ("alto_rendimiento", "PENDIENTE", ev_id))
        listo = Aviso.objects.filter(titulo__contains="listo para validar")
        self.assertEqual(set(listo.values_list("usuario__username", flat=True)), {"dir"})
        self.assertIn("Blas", listo.get().mensaje)
        # Ni el head coach, ni quien valida tardes, ni el autor.
        for u in (self.u_dani, self.valida, self.u_blas):
            r = self.api(u).post(f"/api/informes/{inf.id}/aprobar/", {}, format="json")
            self.assertIn(r.status_code, (403, 404), u.username)
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
        r = d.post(f"/api/informes/{inf.id}/aprobar/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.validado_por), ("VALIDADO", self.dir))
        self.assertTrue(Aviso.objects.filter(usuario=self.u_blas, titulo__contains="validado").exists())

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
