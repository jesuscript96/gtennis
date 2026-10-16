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

    def test_el_entrenador_lo_ve_pero_no_lo_cambia(self):
        c = self.api(self.u_blas)
        self.assertEqual(c.get("/api/torneos/").status_code, 200)
        self.assertEqual(c.get(f"/api/torneos/{self.t1.id}/").status_code, 200)
        self.assertEqual(c.get("/api/torneos/por_jugador/").status_code, 200)
        self.assertEqual(c.post("/api/torneos/", {"nombre": "X", "fecha_inicio": "2026-11-02",
                                                 "fecha_fin": "2026-11-02"}, format="json").status_code, 403)
        self.assertEqual(c.patch(f"/api/torneos/{self.t1.id}/", {"lugar": "Y"}, format="json").status_code, 403)
        self.assertEqual(c.delete(f"/api/torneos/{self.t1.id}/").status_code, 403)
        self.assertEqual(c.post("/api/torneos-participantes/", {"torneo": self.t1.id, "jugador": self.ana.id},
                                format="json").status_code, 403)
        self.assertEqual(c.post(f"/api/torneos/{self.t1.id}/fusionar/", {"con": self.t2.id},
                                format="json").status_code, 403)
        self.assertEqual(c.post("/api/torneos-cambios/deshacer/", {}, format="json").status_code, 403)
        self.assertTrue(Torneo.objects.filter(pk=self.t1.id, lugar="").exists())

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


class DeshacerTests(TestCase):
    """Cada cambio se puede deshacer; cada uno deshace lo suyo y no pisa lo de otro."""

    def setUp(self):
        self.blas = Entrenador.objects.create(nombre="Blas")
        self.ana = Jugador.objects.create(nombre="Ana", entrenador_responsable=self.blas)
        ResponsableJugador.objects.create(jugador=self.ana, entrenador=self.blas, prioridad=1)
        self.u_pablo = User.objects.create_user(username="pablo", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Pablo", user=self.u_pablo).entrenadores.set([self.blas])
        self.u_dir = User.objects.create_user(username="dir", password="x", role=User.Role.SUPERADMIN)
        self.villena = Torneo.objects.create(nombre="W15 Villena", fecha_inicio="2026-10-19",
                                             fecha_fin="2026-10-25", cierre_inscripcion="2026-09-29")
        self.silla = Torneo.objects.create(nombre="Pre. Qualy Silla", fecha_inicio="2026-10-19", fecha_fin="2026-10-25")
        self.villena.acompanantes.add(self.blas)
        self.p = Participante.objects.create(torneo=self.villena, jugador=self.ana, nombre="Ana", certeza="DEDUCIDO")

    def api(self, u):
        c = APIClient()
        c.force_authenticate(u)
        return c

    def deshacer(self, u):
        return self.api(u).post("/api/torneos-cambios/deshacer/", {}, format="json")

    def test_deshacer_un_movimiento(self):
        self.api(self.u_pablo).patch(f"/api/torneos-participantes/{self.p.id}/", {"torneo": self.silla.id}, format="json")
        self.assertEqual(Participante.objects.get(pk=self.p.id).torneo_id, self.silla.id)
        r = self.deshacer(self.u_pablo)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("Mover a Ana", r.data["deshecho"])
        p = Participante.objects.get(pk=self.p.id)
        self.assertEqual((p.torneo_id, p.certeza, p.jugador_id), (self.villena.id, "DEDUCIDO", self.ana.id))
        self.assertFalse(self.silla.participantes.exists())

    def test_deshacer_un_borrado_lo_devuelve_entero(self):
        creado = Torneo.objects.get(pk=self.villena.id).created_at
        self.api(self.u_dir).delete(f"/api/torneos/{self.villena.id}/")
        self.assertFalse(Torneo.objects.filter(pk=self.villena.id).exists())
        r = self.deshacer(self.u_dir)
        self.assertEqual(r.status_code, 200, r.data)
        t = Torneo.objects.get(pk=self.villena.id)
        self.assertEqual(str(t.cierre_inscripcion), "2026-09-29")
        self.assertEqual(t.created_at, creado)
        self.assertEqual(list(t.acompanantes.values_list("nombre", flat=True)), ["Blas"])
        self.assertEqual(list(t.participantes.values_list("id", flat=True)), [self.p.id])

    def test_deshacer_un_alta_la_borra(self):
        r = self.api(self.u_dir).post("/api/torneos/", {"nombre": "Nuevo", "fecha_inicio": "2026-11-02",
                                                       "fecha_fin": "2026-11-08"}, format="json")
        tid = r.data["id"]
        r = self.deshacer(self.u_dir)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(Torneo.objects.filter(pk=tid).exists())
        self.assertEqual(r.data["existen"], [])

    def test_deshacer_una_fusion(self):
        Participante.objects.create(torneo=self.silla, nombre="Invitada")
        self.api(self.u_dir).post(f"/api/torneos/{self.villena.id}/fusionar/", {"con": self.silla.id}, format="json")
        self.assertFalse(Torneo.objects.filter(pk=self.silla.id).exists())
        self.deshacer(self.u_dir)
        self.assertEqual(list(Torneo.objects.get(pk=self.silla.id).participantes.values_list("nombre", flat=True)),
                         ["Invitada"])
        self.assertEqual(list(Torneo.objects.get(pk=self.villena.id).participantes.values_list("nombre", flat=True)),
                         ["Ana"])
        self.assertNotIn("Pre. Qualy Silla", Torneo.objects.get(pk=self.villena.id).alias)

    def test_se_deshace_en_orden_y_cada_uno_lo_suyo(self):
        c = self.api(self.u_dir)
        c.patch(f"/api/torneos/{self.villena.id}/", {"acompanantes": []}, format="json")
        c.patch(f"/api/torneos/{self.villena.id}/", {"lugar": "Villena"}, format="json")
        self.assertEqual(self.deshacer(self.u_pablo).status_code, 404)  # Pablo no ha hecho nada
        r = self.deshacer(self.u_dir)
        self.assertIn("Cambios en", r.data["deshecho"])
        self.assertIn("Acompañante de", r.data["siguiente"])
        self.assertEqual(Torneo.objects.get(pk=self.villena.id).lugar, "")
        self.deshacer(self.u_dir)
        self.assertEqual(list(Torneo.objects.get(pk=self.villena.id).acompanantes.all()), [self.blas])

    def test_no_pisa_lo_que_otro_hizo_despues(self):
        self.api(self.u_pablo).patch(f"/api/torneos-participantes/{self.p.id}/", {"torneo": self.silla.id}, format="json")
        self.api(self.u_dir).patch(f"/api/torneos/{self.silla.id}/", {"lugar": "Silla"}, format="json")
        r = self.deshacer(self.u_pablo)
        self.assertEqual(r.status_code, 409)
        self.assertIn("dir", r.data["detail"])
        self.assertEqual(Participante.objects.get(pk=self.p.id).torneo_id, self.silla.id)


class PreviaTests(TestCase):
    """Días de previa antes del cuadro final y torneos de fin de semana."""

    def setUp(self):
        self.u_dir = User.objects.create_user(username="dir", password="x", role=User.Role.SUPERADMIN)
        self.c = APIClient()
        self.c.force_authenticate(self.u_dir)

    def alta(self, **extra):
        return self.c.post("/api/torneos/", {"nombre": "ITF J60 La Nucía", "fecha_inicio": "2026-10-19",
                                            "fecha_fin": "2026-10-25", **extra}, format="json")

    def test_previa_valida(self):
        r = self.alta(qualy_inicio="2026-10-17", qualy_fin="2026-10-18", solo_fines_semana=False)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["qualy_inicio"], r.data["qualy_fin"]), ("2026-10-17", "2026-10-18"))

    def test_previa_sin_fin_acaba_al_empezar_el_cuadro(self):
        r = self.alta(qualy_inicio="2026-10-17")
        self.assertEqual(r.data["qualy_fin"], "2026-10-19")

    def test_previa_despues_del_cuadro_no(self):
        self.assertEqual(self.alta(qualy_inicio="2026-10-17", qualy_fin="2026-10-21").status_code, 400)
        self.assertEqual(self.alta(qualy_inicio="2026-10-18", qualy_fin="2026-10-17").status_code, 400)
        self.assertEqual(self.alta(qualy_fin="2026-10-18").status_code, 400)

    def test_la_previa_cuenta_para_la_semana(self):
        self.alta(qualy_inicio="2026-10-17", qualy_fin="2026-10-18")
        # La semana del 12 al 18 no llega al cuadro final, pero sí a la previa.
        r = self.c.get("/api/torneos/?desde=2026-10-12&hasta=2026-10-18")
        self.assertEqual([t["nombre"] for t in r.data], ["ITF J60 La Nucía"])

    def test_deshacer_y_fusionar_conservan_la_previa(self):
        tid = self.alta(qualy_inicio="2026-10-17", qualy_fin="2026-10-18").data["id"]
        self.c.patch(f"/api/torneos/{tid}/", {"qualy_inicio": None, "qualy_fin": None}, format="json")
        self.c.post("/api/torneos-cambios/deshacer/", {}, format="json")
        self.assertEqual(str(Torneo.objects.get(pk=tid).qualy_inicio), "2026-10-17")
        otro = Torneo.objects.create(nombre="La Nucia J60", fecha_inicio="2026-10-19", fecha_fin="2026-10-25",
                                     solo_fines_semana=True)
        r = self.c.post(f"/api/torneos/{otro.id}/fusionar/", {"con": tid}, format="json")
        self.assertEqual((r.data["qualy_inicio"], r.data["solo_fines_semana"]), ("2026-10-17", True))
