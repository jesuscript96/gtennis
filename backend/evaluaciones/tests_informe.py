"""El informe conjunto de Competición de tardes: tenis + físico, validación,
devolución, PDF, foto y recordatorios del ciclo (27/10/2026)."""
from datetime import timedelta
from io import BytesIO

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from academy.models import Aviso, Coach, Entrenador, Escuela, Jugador
from users.models import User

from . import catalogo, recordatorios
from .models import Evaluacion, EvaluacionFisica, Informe, RecordatorioInforme
from .tests import SIN_CAPTURA_DE_PLANTILLAS

TENIS = {k: 3 for k in catalogo.CRITERIOS}
FISICO = {k: 4 for k in catalogo.CRITERIOS_FISICO}


@SIN_CAPTURA_DE_PLANTILLAS
@override_settings(ANTHROPIC_API_KEY="", GOOGLE_SERVICE_ACCOUNT_JSON="", DRIVE_INFORMES_ID="")
class InformeTests(TestCase):
    def setUp(self):
        self.ct = Escuela.objects.create(nombre="Competición de tardes", solo_informes=True)
        self.nino = Jugador.objects.create(nombre="Asier Pérez", escuela=self.ct, activo=False, email="fam@x.com")

        def entrenador(username, nombre):
            u = User.objects.create_user(username=username, password="x", role=User.Role.ENTRENADOR)
            Entrenador.objects.create(nombre=nombre, user=u)
            return u
        self.alvaro = entrenador("alvaro.mantoan", "Alvaro Mantoan")
        self.alberto = entrenador("alberto.sanz", "Alberto Sanz")
        self.mico = entrenador("jorge.mico", "Jorge Mico")
        self.blas = entrenador("blas", "Blas")
        self.josep = User.objects.create_user(username="josep.mari", password="x", role=User.Role.PREPARADOR)
        self.ivan = User.objects.create_user(username="ivan", password="x", role=User.Role.SUPERADMIN)
        self.dani = User.objects.create_user(username="daniel.gimeno", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Dani", user=self.dani)
        self.ivan_g = User.objects.create_user(username="ivan.gallego", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Ivan Gallego", user=self.ivan_g)

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def _tenis(self, user=None):
        c = self.api(user or self.alvaro)
        r = c.post("/api/evaluaciones/", {"jugador": self.nino.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        c.patch(f"/api/evaluaciones/{r.data['id']}/", {"puntuaciones": TENIS, "fortalezas": ["Saque"],
                                                       "mejoras": ["Revés"]}, format="json")
        return r.data["id"]

    def _fisico(self):
        c = self.api(self.josep)
        r = c.post("/api/evaluaciones-fisicas/", {"jugador": self.nino.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        c.patch(f"/api/evaluaciones-fisicas/{r.data['id']}/",
                {"puntuaciones": FISICO, "textos": {"puntos_fuertes": "Rápido"}}, format="json")
        return r.data["id"]

    def test_circuito_completo(self):
        t = self._tenis()
        r = self.api(self.alvaro).post(f"/api/evaluaciones/{t}/terminar/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["informe"]["estado"], "EN_CURSO")
        f = self._fisico()
        r = self.api(self.josep).post(f"/api/evaluaciones-fisicas/{f}/terminar/", {}, format="json")
        inf = Informe.objects.get()
        self.assertEqual((inf.tenis_id, inf.fisica_id, inf.estado), (t, f, "PENDIENTE"))
        self.assertTrue(Aviso.objects.filter(usuario=self.ivan, titulo__contains="listo para validar").exists())
        self.assertTrue(Aviso.objects.filter(usuario=self.dani, titulo__contains="listo para validar").exists())
        self.assertTrue(Aviso.objects.filter(usuario=self.ivan_g, titulo__contains="listo para validar").exists())
        # Iván Gallego valida pero no evalúa tenis.
        self.assertEqual(self.api(self.ivan_g).get(f"/api/informes/{inf.id}/").data["puede_validar"], True)
        self.assertEqual(self.api(self.ivan_g).post("/api/evaluaciones/", {"jugador": self.nino.id},
                                                    format="json").status_code, 403)

        # No hay dos evaluaciones de tenis en el mismo informe: se sigue con la que hay.
        r = self.api(self.mico).post("/api/evaluaciones/", {"jugador": self.nino.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(int(r.data["existente"]), t)

        # Josep no valida.
        self.assertEqual(self.api(self.josep).post(f"/api/informes/{inf.id}/aprobar/", {}, format="json").status_code, 403)

        # Devolver: hace falta parte y nota; avisa solo al de esa parte.
        r = self.api(self.ivan).post(f"/api/informes/{inf.id}/devolver/", {"partes": ["tenis"]}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.api(self.ivan).post(f"/api/informes/{inf.id}/devolver/",
                                     {"partes": ["tenis"], "nota": "Revisa el revés"}, format="json")
        self.assertEqual(r.data["estado"], "DEVUELTO")
        self.assertTrue(Aviso.objects.filter(usuario=self.alvaro, titulo__contains="devuelto").exists())
        self.assertFalse(Aviso.objects.filter(usuario=self.josep, titulo__contains="devuelto").exists())
        r = self.api(self.alvaro).get(f"/api/evaluaciones/{t}/")
        self.assertEqual(r.data["informe"]["nota_devolucion"], "Revisa el revés")

        # Otro entrenador de tarde puede corregirlo; al terminar vuelve a pendiente.
        r = self.api(self.alberto).patch(f"/api/evaluaciones/{t}/", {"mejoras": ["Revés cortado"]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.api(self.alberto).post(f"/api/evaluaciones/{t}/terminar/", {}, format="json")
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.devuelto_partes), ("PENDIENTE", []))

        # Aprobar guarda los destinatarios para el futuro envío.
        r = self.api(self.dani).post(f"/api/informes/{inf.id}/aprobar/",
                                     {"destinatarios": [{"email": "fam@x.com", "quien": "Familia"}, {"email": " "}]},
                                     format="json")
        self.assertEqual(r.status_code, 200, r.data)
        inf.refresh_from_db()
        self.assertEqual(inf.estado, "VALIDADO")
        self.assertEqual(inf.destinatarios, [{"email": "fam@x.com", "quien": "Familia"}])
        self.assertTrue(Aviso.objects.filter(usuario=self.josep, titulo__contains="validado").exists())

        # El trimestre siguiente empieza un informe nuevo.
        t2 = self._tenis(self.mico)
        self.assertEqual(Informe.objects.count(), 2)
        self.assertEqual(Evaluacion.objects.get(pk=t2).informe.estado, "EN_CURSO")

        # Corregir una parte del ya validado lo devuelve a validar como versión 2.
        self.api(self.alvaro).post(f"/api/evaluaciones/{t}/terminar/", {}, format="json")
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.version), ("PENDIENTE", 2))

    def test_pdf_conjunto_con_la_evolucion(self):
        anterior = Informe.objects.create(
            jugador=self.nino, estado="VALIDADO", validado_en=timezone.now() - timedelta(days=90),
            tenis=Evaluacion.objects.create(jugador=self.nino, estado="TERMINADA", puntuaciones={k: 2 for k in TENIS}),
            fisica=EvaluacionFisica.objects.create(jugador=self.nino, estado="TERMINADA",
                                                   puntuaciones={k: 3 for k in FISICO}))
        t = self._tenis()
        self.api(self.alvaro).post(f"/api/evaluaciones/{t}/terminar/", {}, format="json")
        inf = Evaluacion.objects.get(pk=t).informe
        self.assertNotEqual(inf.pk, anterior.pk)
        from . import pdf
        datos = pdf.datos_informe(inf)
        self.assertIsNone(datos["fisico"])
        f = self._fisico()
        self.api(self.josep).post(f"/api/evaluaciones-fisicas/{f}/terminar/", {}, format="json")
        inf.refresh_from_db()
        datos = pdf.datos_informe(inf)
        self.assertEqual(datos["evol_media"]["dir"], "sube")
        self.assertTrue(datos["fisico"])
        html = pdf.html_informe(inf)
        self.assertIn("Josep" if "Josep" in html else "josep.mari", html)
        r = self.api(self.ivan).get(f"/api/informes/{inf.id}/pdf/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"%PDF"))

    def test_quien_ve_los_informes_y_el_panel(self):
        self.assertEqual(self.api(self.blas).get("/api/informes/").status_code, 403)
        for u in (self.alvaro, self.josep, self.ivan, self.dani):
            self.assertEqual(self.api(u).get("/api/informes/").status_code, 200, u.username)
        r = self.api(self.ivan).get("/api/informes/panel/")
        self.assertTrue(r.data["puede_validar"])
        fila = r.data["jugadores"][0]
        self.assertEqual((fila["nombre"], fila["ciclo"]["estado"], fila["informe"]), ("Asier Pérez", "primera", None))
        self._tenis()
        fila = self.api(self.josep).get("/api/informes/panel/").data["jugadores"][0]
        self.assertEqual(fila["informe"]["estado"], "EN_CURSO")
        self.assertIsNone(fila["informe"]["fisica"])

    def test_foto(self):
        from PIL import Image
        buf = BytesIO()
        Image.new("RGB", (2000, 1200), "red").save(buf, "PNG")
        buf.seek(0)
        buf.name = "foto.png"
        url = f"/api/informes/foto/{self.nino.id}/"
        self.assertEqual(self.api(self.alvaro).get(url).status_code, 404)
        r = self.api(self.alvaro).post(url, {"foto": buf}, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        r = self.api(self.josep).get(url)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        self.assertEqual(Image.open(BytesIO(r.content)).size, (900, 540))
        r = self.api(self.alvaro).post(url, {"foto": BytesIO(b"no es una imagen")}, format="multipart")
        self.assertEqual(r.status_code, 400)


class RecordatoriosTests(TestCase):
    def setUp(self):
        self.ct = Escuela.objects.create(nombre="Competición de tardes", solo_informes=True)
        self.hoy = timezone.localdate()
        self.nuevo = Jugador.objects.create(nombre="Nuevo", escuela=self.ct, activo=False,
                                            fecha_alta=self.hoy - timedelta(days=3))
        self.alvaro = User.objects.create_user(username="alvaro.mantoan", password="x", role=User.Role.ENTRENADOR)
        self.alberto = User.objects.create_user(username="alberto.sanz", password="x", role=User.Role.ENTRENADOR)
        self.josep = User.objects.create_user(username="josep.mari", password="x", role=User.Role.PREPARADOR)
        self.ivan = User.objects.create_user(username="ivan", password="x", role=User.Role.SUPERADMIN)

    def test_primer_informe_a_la_semana_del_alta_y_una_sola_vez(self):
        self.assertEqual(recordatorios.revisar(self.hoy), 0)
        self.assertEqual(recordatorios.revisar(self.hoy + timedelta(days=7)), 1)
        self.assertEqual(recordatorios.revisar(self.hoy + timedelta(days=8)), 0)
        a = Aviso.objects.get(usuario=self.alvaro)
        self.assertIn("Nuevo", a.mensaje)
        self.assertTrue(Aviso.objects.filter(usuario=self.alberto).exists())
        self.assertTrue(Aviso.objects.filter(usuario=self.josep).exists())
        self.assertFalse(Aviso.objects.filter(usuario=self.ivan).exists())

    def test_sin_alta_se_recuerda_una_vez(self):
        self.nuevo.fecha_alta = None
        self.nuevo.save()
        self.assertEqual(recordatorios.revisar(self.hoy), 1)
        self.assertEqual(recordatorios.revisar(self.hoy + timedelta(days=1)), 0)

    def test_75_y_90_dias_desde_la_validacion(self):
        validado = timezone.now() - timedelta(days=76)
        ev = Evaluacion.objects.create(jugador=self.nuevo, evaluador=self.alberto, estado="TERMINADA")
        Informe.objects.create(jugador=self.nuevo, tenis=ev, estado="VALIDADO", validado_en=validado)
        self.assertEqual(recordatorios.revisar(self.hoy), 1)
        # El de tenis es quien lo hizo; sin parte física, los preparadores.
        self.assertTrue(Aviso.objects.filter(usuario=self.alberto, titulo__contains="pronto").exists())
        self.assertFalse(Aviso.objects.filter(usuario=self.alvaro).exists())
        self.assertTrue(Aviso.objects.filter(usuario=self.josep).exists())
        self.assertEqual(recordatorios.revisar(self.hoy + timedelta(days=14)), 1)
        self.assertTrue(Aviso.objects.filter(usuario=self.ivan, titulo__contains="vencido").exists())
        self.assertEqual(RecordatorioInforme.objects.count(), 2)

    def test_no_recuerda_si_ya_esta_en_marcha(self):
        Informe.objects.create(jugador=self.nuevo, tenis=Evaluacion.objects.create(jugador=self.nuevo))
        self.assertEqual(recordatorios.revisar(self.hoy + timedelta(days=10)), 0)
