"""Tenis de Competición de tardes: lo evalúan Álvaro Mantoan, Alberto Sanz,
Jorge Milla y gestión deportiva, a todos los alumnos de la escuela (27/10/2026)."""
from django.test import TestCase
from rest_framework.test import APIClient

from academy.models import Coach, Entrenador, Escuela, Jugador, ResponsableJugador
from users.models import User


class TenisCompeticionTardesTests(TestCase):
    def setUp(self):
        self.ct = Escuela.objects.create(nombre="Competición de tardes", solo_informes=True)
        self.nino = Jugador.objects.create(nombre="Asier", escuela=self.ct, activo=False)
        self.blas_e = Entrenador.objects.create(nombre="Blas")
        self.ana = Jugador.objects.create(nombre="Ana", entrenador_responsable=self.blas_e)
        ResponsableJugador.objects.create(jugador=self.ana, entrenador=self.blas_e, prioridad=1)

        def entrenador(username, nombre):
            u = User.objects.create_user(username=username, password="x", role=User.Role.ENTRENADOR)
            Entrenador.objects.create(nombre=nombre, user=u)
            return u
        self.alvaro = entrenador("alvaro.mantoan", "Alvaro Mantoan")
        self.milla = entrenador("jorge.milla", "Jorge Milla")
        self.blas = User.objects.create_user(username="blas", password="x", role=User.Role.ENTRENADOR)
        self.blas_e.user = self.blas
        self.blas_e.save(update_fields=["user"])
        self.dani = User.objects.create_user(username="daniel.gimeno", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Dani", user=self.dani)

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_los_de_tarde_y_gestion_evaluan_a_los_de_competicion(self):
        for u in (self.alvaro, self.milla, self.dani):
            nombres = [j["nombre"] for j in self.api(u).get("/api/evaluaciones/jugadores/").data]
            self.assertIn("Asier", nombres, u.username)
            r = self.api(u).post("/api/evaluaciones/", {"jugador": self.nino.id}, format="json")
            self.assertEqual(r.status_code, 201, (u.username, r.data))
        # Cada uno ve las tres (todos evalúan a todos de momento).
        self.assertEqual(len(self.api(self.alvaro).get("/api/evaluaciones/").data), 3)

    def test_otro_entrenador_no(self):
        nombres = [j["nombre"] for j in self.api(self.blas).get("/api/evaluaciones/jugadores/").data]
        self.assertEqual(nombres, ["Ana"])
        self.assertEqual(self.api(self.blas).post("/api/evaluaciones/", {"jugador": self.nino.id},
                                                  format="json").status_code, 403)
        self.api(self.alvaro).post("/api/evaluaciones/", {"jugador": self.nino.id}, format="json")
        self.assertEqual(self.api(self.blas).get("/api/evaluaciones/").data, [])

    def test_cada_uno_sigue_con_los_suyos(self):
        r = self.api(self.blas).post("/api/evaluaciones/", {"jugador": self.ana.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        d = {j["nombre"]: j for j in self.api(self.alvaro).get("/api/evaluaciones/jugadores/").data}
        self.assertTrue(d["Asier"]["solo_informes"])
