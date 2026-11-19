"""El banquillo del cuadrante (19/11/2026): solo quien ese día debería entrenar
y no tiene pista; los que tienen falta, aparte. Y en la tabla de entrenadores,
solo quien trabaja ese día."""
from datetime import date, time, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from academy.models import (
    Entrenador, HorarioEntrenador, HorarioJugador, Invitado, Jugador, Pista, Sede,
    Turno, VisitaInvitado,
)
from scheduling.models import AusenciaJugador, Disponibilidad, Estado, Semana
from users.models import User

LUNES = date(2026, 9, 14)


class BanquilloDelDiaTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.dir = User.objects.create_user(
            username="direccion", password="x", role=User.Role.SUPERADMIN)
        self.api.force_authenticate(self.dir)
        Sede.objects.update(activa=False)
        sede = Sede.objects.create(nombre="Prueba", densidad_default=2, densidad_max=2, activa=True)
        Pista.objects.create(sede=sede, numero=1, superficie="TIERRA")
        Turno.objects.exclude(codigo__in=["M1", "T1"]).update(activo=False)
        self.m1, _ = Turno.objects.get_or_create(
            codigo="M1", defaults={"nombre": "M1", "bloque": Turno.Bloque.MANANA,
                                   "hora_inicio": time(8, 30), "hora_fin": time(10, 0), "orden": 1})
        self.t1, _ = Turno.objects.get_or_create(
            codigo="T1", defaults={"nombre": "T1", "bloque": Turno.Bloque.TARDE,
                                   "hora_inicio": time(14, 15), "hora_fin": time(15, 30), "orden": 4})
        self.semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)
        self.ana = Jugador.objects.create(nombre="Ana")

    def banquillo(self, dia=0):
        r = self.api.get(f"/api/semanas/{self.semana.id}/panel/?dia={dia}")
        self.assertEqual(r.status_code, 200, r.content)
        datos = r.json()
        return {j["nombre"]: j
                for g in datos["por_entrenador"] + datos["sin_entrenador"]
                for j in g["jugadores"] if not j["tiene_asignacion"]}

    def entrenadores(self, dia=0):
        r = self.api.get(f"/api/semanas/{self.semana.id}/panel/?dia={dia}")
        return [e["nombre"] for e in r.json()["entrenadores"]]

    def test_sin_horario_viene_todos_los_dias(self):
        self.assertIn("Ana", self.banquillo(0))
        self.assertFalse(self.banquillo(0)["Ana"]["falta"])

    def test_el_dia_que_no_le_toca_no_sale(self):
        HorarioJugador.objects.create(jugador=self.ana, dia=0,
                                      entrena_manana=False, entrena_tarde=False)
        HorarioJugador.objects.create(jugador=self.ana, dia=1,
                                      entrena_manana=True, entrena_tarde=False)
        self.assertNotIn("Ana", self.banquillo(0))
        self.assertIn("Ana", self.banquillo(1))

    def test_altas_que_no_han_empezado_y_bajas_pasadas_no_salen(self):
        Jugador.objects.create(nombre="Nueva", fecha_alta=LUNES + timedelta(days=3))
        Jugador.objects.create(nombre="Se fue", fecha_baja=LUNES - timedelta(days=1))
        banquillo = self.banquillo(0)
        self.assertNotIn("Nueva", banquillo)
        self.assertNotIn("Se fue", banquillo)
        # El día que empieza, ya sí.
        self.assertIn("Nueva", self.banquillo(3))

    def test_el_invitado_solo_el_dia_de_su_visita(self):
        coach = Entrenador.objects.create(nombre="Pablo")
        jug = Jugador.objects.create(nombre="Invitada")
        inv = Invitado.objects.create(nombre="Invitada", entrenador_solicitante=coach,
                                      estado="APROBADO", jugador_creado=jug)
        VisitaInvitado.objects.create(invitado=inv, fecha=LUNES + timedelta(days=1),
                                      manana="M1", estado=VisitaInvitado.Estado.APROBADA)
        self.assertNotIn("Invitada", self.banquillo(0))
        self.assertIn("Invitada", self.banquillo(1))

    def test_la_falta_sale_aparte_con_su_motivo(self):
        AusenciaJugador.objects.create(jugador=self.ana, fecha_inicio=LUNES, fecha_fin=LUNES,
                                       estado=Estado.EN_TORNEO)
        ana = self.banquillo(0)["Ana"]
        self.assertTrue(ana["falta"])
        self.assertEqual(ana["estado"], Estado.EN_TORNEO)
        # Al día siguiente vuelve a venir.
        self.assertFalse(self.banquillo(1)["Ana"]["falta"])

    def test_falta_solo_por_la_manana_sigue_viniendo_por_la_tarde(self):
        AusenciaJugador.objects.create(jugador=self.ana, fecha_inicio=LUNES, fecha_fin=LUNES,
                                       ambito="MANANA")
        self.assertFalse(self.banquillo(0)["Ana"]["falta"])

    def test_viene_ademas_un_dia_que_no_le_toca(self):
        HorarioJugador.objects.create(jugador=self.ana, dia=0,
                                      entrena_manana=False, entrena_tarde=False)
        Disponibilidad.objects.create(semana=self.semana, jugador=self.ana, dia=0,
                                      ambito="M1", estado=Estado.EXTRA)
        ana = self.banquillo(0)["Ana"]
        self.assertFalse(ana["falta"])
        self.assertEqual(ana["estado"], Estado.EXTRA)

    def test_entrenador_de_solo_sabados(self):
        milla = Entrenador.objects.create(nombre="Jorge Milla", solo_manual=True)
        for dia in range(6):
            HorarioEntrenador.objects.create(entrenador=milla, dia=dia,
                                             manana=dia == 5, tarde=False)
        self.assertNotIn("Jorge Milla", self.entrenadores(0))
        self.assertIn("Jorge Milla", self.entrenadores(5))

    def test_el_de_vacaciones_sigue_saliendo_con_su_motivo(self):
        from academy.models import VacacionesEntrenador

        nacho = Entrenador.objects.create(nombre="Nacho")
        VacacionesEntrenador.objects.create(entrenador=nacho, fecha_inicio=LUNES,
                                            fecha_fin=LUNES, motivo="Torneo")
        self.assertIn("Nacho", self.entrenadores(0))
