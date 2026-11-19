"""Reparto de la parte física (19/11/2026): Josep Mari decide quién hace la
física de cada jugador — en Alto rendimiento, él o Alex Ante; en Competición
de tardes, él o Santiago Pico."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from academy.models import Aviso, Escuela, Jugador
from users.models import Funcion, User

from . import recordatorios
from .models import AsignacionFisica, Evaluacion, Informe, MiembroTardes


class RepartoFisicoTests(TestCase):
    def setUp(self):
        self.ct = Escuela.objects.create(nombre="Competición de tardes", solo_informes=True)
        self.ar = Escuela.objects.create(nombre="Alto Rendimiento X")
        self.hoy = timezone.localdate()
        self.nino = Jugador.objects.create(nombre="Asier", escuela=self.ct, activo=False,
                                           fecha_alta=self.hoy - timedelta(days=3))
        self.ana = Jugador.objects.create(nombre="Ana", escuela=self.ar)
        mk = lambda n, r=User.Role.PREPARADOR: User.objects.create_user(username=n, password="x", role=r)  # noqa: E731
        self.josep, self.alex, self.santi, self.diego = (
            mk("josep.mari"), mk("alex.ante"), mk("santiago.pico"), mk("diego.dominguez"))
        self.ivan = mk("ivan", User.Role.SUPERADMIN)
        self.alberto = mk("alberto.sanz", User.Role.ENTRENADOR)
        Funcion.objects.create(usuario=self.alberto, codigo="COORDINA_TARDES")
        Funcion.objects.create(usuario=self.josep, codigo="COORDINA_FISICO")
        for u in (self.josep, self.alex):
            Funcion.objects.create(usuario=u, codigo="FISICO_AR")
        for u in (self.josep, self.santi):
            MiembroTardes.objects.create(usuario=u, funcion="FISICO")

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def asignar(self, quien, jugadores, evaluador):
        return self.api(quien).post("/api/evaluaciones-fisicas/asignar/",
                                    {"jugadores": [j.id for j in jugadores],
                                     "evaluador": evaluador.id if evaluador else None}, format="json")

    def test_reparto_por_escuela(self):
        r = self.api(self.josep).get("/api/evaluaciones-fisicas/reparto/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["puede_asignar"])
        nombres = lambda c: sorted(u["nombre"] for u in r.data["evaluadores"][c])  # noqa: E731
        self.assertEqual(nombres("tardes"), ["josep.mari", "santiago.pico"])
        self.assertEqual(nombres("alto_rendimiento"), ["alex.ante", "josep.mari"])
        circuito = {j["nombre"]: j["circuito"] for j in r.data["jugadores"]}
        self.assertEqual((circuito["Asier"], circuito["Ana"]), ("tardes", "alto_rendimiento"))
        self.assertTrue(all(j["evaluador"] is None for j in r.data["jugadores"]))

    def test_josep_asigna_y_avisa(self):
        r = self.asignar(self.josep, [self.ana], self.alex)
        self.assertEqual(r.status_code, 200, r.data)
        fila = next(j for j in r.data["jugadores"] if j["id"] == self.ana.id)
        self.assertEqual(fila["evaluador"]["id"], self.alex.id)
        a = Aviso.objects.get(usuario=self.alex)
        self.assertIn("evaluación física", a.titulo)
        self.assertIn("Ana", a.mensaje)
        # Tardes, a Santiago; quitarlo lo deja sin asignar; uno mismo no se avisa.
        self.assertEqual(self.asignar(self.josep, [self.nino], self.santi).status_code, 200)
        self.assertEqual(AsignacionFisica.objects.get(jugador=self.nino).evaluador, self.santi)
        self.asignar(self.josep, [self.nino], None)
        self.assertFalse(AsignacionFisica.objects.filter(jugador=self.nino).exists())
        self.asignar(self.josep, [self.nino, self.ana], self.josep)
        self.assertEqual(AsignacionFisica.objects.filter(evaluador=self.josep).count(), 2)
        self.assertFalse(Aviso.objects.filter(usuario=self.josep).exists())

    def test_cada_escuela_con_su_equipo(self):
        r = self.asignar(self.josep, [self.ana], self.santi)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Alto rendimiento", r.data["detail"])
        r = self.asignar(self.josep, [self.nino], self.alex)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Competición de tardes", r.data["detail"])
        # Mezclando escuelas, solo vale quien está en las dos.
        self.assertEqual(self.asignar(self.josep, [self.nino, self.ana], self.alex).status_code, 400)
        self.assertFalse(AsignacionFisica.objects.exists())
        # Diego no está ya en el equipo de tardes de este ejemplo.
        self.assertEqual(self.asignar(self.josep, [self.nino], self.diego).status_code, 400)

    def test_quien_reparte(self):
        for u in (self.alex, self.santi, self.alberto):
            self.assertEqual(self.asignar(u, [self.ana], self.alex).status_code, 403, u.username)
        self.assertFalse(self.api(self.alex).get("/api/evaluaciones-fisicas/reparto/").data["puede_asignar"])
        # Dirección también reparte.
        self.assertEqual(self.asignar(self.ivan, [self.ana], self.alex).status_code, 200)
        # Los nuevos hacen física (y entran a verla); un entrenador, no.
        for u in (self.alex, self.santi):
            self.assertEqual(self.api(u).get("/api/evaluaciones-fisicas/reparto/").status_code, 200)
            self.assertTrue(self.api(u).get("/api/auth/me/").data["evalua_fisico"])
        self.assertEqual(self.api(self.alberto).get("/api/evaluaciones-fisicas/reparto/").status_code, 403)
        self.assertTrue(self.api(self.josep).get("/api/auth/me/").data["coordina_fisico"])
        self.assertFalse(self.api(self.alex).get("/api/auth/me/").data["coordina_fisico"])

    def test_alto_rendimiento_sin_nadie_marcado(self):
        """Sin nadie con «Evalúa física de Alto rendimiento», se elige entre los preparadores."""
        Funcion.objects.filter(codigo="FISICO_AR").delete()
        r = self.api(self.josep).get("/api/evaluaciones-fisicas/reparto/")
        self.assertEqual(len(r.data["evaluadores"]["alto_rendimiento"]), 4)

    def test_en_el_panel_de_informes(self):
        self.asignar(self.josep, [self.nino], self.santi)
        p = self.api(self.alberto).get("/api/informes/panel/").data
        self.assertEqual(p["jugadores"][0]["preparador"]["id"], self.santi.id)
        self.assertFalse(p["puede_asignar_fisico"])
        self.assertTrue(self.api(self.josep).get("/api/informes/panel/").data["puede_asignar_fisico"])
        self.assertEqual(sorted(u["id"] for u in p["preparadores"]), sorted([self.josep.id, self.santi.id]))

    def test_recordatorio_de_tardes_al_asignado(self):
        self.asignar(self.josep, [self.nino], self.santi)
        Aviso.objects.all().delete()
        self.assertEqual(recordatorios.revisar(self.hoy + timedelta(days=7)), 1)
        self.assertTrue(Aviso.objects.filter(usuario=self.santi, titulo__contains="primer informe").exists())
        self.assertFalse(Aviso.objects.filter(usuario=self.josep).exists())

    def test_recordatorio_de_alto_rendimiento_al_asignado(self):
        validado = timezone.now() - timedelta(days=76)
        ev = Evaluacion.objects.create(jugador=self.ana, evaluador=self.ivan, estado="TERMINADA")
        Informe.objects.create(jugador=self.ana, tenis=ev, estado="VALIDADO", validado_en=validado)
        self.asignar(self.josep, [self.ana], self.alex)
        Aviso.objects.all().delete()
        self.assertEqual(recordatorios.revisar(self.hoy), 1)
        a = Aviso.objects.get(usuario=self.alex, titulo__contains="pronto")
        self.assertIn("Evaluaciones físicas", a.mensaje)
        self.assertFalse(Aviso.objects.filter(usuario=self.josep).exists())

    def test_funciones_en_personas(self):
        datos = self.api(self.ivan).get("/api/auth/personal/").data
        por_codigo = {f["codigo"]: f for f in datos["funciones"]}
        self.assertFalse(por_codigo["COORDINA_FISICO"]["equipo"])
        self.assertTrue(por_codigo["FISICO_AR"]["equipo"])
        self.assertTrue(por_codigo["TARDES_FISICO"]["equipo"])
        # Dirección no está en el equipo de Alto rendimiento sin marcarla.
        r = self.api(self.ivan).get("/api/evaluaciones-fisicas/reparto/")
        self.assertNotIn(self.ivan.id, [u["id"] for u in r.data["evaluadores"]["alto_rendimiento"]])
