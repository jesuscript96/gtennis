"""El calendario de torneos: quién entra, quién toca a quién y que fusionar
no pierda a nadie. No toca faltas ni motor."""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from academy.models import (
    Aviso, Coach, Entrenador, Escuela, Invitado, Jugador, ResponsableJugador, VacacionesEntrenador,
)
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
        self.assertEqual(c.post(f"/api/torneos/{self.t1.id}/fusionar/", {"con": self.t2.id},
                                format="json").status_code, 403)
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


class EntrenadorApuntaTests(TestCase):
    """03/11/2026: el entrenador apunta a sus jugadores a torneos que ya
    existen; queda pendiente y avisa a su head coach, que confirma, mueve o
    quita. El entrenador solo quita lo suyo mientras siga pendiente."""

    def setUp(self):
        self.blas = Entrenador.objects.create(nombre="Blas")
        self.mario = Entrenador.objects.create(nombre="Mario")
        self.ana = Jugador.objects.create(nombre="Ana", entrenador_responsable=self.blas)
        self.leo = Jugador.objects.create(nombre="Leo", entrenador_responsable=self.mario)
        self.u_blas = User.objects.create_user(username="blas", password="x", role=User.Role.ENTRENADOR)
        self.blas.user = self.u_blas
        self.blas.save(update_fields=["user"])
        self.u_pablo = User.objects.create_user(username="pablo", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Pablo", user=self.u_pablo, color="turquesa").entrenadores.set([self.blas])
        self.u_dir = User.objects.create_user(username="dir", password="x", role=User.Role.SUPERADMIN)
        hoy = date.today()
        self.t = Torneo.objects.create(nombre="ITF J30 Silla", fecha_inicio=hoy + timedelta(days=14),
                                       fecha_fin=hoy + timedelta(days=20))
        self.otro = Torneo.objects.create(nombre="ITF J30 Valencia", fecha_inicio=hoy + timedelta(days=21),
                                          fecha_fin=hoy + timedelta(days=27))
        self.pasado = Torneo.objects.create(nombre="W15 Villena", fecha_inicio=hoy - timedelta(days=10),
                                            fecha_fin=hoy - timedelta(days=4))

    def api(self, u):
        c = APIClient()
        c.force_authenticate(u)
        return c

    def apuntar(self, u, jugador, torneo=None, **extra):
        return self.api(u).post("/api/torneos-participantes/",
                                {"torneo": (torneo or self.t).id, "jugador": jugador and jugador.id, **extra},
                                format="json")

    def test_apunta_a_su_jugador_pendiente_y_avisa_al_head_coach(self):
        r = self.apuntar(self.u_blas, self.ana, certeza="CONFIRMADO")
        self.assertEqual(r.status_code, 201, r.data)
        p = Participante.objects.get(pk=r.data["id"])
        self.assertEqual((p.nombre, p.certeza, p.apuntado_por), ("Ana", "PENDIENTE", self.u_blas))
        self.assertEqual((r.data["apuntado_por_nombre"], r.data["apuntado_por_mi"]), ("Blas", True))
        aviso = Aviso.objects.get()
        self.assertEqual(aviso.usuario, self.u_pablo)
        self.assertIn("Blas apunta a Ana a «ITF J30 Silla»", aviso.titulo)

    def test_sin_head_coach_avisa_a_direccion(self):
        Coach.objects.update(color="")
        self.apuntar(self.u_blas, self.ana)
        self.assertTrue(Aviso.objects.get().para_direccion)

    def test_no_apunta_a_los_que_no_son_suyos_ni_sin_ficha_ni_a_torneos_acabados(self):
        self.assertEqual(self.apuntar(self.u_blas, self.leo).status_code, 403)
        self.assertEqual(self.apuntar(self.u_blas, None, nombre="Invitado").status_code, 400)
        self.assertEqual(self.apuntar(self.u_blas, self.ana, self.pasado).status_code, 400)
        self.t.estado = Torneo.Estado.CANCELADO
        self.t.save()
        self.assertEqual(self.apuntar(self.u_blas, self.ana).status_code, 400)
        self.assertFalse(Participante.objects.exists())

    def test_no_mueve_ni_confirma(self):
        pid = self.apuntar(self.u_blas, self.ana).data["id"]
        c = self.api(self.u_blas)
        self.assertEqual(c.patch(f"/api/torneos-participantes/{pid}/", {"torneo": self.otro.id},
                                 format="json").status_code, 403)
        self.assertEqual(c.patch(f"/api/torneos-participantes/{pid}/", {"certeza": "CONFIRMADO"},
                                 format="json").status_code, 403)
        self.assertEqual(Participante.objects.get(pk=pid).torneo, self.t)

    def test_quita_lo_suyo_mientras_esta_pendiente(self):
        pid = self.apuntar(self.u_blas, self.ana).data["id"]
        self.assertEqual(self.api(self.u_blas).delete(f"/api/torneos-participantes/{pid}/").status_code, 204)
        # Lo confirmado ya no.
        pid = self.apuntar(self.u_blas, self.ana).data["id"]
        self.api(self.u_pablo).patch(f"/api/torneos-participantes/{pid}/", {"certeza": "CONFIRMADO"}, format="json")
        self.assertEqual(self.api(self.u_blas).delete(f"/api/torneos-participantes/{pid}/").status_code, 403)
        # Ni lo que apuntó otro.
        otra = self.apuntar(self.u_dir, self.ana, self.otro).data["id"]
        Participante.objects.filter(pk=otra).update(certeza="PENDIENTE")
        self.assertEqual(self.api(self.u_blas).delete(f"/api/torneos-participantes/{otra}/").status_code, 403)

    def test_el_head_coach_confirma_y_mueve(self):
        pid = self.apuntar(self.u_blas, self.ana).data["id"]
        c = self.api(self.u_pablo)
        self.assertEqual(c.patch(f"/api/torneos-participantes/{pid}/", {"torneo": self.otro.id},
                                 format="json").status_code, 200)
        r = c.patch(f"/api/torneos-participantes/{pid}/", {"certeza": "CONFIRMADO"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        p = Participante.objects.get(pk=pid)
        self.assertEqual((p.torneo, p.certeza, p.apuntado_por), (self.otro, "CONFIRMADO", self.u_blas))

    def test_lo_que_apunta_el_head_coach_va_confirmado(self):
        r = self.apuntar(self.u_pablo, self.ana)
        self.assertEqual((r.data["certeza"], r.data["apuntado_por_nombre"]), ("CONFIRMADO", "pablo"))
        self.assertFalse(Aviso.objects.exists())

    def test_por_confirmar(self):
        pid = self.apuntar(self.u_blas, self.ana).data["id"]
        url = "/api/torneos-participantes/por_confirmar/"
        for u in (self.u_blas, self.u_pablo, self.u_dir):
            r = self.api(u).get(url)
            self.assertEqual([(x["id"], x["torneo_detalle"]["nombre"]) for x in r.data], [(pid, "ITF J30 Silla")])
        # Un head coach de otro grupo no lo ve.
        u_santi = User.objects.create_user(username="santi", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Santi", user=u_santi, color="naranja").entrenadores.set([self.mario])
        self.assertEqual(self.api(u_santi).get(url).data, [])
        self.api(self.u_pablo).patch(f"/api/torneos-participantes/{pid}/", {"certeza": "CONFIRMADO"}, format="json")
        self.assertEqual(self.api(self.u_pablo).get(url).data, [])

    def test_deshace_lo_suyo(self):
        self.apuntar(self.u_blas, self.ana)
        r = self.api(self.u_blas).post("/api/torneos-cambios/deshacer/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(Participante.objects.exists())

    def test_solo_los_de_su_columna_en_grupos(self):
        # Entrena con Blas (porcentaje) pero es de Mario: no es suyo.
        pau = Jugador.objects.create(nombre="Pau", entrenador_responsable=self.mario)
        ResponsableJugador.objects.create(jugador=pau, entrenador=self.blas, prioridad=2)
        # Comparte la gestión con Blas: sí.
        iris = Jugador.objects.create(nombre="Iris", entrenador_responsable=self.mario)
        iris.cogestores.add(self.blas)
        # Invitado de Blas: no va a torneos.
        inv = Jugador.objects.create(nombre="Kira (invitado)", entrenador_responsable=self.blas)
        Invitado.objects.create(nombre="Kira", entrenador_solicitante=self.blas, jugador_creado=inv)
        lista = self.api(self.u_blas).get("/api/torneos-participantes/jugadores/").data
        self.assertEqual([(j["nombre"], j["entrenador"]) for j in lista],
                         [("Ana", "Blas"), ("Iris", "Mario y Blas")])
        self.assertEqual(self.apuntar(self.u_blas, pau).status_code, 403)
        self.assertEqual(self.apuntar(self.u_blas, iris).status_code, 201)
        # El head coach de Blas: su columna entera, no los que solo entrenan con él.
        # (más las altas sin entrenador, que en la base de pruebas ya hay).
        nombres = {j["nombre"] for j in self.api(self.u_pablo).get("/api/torneos-participantes/jugadores/").data}
        self.assertTrue({"Ana", "Iris"} <= nombres)
        self.assertFalse({"Pau", "Leo", "Kira (invitado)"} & nombres)
        self.assertEqual(self.apuntar(self.u_pablo, pau).status_code, 403)
        nombres = {j["nombre"] for j in self.api(self.u_dir).get("/api/torneos-participantes/jugadores/").data}
        self.assertTrue({"Ana", "Iris", "Pau", "Leo"} <= nombres)
        self.assertNotIn("Kira (invitado)", nombres)

    def test_notas_y_entrenador_al_apuntar(self):
        r = self.apuntar(self.u_blas, self.ana, detalle="Solo la previa")
        self.assertEqual((r.data["detalle"], r.data["entrenador"]), ("Solo la previa", "Blas"))
        r = self.api(self.u_pablo).get(f"/api/torneos/{self.t.id}/")
        self.assertEqual([(p["nombre"], p["entrenador"], p["detalle"]) for p in r.data["participantes"]],
                         [("Ana", "Blas", "Solo la previa")])

    def test_deshacer_conserva_quien_lo_apunto(self):
        pid = self.apuntar(self.u_blas, self.ana).data["id"]
        self.api(self.u_dir).delete(f"/api/torneos-participantes/{pid}/")
        self.api(self.u_dir).post("/api/torneos-cambios/deshacer/", {}, format="json")
        self.assertEqual(Participante.objects.get(pk=pid).apuntado_por, self.u_blas)


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


class CategoriasTests(TestCase):
    """03/11/2026: un torneo es de una o varias categorías de edad (los años
    que se cumplen en el año del torneo) y a él se apuntan los de esas o los
    de una más pequeña."""

    def setUp(self):
        self.u_dir = User.objects.create_user(username="dir", password="x", role=User.Role.SUPERADMIN)
        self.c = APIClient()
        self.c.force_authenticate(self.u_dir)
        self.alevin = Jugador.objects.create(nombre="Alevín", fecha_nacimiento=date(2014, 12, 31))    # 12 en 2026
        self.infantil = Jugador.objects.create(nombre="Infantil", fecha_nacimiento=date(2012, 1, 1))  # 14 en 2026
        self.cadete = Jugador.objects.create(nombre="Cadete", fecha_nacimiento=date(2011, 6, 15))    # 15 en 2026
        self.sin_fecha = Jugador.objects.create(nombre="Sin fecha")
        self.t = Torneo.objects.create(nombre="Valencia Tennis Tour", fecha_inicio="2026-11-07",
                                       fecha_fin="2026-11-14", categorias=["SUB12", "SUB14"])

    def apuntar(self, jugador, torneo=None):
        return self.c.post("/api/torneos-participantes/", {"torneo": (torneo or self.t).id, "jugador": jugador.id},
                           format="json")

    def test_categoria_por_los_anios_que_cumple_en_el_anio_del_torneo(self):
        from .categorias import categoria_de
        self.assertEqual(categoria_de(self.infantil, 2026), "SUB14")
        self.assertEqual(categoria_de(self.infantil, 2027), "SUB16")
        self.assertEqual(categoria_de(self.alevin, 2026), "SUB12")
        self.assertIsNone(categoria_de(self.sin_fecha, 2026))
        self.assertEqual(categoria_de(Jugador(fecha_nacimiento=date(1990, 1, 1)), 2026), "ABSOLUTA")

    def test_se_apuntan_los_de_su_categoria_o_mas_pequenos(self):
        self.assertEqual(self.apuntar(self.alevin).status_code, 201)
        self.assertEqual(self.apuntar(self.infantil).status_code, 201)
        self.assertEqual(self.apuntar(self.sin_fecha).status_code, 201)
        r = self.apuntar(self.cadete)
        self.assertEqual(r.status_code, 400)
        self.assertIn("cadete en 2026", str(r.data["detail"]))
        # Un benjamín también entra en un torneo infantil.
        benjamin = Jugador.objects.create(nombre="Benjamín", fecha_nacimiento=date(2017, 3, 1))
        self.assertEqual(self.apuntar(benjamin).status_code, 201)

    def test_en_enero_ya_cuenta_el_anio_nuevo(self):
        t = Torneo.objects.create(nombre="Enero", fecha_inicio="2027-01-11", fecha_fin="2027-01-17",
                                  categorias=["SUB14"])
        self.assertEqual(self.apuntar(self.infantil, t).status_code, 400)  # 15 en 2027

    def test_sin_categorias_no_hay_limite(self):
        t = Torneo.objects.create(nombre="Libre", fecha_inicio="2026-11-07", fecha_fin="2026-11-14")
        self.assertEqual(self.apuntar(self.cadete, t).status_code, 201)

    def test_no_se_mueve_a_un_torneo_de_categoria_menor(self):
        absoluto = Torneo.objects.create(nombre="Absoluto", fecha_inicio="2026-11-07", fecha_fin="2026-11-14",
                                         categorias=["ABSOLUTA"])
        pid = self.apuntar(self.cadete, absoluto).data["id"]
        r = self.c.patch(f"/api/torneos-participantes/{pid}/", {"torneo": self.t.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Participante.objects.get(pk=pid).torneo, absoluto)

    def test_el_desplegable_solo_ofrece_los_que_entran(self):
        r = self.c.get(f"/api/torneos-participantes/jugadores/?torneo={self.t.id}")
        mios = {j["nombre"]: j["categoria"] for j in r.data if j["id"] in
                {self.alevin.id, self.infantil.id, self.cadete.id, self.sin_fecha.id}}
        self.assertEqual(mios, {"Alevín": "Alevín", "Infantil": "Infantil", "Sin fecha": None})

    def test_sin_fecha_vale_la_categoria_fijada(self):
        from .models import CategoriaJugador
        CategoriaJugador.objects.create(jugador=self.sin_fecha, categoria="ABSOLUTA")
        self.assertEqual(self.apuntar(self.sin_fecha).status_code, 400)
        absoluto = Torneo.objects.create(nombre="Absoluto", fecha_inicio="2026-11-07", fecha_fin="2026-11-14",
                                         categorias=["ABSOLUTA"])
        self.assertEqual(self.apuntar(self.sin_fecha, absoluto).status_code, 201)
        r = self.c.get(f"/api/torneos-participantes/jugadores/?torneo={absoluto.id}")
        self.assertIn(("Sin fecha", "Absoluta"), [(j["nombre"], j["categoria"]) for j in r.data])
        # Si se le pone la fecha, manda la fecha.
        self.sin_fecha.fecha_nacimiento = date(2014, 5, 5)
        self.sin_fecha.save()
        self.assertEqual(self.apuntar(self.sin_fecha).status_code, 201)

    def test_categorias_validas_y_ordenadas(self):
        r = self.c.patch(f"/api/torneos/{self.t.id}/", {"categorias": ["SUB16", "SUB10", "SUB16"]}, format="json")
        self.assertEqual(r.data["categorias"], ["SUB10", "SUB16"])
        r = self.c.patch(f"/api/torneos/{self.t.id}/", {"categorias": ["Cadete"]}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_avisa_si_queda_fuera_de_categoria(self):
        self.apuntar(self.infantil)
        self.c.patch(f"/api/torneos/{self.t.id}/", {"categorias": ["SUB12"]}, format="json")
        p = self.c.get(f"/api/torneos/{self.t.id}/").data["participantes"][0]
        self.assertEqual((p["categoria"], p["fuera_de_categoria"]), ("Infantil", True))
        # Deshacer devuelve también las categorías.
        self.c.post("/api/torneos-cambios/deshacer/", {}, format="json")
        self.assertEqual(Torneo.objects.get(pk=self.t.id).categorias, ["SUB12", "SUB14"])


class PeticionesDiezNoviembreTests(TestCase):
    """10/11/2026: varios entrenadores por torneo, fuera los dados de baja y
    fecha límite de borrado. Mismo escenario que TorneosTests."""

    setUp = TorneosTests.setUp
    api = TorneosTests.api

    def test_varios_entrenadores_acompanan(self):
        c = self.api(self.u_pablo)
        r = c.patch(f"/api/torneos/{self.t1.id}/", {"acompanantes": [self.blas.id, self.mario.id]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual({e["nombre"] for e in r.data["acompanantes_detalle"]}, {"Blas", "Mario"})
        c.post("/api/torneos-cambios/deshacer/", {}, format="json")
        self.assertFalse(Torneo.objects.get(pk=self.t1.id).acompanantes.exists())

    def test_ir_de_torneo_no_le_esconde_del_desplegable(self):
        # En el cuadrante se le marca «Torneo» justo porque acompaña: no cuenta.
        VacacionesEntrenador.objects.create(entrenador=self.mario, fecha_inicio="2026-10-26",
                                            fecha_fin="2026-11-01", motivo="Torneo")
        VacacionesEntrenador.objects.create(entrenador=self.blas, fecha_inicio="2026-10-26",
                                            fecha_fin="2026-11-01", motivo="Vacaciones")
        r = self.api(self.u_pablo).get("/api/torneos/entrenadores/?desde=2026-10-26&hasta=2026-11-01")
        vac = {e["nombre"]: len(e["vacaciones"]) for e in r.data}
        self.assertEqual((vac["Mario"], vac["Blas"]), (0, 1))

    def test_los_dados_de_baja_no_se_ofrecen_ni_se_apuntan(self):
        hoy = date.today()
        tf = Torneo.objects.create(nombre="Futuro", fecha_inicio=hoy + timedelta(days=20),
                                   fecha_fin=hoy + timedelta(days=22))
        # Ana se va antes de que empiece; Leo ya no está.
        self.ana.fecha_baja = hoy + timedelta(days=5)
        self.ana.save()
        self.leo.activo = False
        self.leo.save()
        c = self.api(self.u_dir)
        nombres = {j["nombre"] for j in c.get(f"/api/torneos-participantes/jugadores/?torneo={tf.id}").data}
        self.assertFalse({"Ana", "Leo"} & nombres)
        # Sin torneo, Ana sigue: aún entrena.
        nombres = {j["nombre"] for j in c.get("/api/torneos-participantes/jugadores/").data}
        self.assertIn("Ana", nombres)
        self.assertNotIn("Leo", nombres)
        r = c.post("/api/torneos-participantes/", {"torneo": tf.id, "jugador": self.ana.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("dado de baja", str(r.data))
        # Lo de antes se queda, marcado.
        Participante.objects.create(torneo=self.t1, jugador=self.leo, nombre="Leo")
        filas = {f["nombre"]: f["de_baja"] for f in c.get("/api/torneos/por_jugador/").data}
        self.assertTrue(filas["Leo"])
        lista = c.get("/api/torneos/?desde=2026-10-26&hasta=2026-11-01").data
        jug = next(t for t in lista if t["id"] == self.t1.id)["jugadores"]
        self.assertEqual([(j["nombre"], j["de_baja"]) for j in jug], [("Leo", True)])
        self.assertTrue(c.get(f"/api/torneos/{self.t1.id}/").data["participantes"][0]["de_baja"])

    def test_fecha_limite_de_borrado(self):
        c = self.api(self.u_pablo)
        r = c.patch(f"/api/torneos/{self.t1.id}/", {"fecha_borrado": "2026-10-20"}, format="json")
        self.assertEqual((r.status_code, r.data["fecha_borrado"]), (200, "2026-10-20"))
        r = c.patch(f"/api/torneos/{self.t1.id}/", {"fecha_borrado": "2026-11-05"}, format="json")
        self.assertEqual(r.status_code, 400)
        c.patch(f"/api/torneos/{self.t1.id}/", {"fecha_borrado": "2026-10-22"}, format="json")
        c.post("/api/torneos-cambios/deshacer/", {}, format="json")
        self.assertEqual(str(Torneo.objects.get(pk=self.t1.id).fecha_borrado), "2026-10-20")
        # Al fusionar se conserva.
        r = self.api(self.u_dir).post(f"/api/torneos/{self.t2.id}/fusionar/", {"con": self.t1.id}, format="json")
        self.assertEqual(r.data["fecha_borrado"], "2026-10-20")


class PabloTodaLaAcademiaTests(TestCase):
    """10/11/2026: Pablo (pablo.gil) apunta y quita en torneos a cualquier
    jugador de la academia, no solo a los de su grupo; los de Competición de
    tardes, no. El resto de head coaches sigue con su grupo."""

    setUp_base = TorneosTests.setUp
    api = TorneosTests.api

    def setUp(self):
        self.setUp_base()
        self.u_pablo_gil = User.objects.create_user(username="pablo.gil", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Pablo Gil", user=self.u_pablo_gil).entrenadores.set([self.blas])
        tardes = Escuela.objects.create(nombre="Competición de tardes", solo_informes=True)
        self.tito = Jugador.objects.create(nombre="Tito", escuela=tardes, entrenador_responsable=self.mario)
        hoy = date.today()
        self.tf = Torneo.objects.create(nombre="Futuro", fecha_inicio=hoy + timedelta(days=20),
                                        fecha_fin=hoy + timedelta(days=22))

    def test_le_salen_todos_menos_los_de_tardes(self):
        nombres = {j["nombre"] for j in
                   self.api(self.u_pablo_gil).get("/api/torneos-participantes/jugadores/").data}
        self.assertTrue({"Ana", "Leo"} <= nombres)
        self.assertNotIn("Tito", nombres)
        # El otro head coach, solo los de su grupo: Leo es de Mario.
        nombres = {j["nombre"] for j in self.api(self.u_pablo).get("/api/torneos-participantes/jugadores/").data}
        self.assertIn("Ana", nombres)
        self.assertNotIn("Leo", nombres)

    def test_apunta_mueve_y_quita_a_uno_de_otro_grupo(self):
        c = self.api(self.u_pablo_gil)
        r = c.post("/api/torneos-participantes/", {"torneo": self.tf.id, "jugador": self.leo.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertNotEqual(Participante.objects.get(pk=r.data["id"]).certeza, Participante.Certeza.PENDIENTE)
        r = c.patch(f"/api/torneos-participantes/{r.data['id']}/", {"torneo": self.t2.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        # Uno que apuntó dirección, también lo quita.
        p = Participante.objects.create(torneo=self.t1, jugador=self.leo, nombre="Leo")
        self.assertEqual(c.delete(f"/api/torneos-participantes/{p.id}/").status_code, 204)
        # El otro head coach no puede.
        p = Participante.objects.create(torneo=self.t1, jugador=self.leo, nombre="Leo")
        self.assertEqual(self.api(self.u_pablo).delete(f"/api/torneos-participantes/{p.id}/").status_code, 403)

    def test_los_de_tardes_no(self):
        c = self.api(self.u_pablo_gil)
        r = c.post("/api/torneos-participantes/", {"torneo": self.tf.id, "jugador": self.tito.id}, format="json")
        self.assertEqual(r.status_code, 403)
        p = Participante.objects.create(torneo=self.t1, jugador=self.tito, nombre="Tito")
        self.assertEqual(c.delete(f"/api/torneos-participantes/{p.id}/").status_code, 403)

    def test_ve_por_confirmar_de_toda_la_academia(self):
        u_mario = User.objects.create_user(username="mario", password="x", role=User.Role.ENTRENADOR)
        self.mario.user = u_mario
        self.mario.save(update_fields=["user"])
        r = self.api(u_mario).post("/api/torneos-participantes/", {"torneo": self.tf.id, "jugador": self.leo.id},
                                   format="json")
        self.assertEqual(r.status_code, 201, r.data)
        nombres = [p["nombre"] for p in
                   self.api(self.u_pablo_gil).get("/api/torneos-participantes/por_confirmar/").data]
        self.assertEqual(nombres, ["Leo"])
