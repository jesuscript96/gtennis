"""Retoques a mano del cuadrante. Run: python manage.py test scheduling"""
from datetime import date, time

from django.test import TestCase
from rest_framework.test import APIClient

from academy.models import Entrenador, Jugador, Pista, Sede, Turno
from scheduling.models import Asignacion, Semana
from users.models import User

LUNES = date(2026, 9, 14)


class AbrirPistaVaciaTests(TestCase):
    """Una pista vacía se abre trayendo gente del banquillo o de otra pista, y
    después se le pone entrenador."""

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(User.objects.create_user(
            username="direccion", password="x", role=User.Role.SUPERADMIN))
        Sede.objects.update(activa=False)
        self.sede = Sede.objects.create(
            nombre="Prueba", densidad_default=2, densidad_max=2, activa=True)
        self.p1, self.p2 = [
            Pista.objects.create(sede=self.sede, numero=n, superficie="TIERRA")
            for n in (1, 2)
        ]
        self.m1, _ = Turno.objects.get_or_create(
            codigo="M1", defaults={"nombre": "M1", "bloque": Turno.Bloque.MANANA,
                                   "hora_inicio": time(8, 30), "hora_fin": time(10, 0), "orden": 1})
        self.t1, _ = Turno.objects.get_or_create(
            codigo="T1", defaults={"nombre": "T1", "bloque": Turno.Bloque.TARDE,
                                   "hora_inicio": time(14, 15), "hora_fin": time(15, 30), "orden": 4})
        self.semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)
        self.coach = Entrenador.objects.create(nombre="Blas")
        self.otro_coach = Entrenador.objects.create(nombre="Nacho")
        self.a, self.b = [Jugador.objects.create(nombre=n) for n in ("Ana", "Bruno")]
        self.asig = Asignacion.objects.create(
            semana=self.semana, dia=0, turno=self.m1, pista=self.p1,
            jugador=self.a, entrenador=self.coach)

    def _mover(self, **extra):
        cuerpo = {"asignacion": self.asig.id, "dia": 0, "turno": self.m1.id,
                  "pista": self.p2.id, **extra}
        return self.api.post("/api/asignaciones/mover/", cuerpo, format="json")

    def test_abre_la_pista_vacia_y_la_deja_sin_entrenador(self):
        r = self._mover()
        self.assertEqual(r.status_code, 200)
        self.asig.refresh_from_db()
        self.assertEqual(self.asig.pista, self.p2)
        self.assertIsNone(self.asig.entrenador)
        self.assertTrue(self.asig.manual)

    def test_quien_llega_entrena_con_el_entrenador_de_esa_pista(self):
        Asignacion.objects.create(
            semana=self.semana, dia=0, turno=self.m1, pista=self.p2,
            jugador=self.b, entrenador=self.otro_coach)
        self._mover()
        self.asig.refresh_from_db()
        self.assertEqual(self.asig.entrenador, self.otro_coach)

    def test_no_entra_en_una_pista_llena(self):
        for j in (self.b, Jugador.objects.create(nombre="Cira")):
            Asignacion.objects.create(semana=self.semana, dia=0, turno=self.m1,
                                      pista=self.p2, jugador=j)
        r = self._mover()
        self.assertEqual(r.status_code, 409)
        self.assertIn("llena", r.json()["error"])

    def test_no_se_puede_llevar_al_miercoles_por_la_tarde(self):
        r = self._mover(dia=2, turno=self.t1.id)
        self.assertEqual(r.status_code, 400)

    def test_no_se_duplica_en_la_misma_franja(self):
        otra = Asignacion.objects.create(
            semana=self.semana, dia=0, turno=self.t1, pista=self.p1, jugador=self.a)
        r = self.api.post("/api/asignaciones/mover/", {
            "asignacion": otra.id, "dia": 0, "turno": self.m1.id, "pista": self.p2.id,
        }, format="json")
        self.assertEqual(r.status_code, 409)

    def test_el_entrenador_necesita_jugadores_en_la_pista(self):
        r = self.api.post("/api/asignaciones/set_coach/", {
            "semana": self.semana.id, "dia": 0, "turno": self.m1.id,
            "pista": self.p2.id, "entrenador_id": self.coach.id,
        }, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("vacía", r.json()["error"])

    def test_del_banquillo_a_una_pista_con_gente_hereda_el_entrenador(self):
        r = self.api.post("/api/asignaciones/manual_assign/", {
            "jugador_id": self.b.id, "semana": self.semana.id, "dia": 0,
            "turno": self.m1.id, "pista": self.p1.id,
        }, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Asignacion.objects.get(pk=r.json()["id"]).entrenador, self.coach)
