"""Retoques a mano del cuadrante. Run: python manage.py test scheduling"""
from datetime import date, time

from django.test import TestCase
from rest_framework.test import APIClient

from academy.models import Entrenador, Jugador, Pista, Sede, Turno
from scheduling.models import Asignacion, DisponibilidadEntrenador, Semana
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


class EntrenadoresPorFranjaTests(AbrirPistaVaciaTests):
    """A la derecha del cuadrante salen todos los entrenadores con su estado en
    cada franja, para poder forzar a quien haga falta."""

    def _panel(self):
        r = self.api.get(f"/api/semanas/{self.semana.id}/panel/?dia=0")
        self.assertEqual(r.status_code, 200)
        return {e["nombre"]: e for e in r.json()["entrenadores"]}

    def test_dice_donde_esta_y_donde_queda_libre(self):
        blas = self._panel()["Blas"]
        self.assertEqual(blas["franjas"][str(self.m1.id)]["pistas"], ["Prueba 1"])
        self.assertFalse(blas["franjas"][str(self.m1.id)]["libre"])
        self.assertTrue(blas["franjas"][str(self.t1.id)]["libre"])

    def test_el_ocupado_sigue_saliendo_para_poder_forzarlo(self):
        self.assertIn("Blas", self._panel())

    def test_el_declarado_no_disponible_sale_con_su_motivo(self):
        DisponibilidadEntrenador.objects.create(
            semana=self.semana, entrenador=self.otro_coach, dia=0, estado="AUSENTE")
        nacho = self._panel()["Nacho"]
        self.assertFalse(nacho["franjas"][str(self.m1.id)]["libre"])
        self.assertIn("no disponible", nacho["franjas"][str(self.m1.id)]["motivo"])

    def test_se_puede_forzar_al_que_ya_esta_en_otra_pista(self):
        Asignacion.objects.create(semana=self.semana, dia=0, turno=self.m1,
                                  pista=self.p2, jugador=self.b)
        r = self.api.post("/api/asignaciones/set_coach/", {
            "semana": self.semana.id, "dia": 0, "turno": self.m1.id,
            "pista": self.p2.id, "entrenador_id": self.coach.id,
        }, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Asignacion.objects.filter(
            semana=self.semana, dia=0, turno=self.m1, entrenador=self.coach).count(), 2)

    def test_arrastrarlo_de_una_pista_a_otra_lo_traslada(self):
        Asignacion.objects.create(semana=self.semana, dia=0, turno=self.m1,
                                  pista=self.p2, jugador=self.b)
        r = self.api.post("/api/asignaciones/set_coach/", {
            "semana": self.semana.id, "dia": 0, "turno": self.m1.id,
            "pista": self.p2.id, "entrenador_id": self.coach.id,
            "desde_pista": self.p1.id,
        }, format="json")
        self.assertEqual(r.status_code, 200)
        self.asig.refresh_from_db()
        self.assertIsNone(self.asig.entrenador)
        self.assertEqual(Asignacion.objects.get(
            semana=self.semana, dia=0, turno=self.m1, pista=self.p2).entrenador, self.coach)

    def test_se_puede_dejar_una_pista_sin_entrenador(self):
        r = self.api.post("/api/asignaciones/set_coach/", {
            "semana": self.semana.id, "dia": 0, "turno": self.m1.id,
            "pista": self.p1.id, "entrenador_id": None,
        }, format="json")
        self.assertEqual(r.status_code, 200)
        self.asig.refresh_from_db()
        self.assertIsNone(self.asig.entrenador)


class MoverPistaEnteraTests(AbrirPistaVaciaTests):
    """Una pista entera se lleva a otra: si está vacía se muda, y si tiene
    gente se intercambian."""

    def _mover_pista(self, **extra):
        cuerpo = {"semana": self.semana.id, "dia": 0, "turno": self.m1.id,
                  "desde_pista": self.p1.id, "pista": self.p2.id, **extra}
        return self.api.post("/api/asignaciones/mover_pista/", cuerpo, format="json")

    def test_se_muda_a_una_pista_vacia_con_su_entrenador(self):
        r = self._mover_pista()
        self.assertEqual(r.status_code, 200)
        self.asig.refresh_from_db()
        self.assertEqual(self.asig.pista, self.p2)
        self.assertEqual(self.asig.entrenador, self.coach)
        self.assertFalse(Asignacion.objects.filter(
            semana=self.semana, dia=0, turno=self.m1, pista=self.p1).exists())

    def test_con_gente_en_las_dos_se_intercambian(self):
        otra = Asignacion.objects.create(
            semana=self.semana, dia=0, turno=self.m1, pista=self.p2,
            jugador=self.b, entrenador=self.otro_coach)
        r = self._mover_pista()
        self.assertEqual(r.status_code, 200)
        self.asig.refresh_from_db(); otra.refresh_from_db()
        self.assertEqual(self.asig.pista, self.p2)
        self.assertEqual(otra.pista, self.p1)
        self.assertEqual(self.asig.entrenador, self.coach)
        self.assertEqual(otra.entrenador, self.otro_coach)

    def test_la_pista_vacia_no_se_puede_mover(self):
        r = self._mover_pista(desde_pista=self.p2.id, pista=self.p1.id)
        self.assertEqual(r.status_code, 409)

    def test_no_se_lleva_al_miercoles_por_la_tarde(self):
        r = self._mover_pista(dia=2, turno=self.t1.id)
        self.assertEqual(r.status_code, 400)

    def test_cambiar_de_franja_avisa_si_el_jugador_ya_esta_alli(self):
        # Ana ya entrena en T1, así que su pista de la mañana no puede mudarse
        # a esa franja.
        Asignacion.objects.create(semana=self.semana, dia=0, turno=self.t1,
                                  pista=self.p2, jugador=self.a)
        r = self._mover_pista(desde_turno=self.m1.id, turno=self.t1.id, pista=self.p1.id)
        self.assertEqual(r.status_code, 409)

    def test_se_puede_mudar_a_otra_franja(self):
        r = self._mover_pista(desde_turno=self.m1.id, turno=self.t1.id, pista=self.p1.id)
        self.assertEqual(r.status_code, 200)
        self.asig.refresh_from_db()
        self.assertEqual((self.asig.turno, self.asig.pista), (self.t1, self.p1))


class DeshacerTests(TestCase):
    """Cada cambio a mano deja una foto; deshacer vuelve a ella."""

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(User.objects.create_user(
            username="dir2", password="x", role=User.Role.SUPERADMIN))
        Sede.objects.update(activa=False)
        self.sede = Sede.objects.create(
            nombre="Prueba", densidad_default=2, densidad_max=2, activa=True)
        self.p1, self.p2 = [
            Pista.objects.create(sede=self.sede, numero=n, superficie="TIERRA")
            for n in (1, 2)
        ]
        self.m1, _ = Turno.objects.get_or_create(
            codigo="M1", defaults={"nombre": "M1", "bloque": Turno.Bloque.MANANA,
                                   "hora_inicio": time(8, 30),
                                   "hora_fin": time(10, 0), "orden": 1})
        self.semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)
        self.coach = Entrenador.objects.create(nombre="Blas")
        self.ana = Jugador.objects.create(nombre="Ana")
        self.asig = Asignacion.objects.create(
            semana=self.semana, dia=0, turno=self.m1, pista=self.p1,
            jugador=self.ana, entrenador=self.coach)

    def test_deshacer_devuelve_al_jugador_a_su_pista(self):
        r = self.api.post("/api/asignaciones/mover/", {
            "asignacion": self.asig.id, "pista": self.p2.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Asignacion.objects.get().pista_id, self.p2.id)

        r = self.api.post(f"/api/semanas/{self.semana.id}/deshacer/", {},
                          format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Asignacion.objects.get().pista_id, self.p1.id)

    def test_sin_cambios_no_hay_nada_que_deshacer(self):
        r = self.api.post(f"/api/semanas/{self.semana.id}/deshacer/", {},
                          format="json")
        self.assertEqual(r.status_code, 409)

    def test_deshace_de_uno_en_uno_y_en_orden(self):
        # Mover a una pista vacía la deja sin entrenador; después se le pone.
        self.api.post("/api/asignaciones/mover/", {
            "asignacion": self.asig.id, "pista": self.p2.id}, format="json")
        self.assertIsNone(Asignacion.objects.get().entrenador_id)
        self.api.post("/api/asignaciones/set_coach/", {
            "semana": self.semana.id, "dia": 0, "turno": self.m1.id,
            "pista": self.p2.id, "entrenador_id": self.coach.id}, format="json")
        self.assertEqual(Asignacion.objects.get().entrenador_id, self.coach.id)

        self.api.post(f"/api/semanas/{self.semana.id}/deshacer/", {}, format="json")
        a = Asignacion.objects.get()
        self.assertEqual((a.pista_id, a.entrenador_id), (self.p2.id, None))

        self.api.post(f"/api/semanas/{self.semana.id}/deshacer/", {}, format="json")
        a = Asignacion.objects.get()
        self.assertEqual((a.pista_id, a.entrenador_id), (self.p1.id, self.coach.id))


class MoverPistaSinDuplicarEntrenadorTests(TestCase):
    """Llevar una pista a otra franja no puede dejar al entrenador dando dos
    pistas a la vez."""

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(User.objects.create_user(
            username="dir3", password="x", role=User.Role.SUPERADMIN))
        Sede.objects.update(activa=False)
        self.sede = Sede.objects.create(
            nombre="Prueba", densidad_default=2, densidad_max=2, activa=True)
        self.p1, self.p2, self.p3 = [
            Pista.objects.create(sede=self.sede, numero=n, superficie="TIERRA")
            for n in (1, 2, 3)
        ]
        self.m1, _ = Turno.objects.get_or_create(
            codigo="M1", defaults={"nombre": "M1", "bloque": Turno.Bloque.MANANA,
                                   "hora_inicio": time(8, 30),
                                   "hora_fin": time(10, 0), "orden": 1})
        self.m2, _ = Turno.objects.get_or_create(
            codigo="M2", defaults={"nombre": "M2", "bloque": Turno.Bloque.MANANA,
                                   "hora_inicio": time(10, 30),
                                   "hora_fin": time(12, 30), "orden": 2})
        self.semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)
        self.coach = Entrenador.objects.create(nombre="Blas")
        a, b = [Jugador.objects.create(nombre=n) for n in ("Ana", "Bruno")]
        # El mismo entrenador ya da la pista 3 en M2.
        Asignacion.objects.create(
            semana=self.semana, dia=0, turno=self.m1, pista=self.p1,
            jugador=a, entrenador=self.coach)
        Asignacion.objects.create(
            semana=self.semana, dia=0, turno=self.m2, pista=self.p3,
            jugador=b, entrenador=self.coach)

    def test_no_deja_al_entrenador_en_dos_pistas(self):
        r = self.api.post("/api/asignaciones/mover_pista/", {
            "semana": self.semana.id, "dia": 0, "turno": self.m2.id,
            "pista": self.p2.id, "desde_pista": self.p1.id,
            "desde_dia": 0, "desde_turno": self.m1.id}, format="json")
        self.assertEqual(r.status_code, 409, r.data)
        self.assertIn("otra pista", r.data["error"])
        self.assertEqual(
            Asignacion.objects.filter(turno=self.m1, pista=self.p1).count(), 1)
