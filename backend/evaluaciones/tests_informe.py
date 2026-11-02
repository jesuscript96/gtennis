"""El informe conjunto de Competición de tardes: tenis + físico, validación,
devolución, PDF, foto y recordatorios del ciclo (27/10/2026)."""
from datetime import timedelta
from io import BytesIO
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from academy.models import Aviso, Coach, Entrenador, Escuela, Jugador
from users.models import User

from . import catalogo, drive, ia, pdf, recordatorios
from . import informes as informes_mod
from .models import (
    AsignacionInforme, DatosInforme, Evaluacion, EvaluacionFisica, Informe, MiembroTardes, RecordatorioInforme,
)
from .tests import SIN_CAPTURA_DE_PLANTILLAS, FakeDrive, FakeResp

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
        self.salva = entrenador("salva.barcala", "Salva Barcala")
        self.mico = entrenador("jorge.mico", "Jorge Mico")
        self.blas = entrenador("blas", "Blas")
        self.josep = User.objects.create_user(username="josep.mari", password="x", role=User.Role.PREPARADOR)
        self.ivan = User.objects.create_user(username="ivan", password="x", role=User.Role.SUPERADMIN)
        self.dani = User.objects.create_user(username="daniel.gimeno", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Dani", user=self.dani)
        self.ivan_g = User.objects.create_user(username="ivan.gallego", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Ivan Gallego", user=self.ivan_g)
        MiembroTardes.objects.create(usuario=self.salva, funcion="TENIS")
        MiembroTardes.objects.create(usuario=self.josep, funcion="FISICO")

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def _tenis(self, user=None):
        c = self.api(user or self.salva)
        r = c.post("/api/evaluaciones/", {"jugador": self.nino.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        c.patch(f"/api/evaluaciones/{r.data['id']}/", {"puntuaciones": TENIS, "fortalezas_original": ["Saque"],
                                                       "mejoras_original": ["Revés"]}, format="json")
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
        r = self.api(self.salva).post(f"/api/evaluaciones/{t}/terminar/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["informe"]["estado"], "EN_CURSO")
        f = self._fisico()
        r = self.api(self.josep).post(f"/api/evaluaciones-fisicas/{f}/terminar/", {}, format="json")
        inf = Informe.objects.get()
        self.assertEqual((inf.tenis_id, inf.fisica_id, inf.estado), (t, f, "PENDIENTE"))
        # Desde el 02/11 valida el coordinador de tardes: el aviso le llega solo a él.
        self.assertTrue(Aviso.objects.filter(usuario=self.alberto, titulo__contains="listo para validar").exists())
        self.assertFalse(Aviso.objects.filter(usuario=self.ivan, titulo__contains="listo para validar").exists())
        self.assertFalse(Aviso.objects.filter(usuario=self.dani, titulo__contains="listo para validar").exists())
        # Iván Gallego valida pero no evalúa tenis.
        self.assertEqual(self.api(self.ivan_g).get(f"/api/informes/{inf.id}/").data["puede_validar"], True)
        self.assertEqual(self.api(self.ivan_g).post("/api/evaluaciones/", {"jugador": self.nino.id},
                                                    format="json").status_code, 403)

        # No hay dos evaluaciones de tenis en el mismo informe: se sigue con la que hay.
        r = self.api(self.alberto).post("/api/evaluaciones/", {"jugador": self.nino.id}, format="json")
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
        self.assertTrue(Aviso.objects.filter(usuario=self.salva, titulo__contains="devuelto").exists())
        self.assertFalse(Aviso.objects.filter(usuario=self.josep, titulo__contains="devuelto").exists())
        r = self.api(self.salva).get(f"/api/evaluaciones/{t}/")
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
        t2 = self._tenis(self.alberto)
        self.assertEqual(Informe.objects.count(), 2)
        self.assertEqual(Evaluacion.objects.get(pk=t2).informe.estado, "EN_CURSO")

        # Corregir una parte del ya validado lo devuelve a validar como versión 2.
        self.api(self.salva).post(f"/api/evaluaciones/{t}/terminar/", {}, format="json")
        inf.refresh_from_db()
        self.assertEqual((inf.estado, inf.version), ("PENDIENTE", 2))

    def test_pdf_conjunto_con_la_evolucion(self):
        anterior = Informe.objects.create(
            jugador=self.nino, estado="VALIDADO", validado_en=timezone.now() - timedelta(days=90),
            tenis=Evaluacion.objects.create(jugador=self.nino, estado="TERMINADA", puntuaciones={k: 2 for k in TENIS}),
            fisica=EvaluacionFisica.objects.create(jugador=self.nino, estado="TERMINADA",
                                                   puntuaciones={k: 3 for k in FISICO}))
        t = self._tenis()
        self.api(self.salva).post(f"/api/evaluaciones/{t}/terminar/", {}, format="json")
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

    def test_el_idioma_solo_cambia_el_pdf_de_la_familia(self):
        # 02/11/2026: en la app todo va en español; el PDF de la familia, en su idioma.
        DatosInforme.objects.create(jugador=self.nino, idioma="EN")
        t = self._tenis()
        self.api(self.salva).post(f"/api/evaluaciones/{t}/terminar/", {}, format="json")
        f = self._fisico()
        self.api(self.josep).post(f"/api/evaluaciones-fisicas/{f}/terminar/", {}, format="json")
        inf = Informe.objects.get()
        traducir = lambda textos, idioma: {k: f"EN {v}" for k, v in textos.items()}
        with mock.patch.object(ia, "traducir", side_effect=traducir) as m:
            es = pdf.datos_informe(inf)
            m.assert_not_called()
            self.assertEqual((es["t"]["lang"], es["fortalezas"]), ("es", ["Saque"]))
            en = pdf.datos_informe(inf, "EN")
            self.assertEqual((en["t"]["lang"], en["fortalezas"], en["mejoras"]), ("en", ["EN Saque"], ["EN Revés"]))
            self.assertEqual(en["fisico"]["textos"][0]["texto"], "EN Rápido")
            self.assertEqual(m.call_count, 2)
            pdf.datos_informe(inf, "EN")  # ya traducido: no se vuelve a pedir
            self.assertEqual(m.call_count, 2)
        self.assertEqual(self.api(self.ivan).get(f"/api/informes/{inf.id}/").data["idioma"], "EN")
        self.assertEqual(informes_mod.idioma_pdf(inf), "ES")  # mientras se revisa
        inf.estado = "VALIDADO"
        self.assertEqual(informes_mod.idioma_pdf(inf), "EN")

    def test_quien_ve_los_informes_y_el_panel(self):
        self.assertEqual(self.api(self.blas).get("/api/informes/").status_code, 403)
        for u in (self.salva, self.josep, self.ivan, self.dani):
            self.assertEqual(self.api(u).get("/api/informes/").status_code, 200, u.username)
        r = self.api(self.ivan).get("/api/informes/panel/")
        self.assertTrue(r.data["puede_validar"])
        fila = r.data["jugadores"][0]
        self.assertEqual((fila["nombre"], fila["ciclo"]["estado"], fila["informe"]), ("Asier Pérez", "primera", None))
        self._tenis()
        fila = self.api(self.josep).get("/api/informes/panel/").data["jugadores"][0]
        self.assertEqual(fila["informe"]["estado"], "EN_CURSO")
        self.assertIsNone(fila["informe"]["fisica"])

    def test_el_coordinador_reparte(self):
        c = self.api(self.alberto)
        r = c.post("/api/informes/asignar/", {"jugadores": [self.nino.id], "evaluador": self.salva.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        fila = next(j for j in r.data["jugadores"] if j["id"] == self.nino.id)
        self.assertEqual(fila["evaluador"]["nombre"], "Salva Barcala")
        self.assertTrue(r.data["puede_asignar"])
        self.assertEqual({e["nombre"] for e in r.data["evaluadores"]}, {"Alberto Sanz", "Salva Barcala"})
        a = Aviso.objects.get(usuario=self.salva)
        self.assertIn("Asier Pérez", a.mensaje)
        # Reasignar al mismo no vuelve a avisar; quitarlo lo deja sin entrenador.
        c.post("/api/informes/asignar/", {"jugadores": [self.nino.id], "evaluador": self.salva.id}, format="json")
        self.assertEqual(Aviso.objects.filter(usuario=self.salva).count(), 1)
        c.post("/api/informes/asignar/", {"jugadores": [self.nino.id], "evaluador": None}, format="json")
        self.assertFalse(AsignacionInforme.objects.exists())
        # Jorge Mico (pádel) no está entre los que pueden hacerlo, y un entrenador no reparte.
        r = c.post("/api/informes/asignar/", {"jugadores": [self.nino.id], "evaluador": self.mico.id}, format="json")
        self.assertEqual(r.status_code, 400)
        # Álvaro Mantoan tampoco desde el 30/10: Salva ocupa su sitio.
        r = c.post("/api/informes/asignar/", {"jugadores": [self.nino.id], "evaluador": self.alvaro.id}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.api(self.salva).post("/api/informes/asignar/", {"jugadores": [self.nino.id],
                                                                  "evaluador": self.salva.id}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(self.api(self.salva).get("/api/informes/panel/").data["puede_asignar"])
        # Los demás siguen pudiendo evaluarle.
        c.post("/api/informes/asignar/", {"jugadores": [self.nino.id], "evaluador": self.alberto.id}, format="json")
        self._tenis(self.salva)

    def test_administracion_no_valida(self):
        adm = User.objects.create_user(username="administracion", password="x", role=User.Role.SUPERADMIN)
        t = self._tenis()
        self.api(self.salva).post(f"/api/evaluaciones/{t}/terminar/", {}, format="json")
        f = self._fisico()
        self.api(self.josep).post(f"/api/evaluaciones-fisicas/{f}/terminar/", {}, format="json")
        inf = Informe.objects.get()
        self.assertFalse(Aviso.objects.filter(usuario=adm, titulo__contains="listo para validar").exists())
        self.assertFalse(self.api(adm).get("/api/informes/panel/").data["puede_validar"])
        self.assertEqual(self.api(adm).post(f"/api/informes/{inf.id}/aprobar/", {}, format="json").status_code, 403)

    def test_foto(self):
        from PIL import Image
        buf = BytesIO()
        Image.new("RGB", (2000, 1200), "red").save(buf, "PNG")
        buf.seek(0)
        buf.name = "foto.png"
        url = f"/api/informes/foto/{self.nino.id}/"
        self.assertEqual(self.api(self.salva).get(url).status_code, 404)
        r = self.api(self.salva).post(url, {"foto": buf}, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        r = self.api(self.josep).get(url)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        self.assertEqual(Image.open(BytesIO(r.content)).size, (900, 540))
        r = self.api(self.salva).post(url, {"foto": BytesIO(b"no es una imagen")}, format="multipart")
        self.assertEqual(r.status_code, 400)


class RecordatoriosTests(TestCase):
    def setUp(self):
        self.ct = Escuela.objects.create(nombre="Competición de tardes", solo_informes=True)
        self.hoy = timezone.localdate()
        self.nuevo = Jugador.objects.create(nombre="Nuevo", escuela=self.ct, activo=False,
                                            fecha_alta=self.hoy - timedelta(days=3))
        self.salva = User.objects.create_user(username="salva.barcala", password="x", role=User.Role.ENTRENADOR)
        self.alberto = User.objects.create_user(username="alberto.sanz", password="x", role=User.Role.ENTRENADOR)
        self.josep = User.objects.create_user(username="josep.mari", password="x", role=User.Role.PREPARADOR)
        self.ivan = User.objects.create_user(username="ivan", password="x", role=User.Role.SUPERADMIN)

    def test_primer_informe_a_la_semana_del_alta_y_una_sola_vez(self):
        self.assertEqual(recordatorios.revisar(self.hoy), 0)
        self.assertEqual(recordatorios.revisar(self.hoy + timedelta(days=7)), 1)
        self.assertEqual(recordatorios.revisar(self.hoy + timedelta(days=8)), 0)
        # Sin entrenador asignado, al coordinador para que lo reparta.
        a = Aviso.objects.get(usuario=self.alberto)
        self.assertIn("no tienen entrenador", a.titulo)
        self.assertIn("Nuevo", a.mensaje)
        self.assertFalse(Aviso.objects.filter(usuario=self.salva).exists())
        self.assertTrue(Aviso.objects.filter(usuario=self.josep).exists())
        self.assertFalse(Aviso.objects.filter(usuario=self.ivan).exists())

    def test_al_entrenador_asignado_y_a_diego(self):
        AsignacionInforme.objects.create(jugador=self.nuevo, evaluador=self.salva)
        diego = User.objects.create_user(username="diego.dominguez", password="x", role=User.Role.PREPARADOR)
        for u in (diego, self.josep):
            MiembroTardes.objects.create(usuario=u, funcion="FISICO")
        self.assertEqual(recordatorios.revisar(self.hoy + timedelta(days=7)), 1)
        self.assertIn("Toca el primer informe", Aviso.objects.get(usuario=self.salva).titulo)
        self.assertFalse(Aviso.objects.filter(usuario=self.alberto).exists())
        # La física de Competición de tardes la hacen Diego y Josep: les llega a los dos.
        self.assertTrue(Aviso.objects.filter(usuario=diego).exists())
        self.assertTrue(Aviso.objects.filter(usuario=self.josep).exists())

    def test_sin_alta_se_recuerda_una_vez(self):
        self.nuevo.fecha_alta = None
        self.nuevo.save()
        self.assertEqual(recordatorios.revisar(self.hoy), 1)
        self.assertEqual(recordatorios.revisar(self.hoy + timedelta(days=1)), 0)

    def test_75_y_90_dias_desde_la_validacion(self):
        validado = timezone.now() - timedelta(days=76)
        ev = Evaluacion.objects.create(jugador=self.nuevo, evaluador=self.alberto, estado="TERMINADA")
        Informe.objects.create(jugador=self.nuevo, tenis=ev, estado="VALIDADO", validado_en=validado)
        AsignacionInforme.objects.create(jugador=self.nuevo, evaluador=self.salva)
        self.assertEqual(recordatorios.revisar(self.hoy), 1)
        # El de tenis es el asignado; la física, Josep.
        self.assertTrue(Aviso.objects.filter(usuario=self.salva, titulo__contains="pronto").exists())
        self.assertFalse(Aviso.objects.filter(usuario=self.alberto).exists())
        self.assertTrue(Aviso.objects.filter(usuario=self.josep).exists())
        self.assertEqual(recordatorios.revisar(self.hoy + timedelta(days=14)), 1)
        self.assertTrue(Aviso.objects.filter(usuario=self.ivan, titulo__contains="vencido").exists())
        self.assertEqual(RecordatorioInforme.objects.count(), 2)

    def test_no_recuerda_si_ya_esta_en_marcha(self):
        Informe.objects.create(jugador=self.nuevo, tenis=Evaluacion.objects.create(jugador=self.nuevo))
        self.assertEqual(recordatorios.revisar(self.hoy + timedelta(days=10)), 0)


class CoordinadorTardesTests(TestCase):
    """Alberto lleva Competición de tardes: jugadores y equipo (02/11/2026)."""

    def setUp(self):
        self.ct = Escuela.objects.create(nombre="Competición de tardes", solo_informes=True)
        self.alberto = User.objects.create_user(username="alberto.sanz", password="x", role=User.Role.ENTRENADOR)
        self.milla = User.objects.create_user(username="jorge.milla", password="x", role=User.Role.ENTRENADOR)
        Entrenador.objects.create(nombre="Jorge Milla", user=self.milla)
        self.blas = User.objects.create_user(username="blas", password="x", role=User.Role.ENTRENADOR)

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_alta_cambios_y_baja_de_jugadores(self):
        c = self.api(self.alberto)
        r = c.post("/api/tardes/jugadores/", {"nombre": " Lucía Pérez ", "fecha_nacimiento": "2014-05-12",
                                               "fecha_alta": "2026-11-02", "email": "madre@x.com", "quien_1": "Madre",
                                               "email_2": "padre@x.com", "quien_2": "Padre", "idioma": "EN"},
                   format="json")
        self.assertEqual(r.status_code, 201, r.data)
        j = Jugador.objects.get(pk=r.data["id"])
        self.assertEqual((j.nombre, j.escuela, j.activo, j.edad is not None), ("Lucía Pérez", self.ct, False, True))
        self.assertEqual((r.data["idioma"], r.data["email_2"]), ("EN", "padre@x.com"))
        r = c.patch(f"/api/tardes/jugadores/{j.id}/", {"idioma": "ES"}, format="json")
        self.assertEqual(r.data["idioma"], "ES")
        self.assertEqual([d["quien"] for d in informes_mod.destinatarios_propuestos(j)], ["Madre", "Padre"])
        r = c.post(f"/api/tardes/jugadores/{j.id}/baja/", {"fecha": "2026-11-01"}, format="json")
        self.assertEqual(r.data["fecha_baja"], "2026-11-01")
        self.assertEqual(c.get("/api/tardes/jugadores/").data, [])
        self.assertEqual(len(c.get("/api/tardes/jugadores/?bajas=1").data), 1)
        c.post(f"/api/tardes/jugadores/{j.id}/reactivar/", {}, format="json")
        self.assertEqual(len(c.get("/api/tardes/jugadores/").data), 1)
        # Un entrenador cualquiera no.
        self.assertEqual(self.api(self.blas).get("/api/tardes/jugadores/").status_code, 403)

    def test_equipo(self):
        c = self.api(self.alberto)
        r = c.post("/api/tardes/equipo/", {"usuario": self.milla.id, "funcion": "TENIS"}, format="json")
        self.assertEqual((r.status_code, r.data["nombre"]), (201, "Jorge Milla"))
        datos = c.get("/api/tardes/equipo/").data
        self.assertEqual([m["nombre"] for m in datos["miembros"]], ["Jorge Milla"])
        self.assertIn("Jorge Milla", [x["nombre"] for x in datos["candidatos"]])
        self.assertTrue(self.api(self.milla).get("/api/auth/me/").data["evalua_tenis_informes"])
        c.delete(f"/api/tardes/equipo/{r.data['id']}/")
        self.assertFalse(MiembroTardes.objects.exists())
        self.assertEqual(self.api(self.blas).post("/api/tardes/equipo/", {"usuario": self.blas.id, "funcion": "TENIS"},
                                                  format="json").status_code, 403)
        # El coordinador valida y lo puede todo en tardes.
        me = c.get("/api/auth/me/").data
        self.assertTrue(me["valida_informes"] and me["coordina_informes"] and me["evalua_tenis_informes"])


@override_settings(GOOGLE_SERVICE_ACCOUNT_JSON="{}", DRIVE_INFORMES_ID="", DRIVE_CT_USUARIO="gestion@gtennis.com",
                   DRIVE_CT_RUTA="gtennis › Gestión deportiva › Competición tardes › 26/27 › Seguimiento y Evaluación")
class DriveTardesTests(TestCase):
    """Informes de tardes en «Mi unidad» de gestion@: dos carpetas y todos los PDF dentro (02/11/2026)."""

    def test_busca_la_ruta_sin_tildes_y_crea_las_dos_carpetas(self):
        arbol = {"root": [("a", "GTennis")], "a": [("b", "Gestion Deportiva")], "b": [("c", "competicion tardes")],
                 "c": [("d", "26/27")], "d": [("e", "Seguimiento y evaluacion")], "e": []}

        class Sesion(FakeDrive):
            def get(self, url, params=None):
                q = (params or {}).get("q", "")
                if q:
                    padre = q.split("'")[1]
                    return FakeResp({"files": [{"id": i, "name": n} for i, n in arbol.get(padre, [])]})
                return super().get(url, params)

        s = Sesion()
        self.assertEqual(drive._carpeta_ct(s, "pendientes"), "id1")
        self.assertEqual(len(s.creados), 1)  # solo «Por validar»; la ruta ya existía
        # Sin la carpeta de la temporada, no se inventa la ruta: avisa.
        del arbol["d"]
        from .models import CarpetaDrive
        CarpetaDrive.objects.all().delete()
        with self.assertRaises(drive.DriveNoDisponible):
            drive._carpeta_ct(Sesion(), "validados")
