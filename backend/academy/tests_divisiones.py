"""Mover alumnos de división desde la vista de Divisiones (21/10/2026)."""
from django.test import TestCase
from rest_framework.test import APIClient

from academy.models import Coach, Division, Entrenador, Jugador
from users.models import User


class MoverDivisionTests(TestCase):
    def setUp(self):
        self.d1, _ = Division.objects.get_or_create(nivel=1, defaults={"nombre": "División 1"})
        self.d2, _ = Division.objects.get_or_create(nivel=2, defaults={"nombre": "División 2"})
        self.ana = Jugador.objects.create(nombre="Ana", division=self.d1)
        self.direccion = User.objects.create_user(username="ivan", password="x", role=User.Role.SUPERADMIN)
        self.dani = User.objects.create_user(username="daniel.gimeno", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Dani", user=self.dani)
        self.otro_coach = User.objects.create_user(username="pablo", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Pablo", user=self.otro_coach)
        self.entrenador = User.objects.create_user(username="blas", password="x", role=User.Role.ENTRENADOR)
        Entrenador.objects.create(nombre="Blas", user=self.entrenador)

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def mover(self, user, division):
        return self.api(user).post("/api/divisiones/mover/", {"jugador": self.ana.id, "division": division},
                                   format="json")

    def test_direccion_y_dani_mueven(self):
        r = self.mover(self.direccion, self.d2.id)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["division"], r.data["anterior"]), (2, 1))
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.division, self.d2)
        self.assertEqual(self.mover(self.dani, self.d1.id).status_code, 200)
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.division, self.d1)

    def test_nadie_mas_mueve(self):
        for u in (self.otro_coach, self.entrenador):
            self.assertEqual(self.mover(u, self.d2.id).status_code, 403, u.username)
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.division, self.d1)

    def test_sin_division_y_errores(self):
        r = self.mover(self.direccion, None)
        self.assertEqual(r.data["division"], None)
        self.ana.refresh_from_db()
        self.assertIsNone(self.ana.division)
        self.assertEqual(self.mover(self.direccion, 999).status_code, 400)
        r = self.api(self.direccion).post("/api/divisiones/mover/", {"jugador": 999, "division": self.d1.id},
                                          format="json")
        self.assertEqual(r.status_code, 404)

    def test_permisos(self):
        self.assertTrue(self.api(self.dani).get("/api/divisiones/permisos/").data["puede_mover"])
        self.assertTrue(self.api(self.direccion).get("/api/divisiones/permisos/").data["puede_mover"])
        self.assertFalse(self.api(self.entrenador).get("/api/divisiones/permisos/").data["puede_mover"])
        self.assertFalse(self.api(self.otro_coach).get("/api/divisiones/permisos/").data["puede_mover"])

    def test_la_tabla_de_divisiones_sigue_siendo_de_direccion(self):
        r = self.api(self.dani).post("/api/divisiones/", {"nivel": 42, "nombre": "División 42"}, format="json")
        self.assertEqual(r.status_code, 403)


class RankingDivisionTests(MoverDivisionTests):
    """Ranking dentro de cada división (27/10/2026): se ordena arrastrando en
    Divisiones y quien cambia de división entra el último."""

    def ordenar(self, user, division, orden):
        return self.api(user).post("/api/divisiones/ordenar/",
                                   {"division": division.id, "orden": orden}, format="json")

    def setUp(self):
        super().setUp()
        Jugador.objects.exclude(pk=self.ana.pk).update(activo=False)
        self.bea = Jugador.objects.create(nombre="Bea", division=self.d1)
        self.carla = Jugador.objects.create(nombre="Carla", division=self.d1)

    def puestos(self):
        return dict(Jugador.objects.filter(division=self.d1, activo=True)
                    .values_list("nombre", "orden_division"))

    def test_sin_ranking_no_hay_puesto(self):
        self.assertEqual(set(self.puestos().values()), {None})

    def test_ordenar(self):
        r = self.ordenar(self.dani, self.d1, [self.carla.id, self.ana.id])
        self.assertEqual(r.status_code, 200, r.data)
        # Quien no viene en la lista se queda detrás.
        self.assertEqual(self.puestos(), {"Carla": 1, "Ana": 2, "Bea": 3})

    def test_solo_quien_mueve_divisiones(self):
        for u in (self.otro_coach, self.entrenador):
            self.assertEqual(self.ordenar(u, self.d1, [self.bea.id]).status_code, 403)

    def test_no_admite_alumnos_de_otra_division(self):
        dora = Jugador.objects.create(nombre="Dora", division=self.d2)
        self.assertEqual(self.ordenar(self.direccion, self.d1, [dora.id]).status_code, 400)

    def test_quien_cambia_de_division_entra_el_ultimo(self):
        self.ordenar(self.direccion, self.d1, [self.carla.id, self.bea.id, self.ana.id])
        dora = Jugador.objects.create(nombre="Dora", division=self.d2)
        r = self.api(self.direccion).post("/api/divisiones/mover/",
                                          {"jugador": dora.id, "division": self.d1.id}, format="json")
        self.assertEqual(r.data["orden_division"], 4)
        # A una división sin ranking, sin puesto.
        self.mover(self.direccion, self.d2.id)
        self.ana.refresh_from_db()
        self.assertIsNone(self.ana.orden_division)
        # Un alta nueva en una división con ranking, también al final (el
        # hueco de Ana no se rellena: cuenta el orden, no el número).
        eva = Jugador.objects.create(nombre="Eva", division=self.d1)
        self.assertEqual(eva.orden_division, 5)

    def test_el_motor_lee_el_nivel_fino(self):
        from engine.service import niveles_finos

        self.ordenar(self.direccion, self.d1, [self.carla.id, self.bea.id, self.ana.id])
        finos = niveles_finos()
        self.assertAlmostEqual(finos[self.carla.id], 1 + 0.5 / 3)
        self.assertAlmostEqual(finos[self.ana.id], 1 + 2.5 / 3)
        self.assertLess(finos[self.carla.id], finos[self.bea.id])
