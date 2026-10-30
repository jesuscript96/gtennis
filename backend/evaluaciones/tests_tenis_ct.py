"""Tenis de Competición de tardes: lo evalúan Alberto Sanz, Salva Barcala y
gestión deportiva, a todos los alumnos de la escuela (27/10/2026; Salva entra
el 29/10 y Álvaro Mantoan sale el 30/10)."""
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
        self.salva = entrenador("salva.barcala", "Salva Barcala")
        self.alberto = entrenador("alberto.sanz", "Alberto Sanz")
        self.mico = entrenador("jorge.mico", "Jorge Mico")
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
        for u in (self.salva, self.alberto, self.dani):
            nombres = [j["nombre"] for j in self.api(u).get("/api/evaluaciones/jugadores/").data]
            self.assertIn("Asier", nombres, u.username)
        r = self.api(self.salva).post("/api/evaluaciones/", {"jugador": self.nino.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        # Una sola evaluación de tenis por informe: los demás siguen con esa y la pueden corregir.
        for u in (self.alberto, self.dani):
            r2 = self.api(u).post("/api/evaluaciones/", {"jugador": self.nino.id}, format="json")
            self.assertEqual((r2.status_code, int(r2.data["existente"])), (400, r.data["id"]), u.username)
            self.assertEqual(self.api(u).patch(f"/api/evaluaciones/{r.data['id']}/", {"idioma": "EN"},
                                               format="json").status_code, 200, u.username)

    def test_jorge_milla_ya_no(self):
        # 27/10: «Jorge Mico» no era Jorge Milla; Milla no evalúa Competición de tardes.
        self.assertEqual(self.api(self.milla).post("/api/evaluaciones/", {"jugador": self.nino.id},
                                                   format="json").status_code, 403)

    def test_alvaro_mantoan_ya_no(self):
        # 30/10: Álvaro pasa a entrenar mañana y tarde en el puesto de Salva, y
        # Salva le sustituye en Competición de tardes.
        self.assertEqual(self.api(self.alvaro).post("/api/evaluaciones/", {"jugador": self.nino.id},
                                                    format="json").status_code, 403)

    def test_jorge_mico_es_de_padel(self):
        # 29/10, respuesta del club: Jorge Mico es de pádel y no hace informes.
        self.assertEqual(self.api(self.mico).post("/api/evaluaciones/", {"jugador": self.nino.id},
                                                  format="json").status_code, 403)

    def test_otro_entrenador_no(self):
        nombres = [j["nombre"] for j in self.api(self.blas).get("/api/evaluaciones/jugadores/").data]
        self.assertEqual(nombres, ["Ana"])
        self.assertEqual(self.api(self.blas).post("/api/evaluaciones/", {"jugador": self.nino.id},
                                                  format="json").status_code, 403)
        self.api(self.salva).post("/api/evaluaciones/", {"jugador": self.nino.id}, format="json")
        self.assertEqual(self.api(self.blas).get("/api/evaluaciones/").data, [])

    def test_cada_uno_sigue_con_los_suyos(self):
        r = self.api(self.blas).post("/api/evaluaciones/", {"jugador": self.ana.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        d = {j["nombre"]: j for j in self.api(self.salva).get("/api/evaluaciones/jugadores/").data}
        self.assertTrue(d["Asier"]["solo_informes"])
