"""Parte física de los informes y carga de Competición de tardes (21/10/2026)."""
import json
import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from academy.models import Coach, Entrenador, Escuela, Jugador
from users.models import User

from . import catalogo
from .models import EvaluacionFisica

TODAS = {k: 3 for k in catalogo.CRITERIOS_FISICO}


class FisicoTests(TestCase):
    def setUp(self):
        self.ct = Escuela.objects.create(nombre="Competición de tardes", solo_informes=True)
        self.ar = Escuela.objects.create(nombre="Alto Rendimiento X")
        self.nino = Jugador.objects.create(nombre="Asier", escuela=self.ct, activo=False)
        self.ar_jug = Jugador.objects.create(nombre="Ana", escuela=self.ar)
        self.josep = User.objects.create_user(username="josep.mari", password="x", role=User.Role.PREPARADOR)
        self.dani = User.objects.create_user(username="daniel.gimeno", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Dani", user=self.dani)
        self.ivan = User.objects.create_user(username="ivan", password="x", role=User.Role.SUPERADMIN)
        self.blas = User.objects.create_user(username="blas", password="x", role=User.Role.ENTRENADOR)
        Entrenador.objects.create(nombre="Blas", user=self.blas)
        self.pablo = User.objects.create_user(username="pablo", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Pablo", user=self.pablo)

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_quien_entra(self):
        for u in (self.josep, self.dani, self.ivan):
            self.assertEqual(self.api(u).get("/api/evaluaciones-fisicas/").status_code, 200, u.username)
        for u in (self.blas, self.pablo):
            self.assertEqual(self.api(u).get("/api/evaluaciones-fisicas/").status_code, 403, u.username)

    def test_solo_jugadores_de_competicion_de_tardes(self):
        nombres = [j["nombre"] for j in self.api(self.josep).get("/api/evaluaciones-fisicas/jugadores/").data]
        self.assertEqual(nombres, ["Asier"])
        r = self.api(self.josep).post("/api/evaluaciones-fisicas/", {"jugador": self.ar_jug.id}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_circuito_completo(self):
        c = self.api(self.josep)
        r = c.post("/api/evaluaciones-fisicas/", {"jugador": self.nino.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["nombre_evaluador"], "josep.mari")
        url = f"/api/evaluaciones-fisicas/{r.data['id']}/"
        c.patch(url, {"puntuaciones": {"fis_aceleracion": 4}}, format="json")
        r = c.patch(url, {"puntuaciones": {"fis_fatiga": 2}, "textos": {"puntos_fuertes": " Muy explosivo "}}, format="json")
        self.assertEqual(r.data["puntuaciones"], {"fis_aceleracion": 4, "fis_fatiga": 2})
        self.assertEqual(r.data["textos"]["puntos_fuertes"], "Muy explosivo")
        self.assertEqual(c.post(url + "terminar/", {}, format="json").status_code, 400)  # faltan notas
        c.patch(url, {"puntuaciones": TODAS}, format="json")
        r = c.post(url + "terminar/", {}, format="json")
        self.assertEqual(r.data["estado"], "TERMINADA")
        # Gestión deportiva la ve y la puede corregir; un entrenador ni la ve.
        self.assertEqual(self.api(self.dani).patch(url, {"textos": {"notas_fisio": "ok"}}, format="json").status_code, 200)
        self.assertEqual(self.api(self.blas).get(url).status_code, 403)

    def test_notas_validas(self):
        ev = EvaluacionFisica.objects.create(jugador=self.nino, evaluador=self.josep, nombre_evaluador="Josep")
        url = f"/api/evaluaciones-fisicas/{ev.id}/"
        for malas in ({"fis_aceleracion": 6}, {"drive_impact": 3}, {"fis_dolor": "4"}):
            self.assertEqual(self.api(self.josep).patch(url, {"puntuaciones": malas}, format="json").status_code, 400)

    def test_catalogo(self):
        d = self.api(self.josep).get("/api/evaluaciones-fisicas/catalogo/").data
        self.assertEqual(sum(len(b["criterios"]) for b in d["bloques"]), 11)
        self.assertEqual([t["clave"] for t in d["textos"]], ["puntos_fuertes", "a_mejorar", "notas_fisio"])
        self.assertEqual(d["escala"][0]["etiqueta"], "Muy deficiente")

    def test_permisos_en_auth_me(self):
        me = self.api(self.josep).get("/api/auth/me/").data
        self.assertTrue(me["is_preparador"] and me["evalua_fisico"])
        self.assertFalse(me["gestion_deportiva"])
        me = self.api(self.blas).get("/api/auth/me/").data
        self.assertFalse(me["evalua_fisico"])


class CargaCompeticionTardesTests(TestCase):
    def test_reutiliza_crea_y_nunca_activa(self):
        vieja = Jugador.objects.create(nombre="Alejandro Mora", activo=False)
        activo = Jugador.objects.create(nombre="Mario V", codigo_cliente=12249, activo=True)
        dup = Jugador.objects.create(nombre="Iker dup", activo=False)
        datos = {"jugadores": [
            {"codigo": 12105, "nombre": "Alejandro Mora Díez", "nacimiento": "03/12/2014", "email": "a@b.es",
             "movil": 600, "alta": "01/09/2026", "app_id": vieja.id},
            {"codigo": 999, "nombre": "Nuevo Nuevo", "nacimiento": "01/01/2015", "email": "", "movil": "",
             "alta": None, "app_id": None},
            {"codigo": 12249, "nombre": "Mario V", "nacimiento": "15/08/2014", "email": "", "movil": "",
             "alta": None, "app_id": None},
        ], "fusionar": [[dup.id, vieja.id]]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(datos, f)
        out = StringIO()
        call_command("cargar_competicion_tardes", f.name, stdout=out)
        self.assertFalse(Escuela.objects.filter(nombre="Competición de tardes").exists())  # simulación
        call_command("cargar_competicion_tardes", f.name, "--aplicar", stdout=out)
        esc = Escuela.objects.get(nombre="Competición de tardes")
        self.assertTrue(esc.solo_informes)
        vieja.refresh_from_db()
        self.assertEqual((vieja.nombre, vieja.codigo_cliente, vieja.escuela, vieja.activo),
                         ("Alejandro Mora Díez", 12105, esc, False))
        self.assertTrue(Jugador.objects.filter(nombre="Nuevo Nuevo", escuela=esc, activo=False).exists())
        activo.refresh_from_db()
        self.assertIsNone(activo.escuela)  # el activo no se toca
        self.assertFalse(Jugador.objects.filter(pk=dup.pk).exists())
        self.assertIn("ACTIVO", out.getvalue())
