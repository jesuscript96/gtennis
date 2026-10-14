"""El calendario de torneos: quién entra, quién toca a quién y que fusionar
no pierda a nadie. No toca faltas ni motor."""
from django.test import TestCase
from rest_framework.test import APIClient

from academy.models import Coach, Entrenador, Jugador, ResponsableJugador, VacacionesEntrenador
from users.models import User

from .models import Participante, Torneo


class TorneosTests(TestCase):
    def setUp(self):
        self.blas = Entrenador.objects.create(nombre="Blas")
        self.mario = Entrenador.objects.create(nombre="Mario")
        self.ana = Jugador.objects.create(nombre="Ana", entrenador_responsable=self.blas)
        self.leo = Jugador.objects.create(nombre="Leo", entrenador_responsable=self.mario)
        ResponsableJugador.objects.create(jugador=self.ana, entrenador=self.blas, prioridad=1)
        ResponsableJugador.objects.create(jugador=self.leo, entrenador=self.mario, prioridad=1)
        self.u_pablo = User.objects.create_user(username="pablo", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Pablo", user=self.u_pablo).entrenadores.set([self.blas])
        self.u_dir = User.objects.create_user(username="dir", password="x", role=User.Role.SUPERADMIN)
        self.u_blas = User.objects.create_user(username="blas", password="x", role=User.Role.ENTRENADOR)
        self.blas.user = self.u_blas
        self.blas.save(update_fields=["user"])
        self.t1 = Torneo.objects.create(nombre="ITF J30 Silla", fecha_inicio="2026-10-26", fecha_fin="2026-11-01")
        self.t2 = Torneo.objects.create(nombre="ITF J30 Sila", fecha_inicio="2026-10-27", fecha_fin="2026-11-02",
                                        cierre_inscripcion="2026-10-19", lugar="Silla")

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_el_entrenador_no_entra(self):
        self.assertEqual(self.api(self.u_blas).get("/api/torneos/").status_code, 403)

    def test_head_coach_y_direccion_entran(self):
        self.assertEqual(self.api(self.u_pablo).get("/api/torneos/").status_code, 200)
        self.assertEqual(self.api(self.u_dir).get("/api/torneos/").status_code, 200)

    def test_el_head_coach_apunta_a_los_suyos_y_no_a_los_de_otro(self):
        c = self.api(self.u_pablo)
        r = c.post("/api/torneos-participantes/", {"torneo": self.t1.id, "jugador": self.ana.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["nombre"], "Ana")
        r = c.post("/api/torneos-participantes/", {"torneo": self.t1.id, "jugador": self.leo.id}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_no_se_apunta_dos_veces(self):
        c = self.api(self.u_dir)
        c.post("/api/torneos-participantes/", {"torneo": self.t1.id, "jugador": self.ana.id}, format="json")
        r = c.post("/api/torneos-participantes/", {"torneo": self.t1.id, "jugador": self.ana.id}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_mover_a_otro_torneo(self):
        p = Participante.objects.create(torneo=self.t1, jugador=self.ana, nombre="Ana")
        r = self.api(self.u_pablo).patch(f"/api/torneos-participantes/{p.id}/", {"torneo": self.t2.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Participante.objects.get(pk=p.id).torneo_id, self.t2.id)

    def test_fusionar_no_pierde_a_nadie(self):
        Participante.objects.create(torneo=self.t1, jugador=self.ana, nombre="Ana")
        Participante.objects.create(torneo=self.t2, jugador=self.ana, nombre="Ana")
        Participante.objects.create(torneo=self.t2, nombre="Invitado")
        self.t2.acompanantes.add(self.mario)
        r = self.api(self.u_pablo).post(f"/api/torneos/{self.t1.id}/fusionar/", {"con": self.t2.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(Torneo.objects.filter(pk=self.t2.id).exists())
        self.assertEqual(sorted(p["nombre"] for p in r.data["participantes"]), ["Ana", "Invitado"])
        self.assertEqual(r.data["fecha_fin"], "2026-11-02")
        self.assertEqual(r.data["cierre_inscripcion"], "2026-10-19")
        self.assertEqual(r.data["lugar"], "Silla")
        self.assertIn("ITF J30 Sila", r.data["alias"])
        self.assertEqual([e["nombre"] for e in r.data["acompanantes_detalle"]], ["Mario"])

    def test_acompanantes_disponibles_sin_vacaciones(self):
        VacacionesEntrenador.objects.create(entrenador=self.mario, fecha_inicio="2026-10-25", fecha_fin="2026-10-30")
        # Una franja suelta no impide viajar.
        VacacionesEntrenador.objects.create(entrenador=self.blas, fecha_inicio="2026-10-27", fecha_fin="2026-10-27",
                                            ambito=VacacionesEntrenador.Ambito.T2)
        r = self.api(self.u_pablo).get("/api/torneos/entrenadores/?desde=2026-10-26&hasta=2026-11-01")
        vac = {e["nombre"]: len(e["vacaciones"]) for e in r.data}
        self.assertEqual(vac["Mario"], 1)
        self.assertEqual(vac["Blas"], 0)

    def test_no_acaba_antes_de_empezar(self):
        r = self.api(self.u_dir).post("/api/torneos/", {
            "nombre": "X", "fecha_inicio": "2026-11-10", "fecha_fin": "2026-11-01"}, format="json")
        self.assertEqual(r.status_code, 400)
