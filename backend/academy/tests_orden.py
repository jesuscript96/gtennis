"""Las reglas del orden de la aplicación (10/11/2026): perfiles y funciones,
gestión en Grupos, división de dirección, reglas del jugador, un solo registro
de faltas, calendario del entrenador, quién toca el cuadrante, historial y
reabrir informes. Run: python manage.py test academy.tests_orden"""
from datetime import date, time
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from academy.models import (
    Coach, Division, Entrenador, Jugador, Pista, Rencilla, ResponsableJugador, Sede, Turno,
    VacacionesEntrenador,
)
from users.models import Funcion, User

LUNES = date(2026, 9, 14)


class Base(TestCase):
    """Dirección, un head coach de color (Pablo) con Blas y Javi, un
    entrenador con usuario (Blas) y otro entrenador fuera del grupo."""

    def setUp(self):
        self.dir = User.objects.create_user(username="dir", password="x", role=User.Role.SUPERADMIN)
        self.pablo = User.objects.create_user(username="pablo", password="x", role=User.Role.COACH)
        self.u_blas = User.objects.create_user(username="blas", password="x", role=User.Role.ENTRENADOR)
        self.blas = Entrenador.objects.create(nombre="Blas", user=self.u_blas)
        self.javi = Entrenador.objects.create(nombre="Javi")
        self.otro = Entrenador.objects.create(nombre="Otro")
        self.grupo = Coach.objects.create(nombre="Pablo", color="amarillo", user=self.pablo)
        self.grupo.entrenadores.set([self.blas, self.javi])
        self.ana = Jugador.objects.create(nombre="Ana Orden", entrenador_responsable=self.blas)
        self.ajeno = Jugador.objects.create(nombre="Ajeno Orden", entrenador_responsable=self.otro)

    def api(self, user):
        """Cliente con el usuario recién leído de la base: las funciones se
        cachean en el objeto durante una petición."""
        c = APIClient()
        c.force_authenticate(User.objects.get(pk=user.pk))
        return c

    def me(self, user):
        return self.api(user).get("/api/auth/me/").json()


class FuncionesTests(Base):
    def test_direccion_las_tiene_todas(self):
        me = self.me(self.dir)
        for clave in ("toca_cuadrante", "aprueba_invitados", "coordina_informes",
                      "valida_informes", "envia_informes", "mueve_divisiones", "coordina_fisico"):
            self.assertIs(me[clave], True, clave)
        # Las de equipo (19/11/2026: «Evalúa física de Alto rendimiento») se marcan también a dirección.
        self.assertEqual(set(me["funciones"]), set(Funcion.Codigo.values) - Funcion.EQUIPOS)

    def test_un_nombre_de_usuario_ya_no_da_nada(self):
        for nombre in ("daniel.gimeno", "ivan.gallego", "alberto.sanz"):
            u = User.objects.create_user(username=nombre, password="x", role=User.Role.COACH)
            me = self.me(u)
            for clave in ("toca_cuadrante", "aprueba_invitados", "coordina_informes",
                          "valida_informes", "envia_informes", "mueve_divisiones"):
                self.assertIs(me[clave], False, f"{nombre}: {clave}")
        adm = User.objects.create_user(username="administracion", password="x", role=User.Role.ENTRENADOR)
        self.assertIs(self.me(adm)["envia_informes"], False)

    def test_direccion_marca_y_quita_funciones(self):
        url = f"/api/auth/personal/{self.pablo.id}/"
        self.assertIs(self.me(self.pablo)["toca_cuadrante"], False)
        r = self.api(self.dir).post(url, {"codigo": "TOCA_CUADRANTE", "activa": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["funciones"], ["TOCA_CUADRANTE"])
        f = Funcion.objects.get(usuario=self.pablo)
        self.assertEqual((f.codigo, f.asignada_por), ("TOCA_CUADRANTE", self.dir))
        self.assertIs(self.me(self.pablo)["toca_cuadrante"], True)
        # Marcarla dos veces no la duplica.
        self.api(self.dir).post(url, {"codigo": "TOCA_CUADRANTE", "activa": True}, format="json")
        self.assertEqual(Funcion.objects.filter(usuario=self.pablo).count(), 1)
        r = self.api(self.dir).post(url, {"codigo": "TOCA_CUADRANTE", "activa": False}, format="json")
        self.assertEqual(r.json()["funciones"], [])
        self.assertIs(self.me(self.pablo)["toca_cuadrante"], False)

    def test_las_de_tardes_son_el_equipo_de_tardes(self):
        from evaluaciones.models import MiembroTardes

        url = f"/api/auth/personal/{self.u_blas.id}/"
        r = self.api(self.dir).post(url, {"codigo": "TARDES_TENIS", "activa": True}, format="json")
        self.assertEqual(r.json()["tardes"], ["TENIS"])
        self.assertTrue(MiembroTardes.objects.filter(usuario=self.u_blas, funcion="TENIS").exists())
        self.assertIs(self.me(self.u_blas)["evalua_tenis_informes"], True)
        self.assertEqual(self.api(self.dir).post(url, {"codigo": "INVENTADA", "activa": True},
                                                 format="json").status_code, 400)

    def test_solo_direccion_marca_funciones_y_perfiles(self):
        url = f"/api/auth/personal/{self.u_blas.id}/"
        for u in (self.pablo, self.u_blas):
            c = self.api(u)
            self.assertEqual(c.post(url, {"codigo": "VALIDA_INFORMES", "activa": True},
                                    format="json").status_code, 403, u.username)
            self.assertEqual(c.patch(url, {"role": "SUPERADMIN"}, format="json").status_code, 403)
            self.assertEqual(c.get("/api/auth/personal/").status_code, 403)
        self.assertFalse(Funcion.objects.filter(usuario=self.u_blas).exists())
        self.assertEqual(User.objects.get(pk=self.u_blas.pk).role, "ENTRENADOR")
        self.assertEqual(self.api(self.dir).get("/api/auth/personal/").status_code, 200)

    def test_direccion_cambia_el_perfil(self):
        r = self.api(self.dir).patch(f"/api/auth/personal/{self.u_blas.id}/",
                                     {"role": "ADMINISTRACION"}, format="json")
        self.assertEqual((r.status_code, r.json()["perfil"]), (200, "administracion"))
        self.assertIs(self.me(self.u_blas)["envia_informes"], True)
        # Dirección no se quita a sí misma el perfil.
        r = self.api(self.dir).patch(f"/api/auth/personal/{self.dir.id}/",
                                     {"role": "COACH"}, format="json")
        self.assertEqual(r.status_code, 400)


class CoachesYEntrenadoresTests(Base):
    def test_un_head_coach_no_se_cambia_su_propio_bloque(self):
        c = self.api(self.pablo)
        url = f"/api/coaches/{self.grupo.id}/"
        self.assertEqual(c.get(url).status_code, 200)
        r = c.patch(url, {"entrenadores": [self.blas.id, self.javi.id, self.otro.id]}, format="json")
        self.assertEqual(r.status_code, 403, r.content)
        self.assertEqual(set(self.grupo.entrenadores.values_list("id", flat=True)),
                         {self.blas.id, self.javi.id})
        r = self.api(self.dir).patch(url, {"nombre": "Pablo Gil"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_un_head_coach_no_da_acceso_a_todos_ni_borra(self):
        c = self.api(self.pablo)
        url = f"/api/entrenadores/{self.blas.id}/"
        self.assertEqual(c.patch(url, {"gestiona_todos_jugadores": True}, format="json").status_code, 403)
        self.assertEqual(c.delete(url).status_code, 403)
        self.blas.refresh_from_db()
        self.assertEqual((self.blas.gestiona_todos_jugadores, self.blas.activo), (False, True))
        # Dar de baja y de alta a los de su grupo, sí (como antes, 11/11/2026);
        # a uno de otro grupo, no.
        self.assertEqual(c.patch(url, {"activo": False}, format="json").status_code, 200)
        self.assertEqual(c.patch(url, {"activo": True}, format="json").status_code, 200)
        self.assertIn(c.patch(f"/api/entrenadores/{self.otro.id}/", {"activo": False},
                              format="json").status_code, (403, 404))
        self.otro.refresh_from_db()
        self.assertTrue(self.otro.activo)
        # Lo demás de los suyos, sí.
        self.assertEqual(c.patch(url, {"disponibilidad_notas": "Llega tarde"}, format="json").status_code, 200)
        # Dirección, todo.
        self.assertEqual(self.api(self.dir).patch(url, {"gestiona_todos_jugadores": True},
                                                  format="json").status_code, 200)

    def test_un_head_coach_no_da_de_alta_a_alguien_que_lo_ve_todo(self):
        r = self.api(self.pablo).post("/api/entrenadores/", {
            "nombre": "Nuevo", "gestiona_todos_jugadores": True}, format="json")
        creado = Entrenador.objects.filter(nombre="Nuevo").first()
        self.assertTrue(r.status_code == 403 or (creado is not None and not creado.gestiona_todos_jugadores),
                        f"{r.status_code}: un head coach crea un entrenador que ve a todos los jugadores")


class FichaDelJugadorTests(Base):
    def setUp(self):
        super().setUp()
        self.d4, _ = Division.objects.get_or_create(nivel=4)

    def test_la_division_solo_la_cambia_direccion(self):
        url = f"/api/jugadores/{self.ana.id}/"
        self.assertEqual(self.api(self.pablo).patch(url, {"division": self.d4.id},
                                                    format="json").status_code, 403)
        self.ana.refresh_from_db()
        self.assertIsNone(self.ana.division_id)
        r = self.api(self.dir).patch(url, {"division": self.d4.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.division, self.d4)
        # Y la tabla de divisiones, igual.
        url = f"/api/divisiones/{self.d4.id}/"
        self.assertEqual(self.api(self.pablo).patch(url, {"nombre": "Cuarta"}, format="json").status_code, 403)
        self.assertEqual(self.api(self.dir).patch(url, {"nombre": "Cuarta"}, format="json").status_code, 200)

    def test_el_grupo_se_cambia_desde_la_ficha_con_la_regla_de_grupos(self):
        """13/11/2026: la ficha vuelve a tener el grupo, con la misma regla y
        el mismo efecto que mover en Grupos (academy.grupos)."""
        url = f"/api/jugadores/{self.ana.id}/"
        ResponsableJugador.objects.create(jugador=self.ana, entrenador=self.blas, prioridad=1,
                                          porcentaje_objetivo=100)
        self.ana.cogestores.add(self.javi)
        # Head coach, dentro de su color: sí; quien compartía, fuera; porcentajes intactos.
        r = self.api(self.pablo).patch(url, {"entrenador_responsable": self.javi.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIs(r.json()["revisar_porcentajes"], True)
        self.ana.refresh_from_db()
        self.assertEqual((self.ana.entrenador_responsable, list(self.ana.cogestores.all())), (self.javi, []))
        self.assertEqual(list(ResponsableJugador.objects.filter(jugador=self.ana)
                              .values_list("entrenador_id", "porcentaje_objetivo")), [(self.blas.id, 100)])
        # A una columna de otro color, o un alumno de otro color: no.
        self.assertEqual(self.api(self.pablo).patch(url, {"entrenador_responsable": self.otro.id},
                                                    format="json").status_code, 403)
        self.assertIn(self.api(self.pablo).patch(f"/api/jugadores/{self.ajeno.id}/",
                                                 {"entrenador_responsable": self.blas.id},
                                                 format="json").status_code, (403, 404))
        # Sacarle del grupo, a «Sin grupo»: su head coach sí.
        r = self.api(self.pablo).patch(url, {"entrenador_responsable": None}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        # Uno sin grupo: el head coach le mete en el suyo; dirección, en cualquiera.
        self.assertEqual(self.api(self.pablo).patch(url, {"entrenador_responsable": self.blas.id},
                                                    format="json").status_code, 200)
        self.assertEqual(self.api(self.dir).patch(url, {"entrenador_responsable": self.otro.id},
                                                  format="json").status_code, 200)
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.entrenador_responsable, self.otro)
        # Compartir la gestión, solo en Grupos; el entrenador y Administración, nada.
        for u in (self.dir, self.pablo):
            r = self.api(u).patch(url, {"cogestores": [self.javi.id]}, format="json")
            self.assertEqual(r.status_code, 403, u.username)
            self.assertIn("Grupos", r.json()["detail"])
        adm = User.objects.create_user(username="adm", password="x", role=User.Role.ADMINISTRACION)
        for u in (self.u_blas, adm):
            self.assertIn(self.api(u).patch(url, {"entrenador_responsable": self.blas.id},
                                            format="json").status_code, (403, 404))
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.entrenador_responsable, self.otro)

    def test_el_grupo_al_dar_de_alta_solo_direccion(self):
        r = self.api(self.dir).post("/api/jugadores/", {"nombre": "Nuevo Grupo", "entrenador_responsable": self.blas.id},
                                    format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Jugador.objects.get(nombre="Nuevo Grupo").entrenador_responsable, self.blas)
        adm = User.objects.create_user(username="adm2", password="x", role=User.Role.ADMINISTRACION)
        r = self.api(adm).post("/api/jugadores/", {"nombre": "Otro Grupo", "entrenador_responsable": self.blas.id},
                               format="json")
        self.assertEqual(r.status_code, 403, r.content)
        self.assertEqual(self.api(adm).post("/api/jugadores/", {"nombre": "Sin Grupo"},
                                            format="json").status_code, 201)

    def test_mandar_el_mismo_responsable_no_es_cambiarlo(self):
        # El formulario de la ficha manda todos los campos: si el responsable
        # no cambia, se guarda lo demás.
        r = self.api(self.dir).patch(f"/api/jugadores/{self.ana.id}/", {
            "entrenador_responsable": self.blas.id, "cogestores": [], "vecindad": "SOLO"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.vecindad, "SOLO")


class AdministracionTests(Base):
    """Administración (decisión 10): altas y datos de todos los jugadores, sin
    tocar lo deportivo."""

    def setUp(self):
        super().setUp()
        self.adm = User.objects.create_user(username="adm", password="x", role=User.Role.ADMINISTRACION)

    def test_ve_y_cambia_los_datos_de_todos_los_jugadores(self):
        self.assertIs(self.me(self.adm)["ve_todos_los_jugadores"], True)
        c = self.api(self.adm)
        filas = c.get("/api/jugadores/").json()
        nombres = {f["nombre"] for f in filas.get("results", filas)}
        self.assertTrue({"Ana Orden", "Ajeno Orden"} <= nombres, "Administración no ve a los jugadores")
        r = c.patch(f"/api/jugadores/{self.ajeno.id}/", {"email": "familia@x.com"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_da_altas_pero_no_toca_lo_deportivo(self):
        c = self.api(self.adm)
        r = c.post("/api/jugadores/", {"nombre": "Alta Nueva"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.api(self.u_blas).post("/api/jugadores/", {"nombre": "Otra"},
                                                    format="json").status_code, 403)
        r = c.patch(f"/api/jugadores/{r.json()['id']}/", {"vecindad": "SOLO"}, format="json")
        self.assertIn(r.status_code, (403, 404), r.content)


class GruposTests(Base):
    def setUp(self):
        super().setUp()
        ResponsableJugador.objects.create(jugador=self.ana, entrenador=self.blas,
                                          prioridad=1, porcentaje_objetivo=70)
        ResponsableJugador.objects.create(jugador=self.ana, entrenador=self.javi,
                                          prioridad=2, porcentaje_objetivo=30)

    def porcentajes(self):
        return sorted(ResponsableJugador.objects.filter(jugador=self.ana).values_list(
            "entrenador_id", "prioridad", "porcentaje_objetivo", "activo"))

    def test_mover_cambia_quien_gestiona_y_no_toca_los_porcentajes(self):
        antes = self.porcentajes()
        r = self.api(self.dir).post("/api/grupos/mover/", {"jugador": self.ana.id, "entrenador": self.otro.id},
                                    format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIs(r.json()["revisar_porcentajes"], True)
        self.assertEqual(self.porcentajes(), antes)
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.entrenador_responsable, self.otro)
        # Si el nuevo gestor ya le entrena, no hay nada que revisar.
        r = self.api(self.dir).post("/api/grupos/mover/", {"jugador": self.ana.id, "entrenador": self.javi.id},
                                    format="json")
        self.assertIs(r.json()["revisar_porcentajes"], False)
        self.assertEqual(self.porcentajes(), antes)

    def test_quitar_no_toca_los_porcentajes(self):
        antes = self.porcentajes()
        r = self.api(self.pablo).post("/api/grupos/quitar/", {"jugador": self.ana.id, "entrenador": self.blas.id},
                                      format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.ana.refresh_from_db()
        self.assertIsNone(self.ana.entrenador_responsable)
        self.assertEqual(self.porcentajes(), antes)

    def test_compartir_anade_un_cogestor_dentro_de_su_color(self):
        antes = self.porcentajes()
        r = self.api(self.pablo).post("/api/grupos/compartir/", {"jugador": self.ana.id, "entrenador": self.javi.id},
                                      format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(list(self.ana.cogestores.all()), [self.javi])
        self.assertEqual(self.ana.entrenador_responsable, self.blas)
        self.assertEqual(self.porcentajes(), antes)
        # Fuera de su color, no; y un entrenador, nada.
        self.assertEqual(self.api(self.pablo).post("/api/grupos/compartir/", {
            "jugador": self.ana.id, "entrenador": self.otro.id}, format="json").status_code, 403)
        self.assertEqual(self.api(self.u_blas).post("/api/grupos/compartir/", {
            "jugador": self.ana.id, "entrenador": self.javi.id}, format="json").status_code, 403)


class ColumnasDeGruposTests(Base):
    """17/11/2026: Santi tiene su columna aunque no lleve a nadie, y Mario y
    Jorge, que llevan el mismo grupo, salen como una sola columna."""

    def setUp(self):
        super().setUp()
        # Blas es el principal; Javi comparte columna con él.
        self.javi.columna_con = self.blas
        self.javi.save()
        self.ana.cogestores.add(self.javi)
        self.bea = Jugador.objects.create(nombre="Bea Orden", entrenador_responsable=self.blas)
        self.bea.cogestores.add(self.javi)

    def columnas(self, user=None):
        r = self.api(user or self.dir).get("/api/grupos/")
        self.assertEqual(r.status_code, 200, r.content)
        bloque = next(b for b in r.json()["bloques"] if b["coach"] and b["coach"]["id"] == self.grupo.id)
        return bloque["grupos"]

    def test_el_head_coach_sale_en_su_bloque_aunque_no_lleve_a_nadie(self):
        santi = Entrenador.objects.create(nombre="Pablo Head", user=self.pablo)
        self.grupo.entrenadores.add(santi)
        col = next(g for g in self.columnas() if g["entrenador"]["id"] == santi.id)
        self.assertEqual(col["jugadores"], [])
        # Y puede recibir a alguien: el head coach mueve dentro de su color.
        r = self.api(self.pablo).post("/api/grupos/mover/", {"jugador": self.ana.id, "entrenador": santi.id},
                                      format="json")
        self.assertEqual(r.status_code, 200, r.content)
        col = next(g for g in self.columnas() if g["entrenador"]["id"] == santi.id)
        self.assertEqual([j["nombre"] for j in col["jugadores"]], ["Ana Orden"])

    def test_dos_entrenadores_que_comparten_columna_salen_como_una(self):
        cols = self.columnas()
        self.assertEqual([g["entrenador"]["nombre"] for g in cols], ["Blas / Javi"])
        col = cols[0]
        self.assertEqual(col["entrenador"]["id"], self.blas.id)
        self.assertEqual(col["entrenador"]["ids"], [self.blas.id, self.javi.id])
        # Cada alumno una sola vez, aunque lo vean los dos.
        self.assertEqual([j["nombre"] for j in col["jugadores"]], ["Ana Orden", "Bea Orden"])

    def test_el_nombre_empieza_por_el_principal_aunque_vaya_detras_en_el_abecedario(self):
        # Mario Muniesa (principal) / Jorge Ibáñez: Jorge sale antes por orden alfabético.
        Entrenador.objects.filter(pk=self.javi.pk).update(columna_con=None)
        Entrenador.objects.filter(pk=self.blas.pk).update(columna_con=self.javi)
        self.assertEqual([g["entrenador"]["nombre"] for g in self.columnas()], ["Javi / Blas"])

    def test_si_el_principal_esta_de_baja_el_otro_vuelve_a_tener_la_suya(self):
        self.blas.activo = False
        self.blas.save()
        self.assertEqual([g["entrenador"]["nombre"] for g in self.columnas()], ["Javi"])

    def test_meter_a_uno_en_la_columna_unida_lo_deja_con_los_dos(self):
        carlos = Jugador.objects.create(nombre="Carlos Orden")
        for entrenador in (self.blas, self.javi):  # da igual por cuál se entre
            carlos.entrenador_responsable = None
            carlos.save()
            carlos.cogestores.clear()
            r = self.api(self.pablo).post("/api/grupos/mover/", {
                "jugador": carlos.id, "entrenador": entrenador.id}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
            carlos.refresh_from_db()
            self.assertEqual(carlos.entrenador_responsable, self.blas)
            self.assertEqual(list(carlos.cogestores.all()), [self.javi])
        self.assertEqual([j["nombre"] for j in self.columnas()[0]["jugadores"]],
                         ["Ana Orden", "Bea Orden", "Carlos Orden"])

    def test_desde_la_ficha_tambien(self):
        carlos = Jugador.objects.create(nombre="Carlos Orden")
        r = self.api(self.pablo).patch(f"/api/jugadores/{carlos.id}/", {
            "entrenador_responsable": self.javi.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        carlos.refresh_from_db()
        self.assertEqual((carlos.entrenador_responsable, list(carlos.cogestores.all())),
                         (self.blas, [self.javi]))

    def test_no_hay_que_revisar_porcentajes_si_le_entrena_el_otro_de_la_columna(self):
        ResponsableJugador.objects.create(jugador=self.ajeno, entrenador=self.javi, prioridad=1,
                                          porcentaje_objetivo=100)
        r = self.api(self.dir).post("/api/grupos/mover/", {
            "jugador": self.ajeno.id, "entrenador": self.blas.id}, format="json")
        self.assertIs(r.json()["revisar_porcentajes"], False)

    def test_quitar_de_la_columna_unida_lo_quita_de_los_dos(self):
        r = self.api(self.pablo).post("/api/grupos/quitar/", {
            "jugador": self.ana.id, "entrenador": self.blas.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.ana.refresh_from_db()
        self.assertIsNone(self.ana.entrenador_responsable)
        self.assertEqual(list(self.ana.cogestores.all()), [])
        self.assertEqual([j["nombre"] for j in self.columnas()[0]["jugadores"]], ["Bea Orden"])

    def test_compartir_con_la_columna_unida_los_pone_a_los_dos(self):
        carlos = Jugador.objects.create(nombre="Carlos Orden", entrenador_responsable=self.otro)
        self.grupo.entrenadores.add(self.otro)
        r = self.api(self.pablo).post("/api/grupos/compartir/", {
            "jugador": carlos.id, "entrenador": self.javi.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual({e.pk for e in carlos.cogestores.all()}, {self.blas.pk, self.javi.pk})

    def test_mudar_la_columna_se_lleva_a_los_dos(self):
        otro_bloque = Coach.objects.create(nombre="Santi", color="naranja")
        r = self.api(self.dir).post("/api/grupos/mover_entrenador/", {
            "entrenador": self.blas.id, "coach": otro_bloque.id, "desde": self.grupo.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual({e.pk for e in otro_bloque.entrenadores.all()}, {self.blas.pk, self.javi.pk})
        self.assertEqual(list(self.grupo.entrenadores.all()), [])

    def test_no_se_puede_compartir_columna_consigo_ni_en_cadena(self):
        from django.core.exceptions import ValidationError

        self.blas.columna_con = self.blas
        with self.assertRaises(ValidationError):
            self.blas.full_clean(exclude=["user"])
        self.blas.columna_con = None
        # Javi ya depende de Blas: nadie puede colgar de Javi.
        self.otro.columna_con = self.javi
        with self.assertRaises(ValidationError):
            self.otro.full_clean(exclude=["user"])
        # Y Blas, con gente colgando de él, no puede colgar de otro.
        self.blas.columna_con = self.otro
        with self.assertRaises(ValidationError):
            self.blas.full_clean(exclude=["user"])

    def test_un_ciclo_hecho_a_mano_no_hace_desaparecer_a_nadie(self):
        Entrenador.objects.filter(pk=self.blas.pk).update(columna_con=self.javi)
        nombres = [g["entrenador"]["nombre"] for g in self.columnas()]
        self.assertCountEqual(nombres, ["Blas", "Javi"])


class GonzaloYaEsDeLaEscuelaTests(Base):
    """17/11/2026: un invitado que pasa a la escuela (academy.0062)."""

    def setUp(self):
        super().setUp()
        import importlib

        from django.apps import apps

        from academy.models import HorarioJugador, Invitado, VisitaInvitado

        self.apps = apps
        self.mig = importlib.import_module("academy.migrations.0062_gonzalo_chicote_ya_es_de_la_escuela")
        self.gonzalo = Jugador.objects.create(
            nombre="Gonzalo Chicote (invitado)", entrenador_responsable=self.blas,
            notas="Invitado de Blas: viene los jueves", fecha_alta=date(2026, 10, 20),
            fecha_baja=date(2026, 11, 12))
        HorarioJugador.objects.create(jugador=self.gonzalo, dia=0, entrena_manana=False, entrena_tarde=False)
        self.inv = Invitado.objects.create(
            nombre="Gonzalo Chicote", entrenador_solicitante=self.blas, estado=Invitado.Estado.APROBADO,
            jugador_creado=self.gonzalo)
        for dia in (date(2026, 10, 20), date(2026, 10, 29)):
            VisitaInvitado.objects.create(invitado=self.inv, fecha=dia, manana="M1",
                                          estado=VisitaInvitado.Estado.APROBADA)

    def test_pasa_a_ser_un_alumno_como_los_demas(self):
        from academy.models import HorarioJugador, Invitado, VisitaInvitado

        self.mig.pasar_a_la_escuela(self.apps, None)
        self.gonzalo.refresh_from_db()
        self.assertEqual(self.gonzalo.nombre, "Gonzalo Chicote")
        self.assertEqual(self.gonzalo.notas, "")
        self.assertIsNone(self.gonzalo.fecha_baja)
        # Lo demás, intacto: responsable, fecha de alta y su semana habitual.
        self.assertEqual(self.gonzalo.entrenador_responsable, self.blas)
        self.assertEqual(self.gonzalo.fecha_alta, date(2026, 10, 20))
        self.assertEqual(HorarioJugador.objects.filter(jugador=self.gonzalo).count(), 1)
        self.assertFalse(Invitado.objects.exists())
        self.assertFalse(VisitaInvitado.objects.exists())
        # Y sale en Jugadores aunque se pida sin invitados.
        r = self.api(self.dir).get("/api/jugadores/?sin_invitados=1")
        nombres = [j["nombre"] for j in (r.json()["results"] if isinstance(r.json(), dict) else r.json())]
        self.assertIn("Gonzalo Chicote", nombres)

    def test_se_deshace_tal_como_estaba(self):
        from academy.models import Invitado, VisitaInvitado

        self.mig.pasar_a_la_escuela(self.apps, None)
        self.mig.deshacer(self.apps, None)
        self.gonzalo.refresh_from_db()
        self.assertEqual(self.gonzalo.nombre, "Gonzalo Chicote (invitado)")
        self.assertEqual(self.gonzalo.notas, "Invitado de Blas: viene los jueves")
        self.assertEqual(self.gonzalo.fecha_baja, date(2026, 11, 12))
        inv = Invitado.objects.get(pk=self.inv.pk)
        self.assertEqual(inv.jugador_creado_id, self.gonzalo.pk)
        self.assertEqual(sorted(inv.visitas.values_list("fecha", flat=True)),
                         [date(2026, 10, 20), date(2026, 10, 29)])
        self.assertEqual(VisitaInvitado.objects.count(), 2)

    def test_sin_el_invitado_no_hace_nada(self):
        from academy.models import Invitado

        Invitado.objects.all().delete()
        self.mig.pasar_a_la_escuela(self.apps, None)
        self.gonzalo.refresh_from_db()
        self.assertEqual(self.gonzalo.nombre, "Gonzalo Chicote (invitado)")
        self.assertEqual(self.gonzalo.fecha_baja, date(2026, 11, 12))


class JorgeMicoFueraTests(Base):
    """17/11/2026: Jorge Mico es de pádel y no sale en la aplicación (academy.0063)."""

    def setUp(self):
        super().setUp()
        import importlib

        from django.apps import apps

        self.apps = apps
        self.mig = importlib.import_module("academy.migrations.0063_jorge_mico_fuera_de_la_aplicacion")
        self.u_mico = User.objects.create_user(username="jorge.mico", password="x", role=User.Role.ENTRENADOR)
        self.mico = Entrenador.objects.create(nombre="Jorge Mico", user=self.u_mico, solo_manual=True)
        self.grupo.entrenadores.add(self.mico)

    def columnas(self):
        r = self.api(self.dir).get("/api/grupos/")
        return [g["entrenador"]["nombre"] for b in r.json()["bloques"] for g in b["grupos"]]

    def test_deja_de_salir_y_no_entra(self):
        self.assertIn("Jorge Mico", self.columnas())
        self.mig.dar_de_baja(self.apps, None)
        self.mico.refresh_from_db()
        self.u_mico.refresh_from_db()
        self.assertFalse(self.mico.activo)
        self.assertFalse(self.u_mico.is_active)
        self.assertNotIn("Jorge Mico", self.columnas())
        # Nada se borra: sigue en su bloque y en la base.
        self.assertTrue(self.grupo.entrenadores.filter(pk=self.mico.pk).exists())
        # Y fuera de Personas y funciones.
        r = self.api(self.dir).get("/api/auth/personal/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertNotIn("jorge.mico", [p["username"] for p in r.json()["personas"]])

    def test_se_deshace_como_estaba(self):
        self.mig.dar_de_baja(self.apps, None)
        self.mig.deshacer(self.apps, None)
        self.mico.refresh_from_db()
        self.u_mico.refresh_from_db()
        self.assertTrue(self.mico.activo)
        self.assertTrue(self.u_mico.is_active)
        self.assertTrue(self.mico.solo_manual)

    def test_no_toca_a_otros_jorge_ni_hace_nada_si_no_esta(self):
        milla = Entrenador.objects.create(nombre="Jorge Milla")
        self.mico.delete()
        self.mig.dar_de_baja(self.apps, None)
        milla.refresh_from_db()
        self.assertTrue(milla.activo)
        self.u_mico.refresh_from_db()
        self.assertTrue(self.u_mico.is_active)


class ReglasDelJugadorTests(Base):
    def url(self, jugador=None):
        return f"/api/jugadores/{(jugador or self.ana).id}/reglas/"

    def test_las_leen_direccion_y_head_coach_y_el_entrenador_no(self):
        for u in (self.dir, self.pablo):
            r = self.api(u).get(self.url())
            self.assertEqual(r.status_code, 200, u.username)
            self.assertEqual(set(r.json()), {"rencillas", "contratos", "vetos", "parejas", "franjas", "superficie"})
        self.assertEqual(self.api(self.u_blas).get(self.url()).status_code, 403)
        self.assertEqual(self.api(self.u_blas).get("/api/rencillas/").status_code, 403)

    def test_el_head_coach_anade_una_rencilla(self):
        otro = Jugador.objects.create(nombre="Rencilloso", entrenador_responsable=self.javi)
        r = self.api(self.pablo).post(self.url(), {"tipo": "rencilla", "jugador": otro.id, "motivo": "Discuten"},
                                      format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([(x["nombre"], x["motivo"]) for x in r.json()["rencillas"]], [("Rencilloso", "Discuten")])
        self.assertTrue(Rencilla.objects.filter(jugador_a__in=[self.ana, otro], jugador_b__in=[self.ana, otro]).exists())
        # Una regla mal formada no rompe nada.
        r = self.api(self.pablo).post(self.url(), {"tipo": "rencilla", "jugador": self.ana.id}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_ni_el_entrenador_ni_otro_grupo_las_cambian(self):
        self.assertEqual(self.api(self.u_blas).post(self.url(), {
            "tipo": "rencilla", "jugador": self.ajeno.id}, format="json").status_code, 403)
        self.assertIn(self.api(self.pablo).post(self.url(self.ajeno), {
            "tipo": "rencilla", "jugador": self.ana.id}, format="json").status_code, (403, 404))
        self.assertFalse(Rencilla.objects.filter(jugador_a__in=[self.ana, self.ajeno],
                                                 jugador_b__in=[self.ana, self.ajeno]).exists())


class FaltasTests(Base):
    def setUp(self):
        super().setUp()
        from scheduling.models import Semana

        self.semana, _ = Semana.objects.get_or_create(fecha_inicio=date(2026, 12, 7))

    def test_el_parte_semanal_solo_guarda_viene_ademas(self):
        from scheduling.models import Disponibilidad

        base = {"semana": self.semana.id, "jugador": self.ana.id, "dia": 1, "ambito": "M1"}
        r = self.api(self.dir).post("/api/disponibilidades/", {**base, "estado": "AUSENCIA_JUGADOR"},
                                    format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("estado", r.json())
        self.assertFalse(Disponibilidad.objects.filter(jugador=self.ana).exists())
        r = self.api(self.dir).post("/api/disponibilidades/", {**base, "estado": "EXTRA"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        # Tampoco se convierte en falta editándolo.
        r = self.api(self.dir).patch(f"/api/disponibilidades/{r.json()['id']}/", {"estado": "EN_TORNEO"},
                                     format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_la_falta_guarda_quien_la_apunto(self):
        from scheduling.models import AusenciaJugador

        cuerpo = {"jugador": self.ana.id, "fecha_inicio": "2026-12-08", "fecha_fin": "2026-12-09",
                  "ambito": "DIA", "estado": "AUSENCIA_JUGADOR", "subtipo": "ESTUDIOS"}
        r = self.api(self.u_blas).post("/api/ausencias-fechas/", cuerpo, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        f = AusenciaJugador.objects.get(pk=r.json()["id"])
        self.assertEqual((f.creada_por, f.declarada_por), (self.u_blas, self.blas))
        self.assertEqual(r.json()["apuntada_por"], "blas")
        # Quien no es entrenador también queda apuntado.
        r = self.api(self.dir).post("/api/ausencias-fechas/", {**cuerpo, "fecha_inicio": "2026-12-10",
                                                               "fecha_fin": "2026-12-10"}, format="json")
        f = AusenciaJugador.objects.get(pk=r.json()["id"])
        self.assertEqual((f.creada_por, f.declarada_por), (self.dir, None))
        # Y no se puede falsear.
        r = self.api(self.u_blas).post("/api/ausencias-fechas/", {
            **cuerpo, "fecha_inicio": "2026-12-11", "fecha_fin": "2026-12-11", "creada_por": self.dir.id},
            format="json")
        self.assertEqual(AusenciaJugador.objects.get(pk=r.json()["id"]).creada_por, self.u_blas)

    def test_falta_por_descanso(self):
        # 23/11/2026: «Descanso» es un motivo más de falta.
        r = self.api(self.u_blas).post("/api/ausencias-fechas/", {
            "jugador": self.ana.id, "fecha_inicio": "2026-12-08", "fecha_fin": "2026-12-08",
            "ambito": "DIA", "estado": "AUSENCIA_JUGADOR", "subtipo": "DESCANSO"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["subtipo_display"], "Descanso")


class CalendarioDelEntrenadorTests(Base):
    """Un solo calendario del entrenador, con horas opcionales; el motor y el
    panel preguntan a `motivo_no_disponible`."""

    FECHA = date(2026, 11, 16)  # lunes, fuera del horario de verano

    def turno(self, codigo, desde, hasta, bloque=Turno.Bloque.MANANA):
        return Turno(codigo=codigo, nombre=codigo, bloque=bloque, hora_inicio=desde, hora_fin=hasta)

    def motivo(self, turno):
        from engine.service import motivo_no_disponible

        vacaciones = {}
        for v in VacacionesEntrenador.objects.filter(
                entrenador=self.javi, fecha_inicio__lte=self.FECHA, fecha_fin__gte=self.FECHA):
            vacaciones.setdefault(v.entrenador_id, []).append(v)
        return motivo_no_disponible(self.javi, 0, turno, self.FECHA, vacaciones, {}, {})

    def test_unas_horas_solo_le_quitan_las_franjas_que_pisan(self):
        r = self.api(self.dir).post("/api/vacaciones/", {
            "entrenador": self.javi.id, "fecha_inicio": "2026-11-16", "fecha_fin": "2026-11-16",
            "hora_desde": "08:00", "hora_hasta": "10:00", "motivo": "Médico"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        v = VacacionesEntrenador.objects.get(pk=r.json()["id"])
        self.assertEqual((v.hora_desde, v.hora_hasta, v.creada_por), (time(8), time(10), self.dir))

        self.assertEqual(self.motivo(self.turno("M1", time(8, 30), time(10))), "no está: médico")
        self.assertIsNone(self.motivo(self.turno("M2", time(10, 30), time(12, 30))))
        # Empieza justo cuando él vuelve: puede.
        self.assertIsNone(self.motivo(self.turno("X", time(10), time(11))))
        # Sin motivo apuntado.
        v.motivo = ""
        v.save()
        self.assertEqual(self.motivo(self.turno("M1", time(8, 30), time(10))), "no está")

    def test_sin_horas_el_dia_entero_y_otro_dia_nada(self):
        VacacionesEntrenador.objects.create(entrenador=self.javi, fecha_inicio=self.FECHA,
                                            fecha_fin=self.FECHA, motivo="Torneo · Valencia")
        self.assertEqual(self.motivo(self.turno("T1", time(14, 15), time(15, 30), Turno.Bloque.TARDE)),
                         "no está: torneo")
        VacacionesEntrenador.objects.all().update(fecha_inicio=date(2026, 11, 17), fecha_fin=date(2026, 11, 17))
        self.assertIsNone(self.motivo(self.turno("M1", time(8, 30), time(10))))

    def test_el_head_coach_solo_apunta_a_los_de_su_grupo(self):
        c = self.api(self.pablo)
        cuerpo = {"fecha_inicio": "2026-11-16", "fecha_fin": "2026-11-16", "motivo": "Torneo"}
        self.assertEqual(c.post("/api/vacaciones/", {**cuerpo, "entrenador": self.otro.id},
                                format="json").status_code, 403)
        r = c.post("/api/vacaciones/", {**cuerpo, "entrenador": self.javi.id}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        # Tampoco pasándole después la suya a uno de fuera.
        r = c.patch(f"/api/vacaciones/{r.json()['id']}/", {"entrenador": self.otro.id}, format="json")
        self.assertIn(r.status_code, (400, 403), r.content)
        self.assertFalse(VacacionesEntrenador.objects.filter(entrenador=self.otro).exists(),
                         "un head coach apunta ausencias a un entrenador de otro grupo editando una suya")
        # El entrenador, solo desde su agenda.
        self.assertEqual(self.api(self.u_blas).post("/api/vacaciones/", {**cuerpo, "entrenador": self.blas.id},
                                                    format="json").status_code, 403)

    def test_la_tarde_no_le_quita_la_manana(self):
        VacacionesEntrenador.objects.create(entrenador=self.javi, fecha_inicio=self.FECHA,
                                            fecha_fin=self.FECHA, ambito="TARDE")
        self.assertIsNone(self.motivo(self.turno("M1", time(8, 30), time(10))))
        self.assertEqual(self.motivo(self.turno("T1", time(14, 15), time(15, 30), Turno.Bloque.TARDE)), "no está")

    def test_hoy_unas_horas_no_le_marcan_fuera_el_dia_entero(self):
        """«Hoy» de su agenda (11/11/2026): una ausencia de 00:00 a 10:00 le
        quita la M1, no el día."""
        hoy = date.today()
        for codigo, ini, fin in (("M1", time(8, 30), time(10)), ("M2", time(10, 30), time(12, 30))):
            Turno.objects.update_or_create(codigo=codigo, defaults={
                "nombre": codigo, "bloque": Turno.Bloque.MANANA, "hora_inicio": ini, "hora_fin": fin})
        VacacionesEntrenador.objects.create(entrenador=self.blas, fecha_inicio=hoy, fecha_fin=hoy,
                                            hora_desde=time(0), hora_hasta=time(10), motivo="Médico")
        d = self.api(self.u_blas).get("/api/mi-agenda/dia/").json()
        self.assertIs(d["ausente"], False, d)
        self.assertIn("M1", d["franjas_fuera"])
        self.assertNotIn("M2", d["franjas_fuera"])
        # Sin horas, el día entero.
        VacacionesEntrenador.objects.all().update(hora_desde=None, hora_hasta=None)
        self.assertIs(self.api(self.u_blas).get("/api/mi-agenda/dia/").json()["ausente"], True)


class BajasDelHeadCoachTests(Base):
    """El head coach da de baja a los jugadores de su grupo, como antes
    (11/11/2026); a los de otro grupo, no. Dirección recibe el aviso."""

    def test_baja_de_un_jugador_de_su_grupo_y_no_de_otro(self):
        from academy.models import Aviso

        c = self.api(self.pablo)
        r = c.patch(f"/api/jugadores/{self.ana.id}/", {"activo": False}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(Aviso.objects.filter(para_direccion=True, titulo__contains="Ana Orden").exists())
        r = c.patch(f"/api/jugadores/{self.ajeno.id}/", {"activo": False}, format="json")
        self.assertIn(r.status_code, (403, 404), r.content)
        self.ajeno.refresh_from_db()
        self.assertTrue(self.ajeno.activo)
        # El entrenador, no.
        self.ana.activo = True
        self.ana.save()
        self.assertIn(self.api(self.u_blas).patch(f"/api/jugadores/{self.ana.id}/", {"activo": False},
                                                  format="json").status_code, (403, 404))


class CuadranteTests(Base):
    def setUp(self):
        super().setUp()
        from scheduling.models import Asignacion, Semana

        Sede.objects.update(activa=False)
        self.sede = Sede.objects.create(nombre="Orden", densidad_default=2, densidad_max=2, activa=True)
        self.p1, self.p2 = [Pista.objects.create(sede=self.sede, numero=n, superficie="TIERRA") for n in (1, 2)]
        self.m1, _ = Turno.objects.get_or_create(
            codigo="M1", defaults={"nombre": "M1", "bloque": Turno.Bloque.MANANA,
                                   "hora_inicio": time(8, 30), "hora_fin": time(10, 0), "orden": 1})
        self.semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)
        self.asig = Asignacion.objects.create(semana=self.semana, dia=0, turno=self.m1, pista=self.p1,
                                              jugador=self.ana, entrenador=self.blas, manual=True)

    def test_sin_la_funcion_un_head_coach_mira_pero_no_toca(self):
        c = self.api(self.pablo)
        url = f"/api/semanas/{self.semana.id}/"
        self.assertEqual(c.get(url + "cuadrante/?dia=0").status_code, 200)
        for accion in ("generar/", "deshacer/", "publicar/"):
            self.assertEqual(c.post(url + accion, {"solo_dia": 0}, format="json").status_code, 403, accion)
        r = c.post("/api/asignaciones/mover/", {"asignacion": self.asig.id, "pista": self.p2.id}, format="json")
        self.assertEqual(r.status_code, 403)
        self.asig.refresh_from_db()
        self.assertEqual(self.asig.pista, self.p1)

    def test_con_la_funcion_pasa(self):
        Funcion.objects.create(usuario=self.pablo, codigo="TOCA_CUADRANTE")
        c = self.api(self.pablo)
        # Hay un cambio a mano ese día: pregunta qué hacer con él (409), señal
        # de que el permiso ya ha pasado sin tener que lanzar el motor.
        r = c.post(f"/api/semanas/{self.semana.id}/generar/", {"solo_dia": 0}, format="json")
        self.assertEqual(r.status_code, 409, r.content)
        self.assertTrue(r.json()["pregunta_manual"])
        r = c.post("/api/asignaciones/mover/", {"asignacion": self.asig.id, "pista": self.p2.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_un_mover_que_falla_no_deja_paso_en_el_historial(self):
        from scheduling.models import Asignacion, CambioSemana

        for nombre in ("Llena 1", "Llena 2"):
            Asignacion.objects.create(semana=self.semana, dia=0, turno=self.m1, pista=self.p2,
                                      jugador=Jugador.objects.create(nombre=nombre))
        c = self.api(self.dir)
        r = c.post("/api/asignaciones/mover/", {"asignacion": self.asig.id, "pista": self.p2.id}, format="json")
        self.assertEqual(r.status_code, 409, r.content)
        # El miércoles por la tarde no se entrena.
        t1, _ = Turno.objects.get_or_create(
            codigo="T1", defaults={"nombre": "T1", "bloque": Turno.Bloque.TARDE,
                                   "hora_inicio": time(14, 15), "hora_fin": time(15, 30), "orden": 4})
        r = c.post("/api/asignaciones/mover/", {"asignacion": self.asig.id, "pista": self.p1.id,
                                                "dia": 2, "turno": t1.id}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertFalse(CambioSemana.objects.filter(semana=self.semana).exists())
        self.assertEqual(c.post(f"/api/semanas/{self.semana.id}/deshacer/").status_code, 409)

    def test_un_mover_a_una_pista_que_no_existe_no_rompe_ni_deja_paso(self):
        from scheduling.models import CambioSemana

        c = self.api(self.dir)
        c.raise_request_exception = False
        r = c.post("/api/asignaciones/mover/", {"asignacion": self.asig.id, "pista": 999999}, format="json")
        self.assertIn(r.status_code, (400, 404), "mover a una pista inexistente devuelve "
                                                 f"{r.status_code} en vez de un error de petición")
        self.assertFalse(CambioSemana.objects.filter(semana=self.semana).exists(),
                         "el mover fallido deja una foto en el historial")
        self.asig.refresh_from_db()
        self.assertEqual(self.asig.pista, self.p1)


@override_settings(ANTHROPIC_API_KEY="", GOOGLE_SERVICE_ACCOUNT_JSON="", DRIVE_INFORMES_ID="", DRIVE_CT_USUARIO="")
class InformesTests(Base):
    def setUp(self):
        super().setUp()
        from academy.models import Escuela
        from evaluaciones.models import Evaluacion, EvaluacionFisica, Informe, MiembroTardes

        # Como en evaluaciones.tests: el cliente de pruebas no captura las
        # plantillas de los PDF.
        plantillas = mock.patch("django.test.client.store_rendered_templates", lambda *a, **k: None)
        plantillas.start()
        self.addCleanup(plantillas.stop)
        ct = Escuela.objects.create(nombre="Competición de tardes", solo_informes=True)
        self.nino = Jugador.objects.create(nombre="Nino Tardes", escuela=ct, activo=False)
        self.salva = User.objects.create_user(username="salva", password="x", role=User.Role.ENTRENADOR)
        self.josep = User.objects.create_user(username="josep", password="x", role=User.Role.PREPARADOR)
        MiembroTardes.objects.create(usuario=self.salva, funcion="TENIS")
        MiembroTardes.objects.create(usuario=self.josep, funcion="FISICO")
        self.validador = User.objects.create_user(username="valida", password="x", role=User.Role.ENTRENADOR)
        Funcion.objects.create(usuario=self.validador, codigo="VALIDA_INFORMES")
        self.tenis = Evaluacion.objects.create(jugador=self.nino, evaluador=self.salva, nombre_evaluador="Salva",
                                               estado="TERMINADA")
        self.fisica = EvaluacionFisica.objects.create(jugador=self.nino, evaluador=self.josep,
                                                      nombre_evaluador="Josep", estado="TERMINADA")
        self.inf = Informe.objects.create(jugador=self.nino, tenis=self.tenis, fisica=self.fisica,
                                          estado="VALIDADO")

    def test_reabrir_un_informe_aprobado_permite_volver_a_corregirlo(self):
        t = f"/api/evaluaciones/{self.tenis.id}/"
        f = f"/api/evaluaciones-fisicas/{self.fisica.id}/"
        # Aprobado: nadie lo toca, ni siquiera dirección o quien valida.
        for u in (self.salva, self.validador, self.dir):
            self.assertEqual(self.api(u).patch(t, {"idioma": "EN"}, format="json").status_code, 403, u.username)
        self.assertEqual(self.api(self.josep).patch(f, {"textos": {"notas_fisio": "x"}},
                                                    format="json").status_code, 403)
        self.assertEqual(self.api(self.salva).delete(t).status_code, 403)
        # Reabre quien valida (no el autor).
        self.assertEqual(self.api(self.salva).post(f"/api/informes/{self.inf.id}/reabrir/").status_code, 403)
        r = self.api(self.validador).post(f"/api/informes/{self.inf.id}/reabrir/")
        self.assertEqual(r.status_code, 200, r.content)
        self.inf.refresh_from_db()
        self.assertEqual((self.inf.estado, self.inf.version, self.inf.validado_por), ("EN_CURSO", 2, None))
        # Y ya se corrige.
        self.assertEqual(self.api(self.salva).patch(t, {"idioma": "EN"}, format="json").status_code, 200)
        self.assertEqual(self.api(self.josep).patch(f, {"textos": {"notas_fisio": "x"}},
                                                    format="json").status_code, 200)
        # Reabrir lo que no está aprobado no tiene sentido.
        self.assertEqual(self.api(self.validador).post(f"/api/informes/{self.inf.id}/reabrir/").status_code, 400)

    def test_quien_envia(self):
        url = f"/api/informes/{self.inf.id}/enviar/"
        for u in (self.salva, self.validador):
            self.assertEqual(self.api(u).post(url).status_code, 403, u.username)
        # El head coach envía solo los de Alto rendimiento de su color
        # (25/11/2026); este de tardes ni lo ve.
        self.assertEqual(self.api(self.pablo).post(url).status_code, 404)
        adm = User.objects.create_user(username="adm", password="x", role=User.Role.ADMINISTRACION)
        envia = User.objects.create_user(username="envia", password="x", role=User.Role.ENTRENADOR)
        Funcion.objects.create(usuario=envia, codigo="ENVIA_INFORMES")
        for u in (adm, envia, self.dir):
            # Pasa el permiso; falla porque no tiene a quién enviarse.
            r = self.api(u).post(url)
            self.assertEqual(r.status_code, 400, (u.username, r.content))

    def test_alto_rendimiento_pasa_por_la_validacion(self):
        from academy.models import Aviso
        from evaluaciones import catalogo
        from evaluaciones.models import Informe

        ar = Jugador.objects.create(nombre="Alto Rendimiento Uno", entrenador_responsable=self.blas)
        c = self.api(self.u_blas)
        r = c.post("/api/evaluaciones/", {"jugador": ar.id}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        ev_id = r.json()["id"]
        inf = Informe.objects.get(jugador=ar)
        self.assertEqual((inf.circuito, inf.tenis_id, inf.estado), ("alto_rendimiento", ev_id, "EN_CURSO"))
        c.patch(f"/api/evaluaciones/{ev_id}/", {
            "puntuaciones": {k: 3 for k in catalogo.CRITERIOS},
            "fortalezas_original": ["Saque"], "mejoras_original": ["Revés"]}, format="json")
        r = c.post(f"/api/evaluaciones/{ev_id}/terminar/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        inf.refresh_from_db()
        # Solo tenis: ya está completo y pendiente de validar.
        self.assertTrue(inf.completo)
        self.assertEqual(inf.estado, "PENDIENTE")
        # Los de Alto rendimiento los validan dirección y el head coach de su
        # color (12/11/2026), no quien valida los de tardes.
        listo = Aviso.objects.filter(titulo__contains="listo para validar")
        self.assertEqual(set(listo.values_list("usuario__username", flat=True)), {"dir", "pablo"})
        v = self.api(self.validador)
        self.assertEqual(v.get(f"/api/evaluaciones/{ev_id}/").status_code, 404)
        self.assertEqual(v.post(f"/api/informes/{inf.id}/aprobar/", {}, format="json").status_code, 404)
        self.assertEqual(v.get("/api/informes/", {"estado": "PENDIENTE"}).json(), [])
        # Dirección lo abre, lo corrige y lo aprueba.
        d = self.api(self.dir)
        r = d.get(f"/api/informes/{inf.id}/")
        self.assertIs(r.json()["puede_validar"], True)
        self.assertEqual(d.patch(f"/api/evaluaciones/{ev_id}/", {"idioma": "EN"}, format="json").status_code, 200)
        r = d.post(f"/api/informes/{inf.id}/aprobar/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(c.patch(f"/api/evaluaciones/{ev_id}/", {"idioma": "ES"}, format="json").status_code, 403)


    def test_el_equipo_de_tenis_sigue_la_evaluacion_de_otro_pero_no_la_borra(self):
        """«Todos evalúan a todos» en tardes (11/11/2026): otro del equipo de
        tenis continúa o corrige la parte de Salva mientras el informe no esté
        aprobado (p. ej. si le reasignan al jugador); borrarla, no."""
        jorge = User.objects.create_user(username="jorge", password="x", role=User.Role.ENTRENADOR)
        from evaluaciones.models import MiembroTardes

        MiembroTardes.objects.create(usuario=jorge, funcion="TENIS")
        self.inf.estado = "EN_CURSO"
        self.inf.save()
        self.tenis.estado = "BORRADOR"
        self.tenis.save()
        c = self.api(jorge)
        url = f"/api/evaluaciones/{self.tenis.id}/"
        r = c.patch(url, {"fortalezas": ["Sigue Jorge"]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIs(r.json()["puede_borrar"], False)
        self.assertEqual(c.delete(url).status_code, 403)
        # Aprobado, ya no.
        self.inf.estado = "VALIDADO"
        self.inf.save()
        self.assertEqual(c.patch(url, {"fortalezas": ["Otra"]}, format="json").status_code, 403)


class TorneosTests(Base):
    """Sin estado «Propuesto»; borrar o fundir un torneo con jugadores de otro
    grupo es solo de dirección (decisión 9)."""

    def setUp(self):
        super().setUp()
        from torneos.models import Participante, Torneo

        self.Torneo = Torneo
        self.suyo = Torneo.objects.create(nombre="Solo los suyos", fecha_inicio="2026-12-01", fecha_fin="2026-12-06")
        Participante.objects.create(torneo=self.suyo, jugador=self.ana, nombre=self.ana.nombre)
        self.mixto = Torneo.objects.create(nombre="Con uno de fuera", fecha_inicio="2026-12-01",
                                           fecha_fin="2026-12-06")
        Participante.objects.create(torneo=self.mixto, jugador=self.ajeno, nombre=self.ajeno.nombre)

    def test_sin_propuesto(self):
        self.assertNotIn("PROPUESTO", self.Torneo.Estado.values)
        r = self.api(self.dir).post("/api/torneos/", {"nombre": "X", "fecha_inicio": "2026-12-01",
                                                      "fecha_fin": "2026-12-02", "estado": "PROPUESTO"},
                                    format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_con_jugadores_de_otro_grupo_solo_borra_o_funde_direccion(self):
        c = self.api(self.pablo)
        self.assertEqual(c.delete(f"/api/torneos/{self.mixto.id}/").status_code, 403)
        self.assertEqual(c.post(f"/api/torneos/{self.suyo.id}/fusionar/", {"con": self.mixto.id},
                                format="json").status_code, 403)
        self.assertTrue(self.Torneo.objects.filter(pk=self.mixto.id).exists())
        # El que solo tiene a los suyos, sí.
        self.assertEqual(c.delete(f"/api/torneos/{self.suyo.id}/").status_code, 204)
        # Dirección, siempre.
        self.assertEqual(self.api(self.dir).delete(f"/api/torneos/{self.mixto.id}/").status_code, 204)


class GruposSoloColorTests(Base):
    """19/11/2026: en Grupos solo salen los grupos de color; sin invitados ni
    bajas; los entrenadores sin grupo, en una línea para dirección."""

    def grupos(self, user=None):
        r = self.api(user or self.dir).get("/api/grupos/")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_sin_bloques_grises(self):
        Coach.objects.create(nombre="ALVARO MANTOAN").entrenadores.add(self.otro)
        datos = self.grupos()
        self.assertTrue(all(b["coach"] and b["coach"]["color"] for b in datos["bloques"]))
        columnas = [g["entrenador"]["nombre"] for b in datos["bloques"] for g in b["grupos"]]
        self.assertNotIn("Otro", columnas)
        self.assertIn("Otro", [e["nombre"] for e in datos["sin_grupo_entrenadores"]])
        # Esa línea es solo para dirección.
        self.assertEqual(self.grupos(self.pablo)["sin_grupo_entrenadores"], [])

    def test_quien_no_sale_en_ninguna_columna_va_a_sin_grupo(self):
        self.assertIn("Ajeno Orden", [j["nombre"] for j in self.grupos()["sin_grupo"]])

    def test_invitados_y_bajas_fuera_y_altas_futuras_con_su_fecha(self):
        from datetime import timedelta

        from academy.models import Invitado

        hoy = date.today()
        inv = Jugador.objects.create(nombre="Elina (invitado)", fecha_alta=hoy - timedelta(days=20),
                                     fecha_baja=hoy - timedelta(days=20))
        Invitado.objects.create(nombre="Elina", entrenador_solicitante=self.javi,
                                estado="APROBADO", jugador_creado=inv)
        Jugador.objects.create(nombre="Invitada de hoy", entrenador_responsable=self.blas)
        Invitado.objects.create(nombre="Invitada de hoy", entrenador_solicitante=self.javi,
                                estado="APROBADO",
                                jugador_creado=Jugador.objects.get(nombre="Invitada de hoy"))
        Jugador.objects.create(nombre="Ya se fue", fecha_baja=hoy - timedelta(days=1))
        Jugador.objects.create(nombre="Llega pronto", fecha_alta=hoy + timedelta(days=3), edad=16)
        datos = self.grupos()
        sin = {j["nombre"]: j for j in datos["sin_grupo"]}
        en_columnas = {j["nombre"] for b in datos["bloques"] for g in b["grupos"]
                       for j in g["jugadores"]}
        for nombre in ("Elina (invitado)", "Invitada de hoy", "Ya se fue"):
            self.assertNotIn(nombre, sin)
            self.assertNotIn(nombre, en_columnas)
        self.assertEqual(sin["Llega pronto"]["fecha_alta"], (hoy + timedelta(days=3)).isoformat())
        self.assertEqual(sin["Llega pronto"]["edad"], 16)

    def test_dar_grupo_desde_la_linea_no_le_saca_del_bloque_de_todos(self):
        todos = Coach.objects.create(nombre="Sergio")
        todos.entrenadores.add(self.otro)
        r = self.api(self.dir).post("/api/grupos/mover_entrenador/", {
            "entrenador": self.otro.id, "coach": self.grupo.id, "desde": 0,
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(set(self.otro.coaches.all()), {self.grupo, todos})
        self.assertIn("Otro", [g["entrenador"]["nombre"] for b in self.grupos()["bloques"]
                               for g in b["grupos"]])


class EntrenadoresYGonzaloTests(Base):
    """19/11/2026 (academy.0065): Alberto fuera del cuadrante con su usuario
    activo, Jorge Milla y Salva solo los sábados, el Gonzalo duplicado inactivo
    y Marc Giner dado de alta sin contraseña."""

    def setUp(self):
        super().setUp()
        import importlib

        from django.apps import apps

        self.apps = apps
        self.mig = importlib.import_module("academy.migrations.0065_entrenadores_y_gonzalo")
        # La base de pruebas ya pasó por 0065 (y trae entrenadores sembrados):
        # se parte de cero.
        from users.models import ArchivoMigracion

        ArchivoMigracion.objects.filter(migracion=self.mig.NOMBRE).delete()
        User.objects.filter(username="marc.giner").delete()
        Entrenador.objects.filter(nombre="Marc Giner").delete()
        Entrenador.objects.update(activo=False)
        Entrenador.objects.filter(pk__in=[self.blas.pk, self.javi.pk, self.otro.pk]).update(activo=True)
        self.u_alberto = User.objects.create_user(username="alberto.sanz", password="x",
                                                  role=User.Role.ENTRENADOR)
        self.alberto = Entrenador.objects.create(nombre="Alberto Sanz", user=self.u_alberto,
                                                 solo_manual=True)
        self.milla = Entrenador.objects.create(nombre="Jorge Milla", solo_manual=True)
        self.salva = Entrenador.objects.create(nombre="Salva Barcala", solo_manual=True)
        from academy.models import HorarioEntrenador

        self.HorarioEntrenador = HorarioEntrenador
        # Salva tenía ya una fila (los lunes solo mañana): se cambia y vuelve.
        HorarioEntrenador.objects.create(entrenador=self.salva, dia=0, manana=True, tarde=False)
        self.gonzalo = Jugador.objects.create(nombre="Gonzalo Chicote")
        self.revert = Jugador.objects.create(nombre="Gonzalo Chicote Revert", codigo_cliente=8800)

    def jornada(self, ent):
        return {h.dia: (h.manana, h.tarde) for h in self.HorarioEntrenador.objects.filter(entrenador=ent)}

    def test_aplica(self):
        self.mig.aplicar(self.apps, None)
        for o in (self.alberto, self.u_alberto, self.milla, self.salva, self.gonzalo, self.revert):
            o.refresh_from_db()
        self.assertFalse(self.alberto.activo)
        self.assertTrue(self.u_alberto.is_active)  # sigue con Competición de tardes
        self.assertTrue(self.milla.activo and self.salva.activo)
        solo_sabado = {d: (d == 5, False) for d in range(6)}
        self.assertEqual(self.jornada(self.milla), solo_sabado)
        self.assertEqual(self.jornada(self.salva), solo_sabado)
        self.assertFalse(self.gonzalo.activo)
        self.assertTrue(self.revert.activo)
        marc = User.objects.get(username="marc.giner")
        self.assertEqual(marc.role, User.Role.ENTRENADOR)
        self.assertFalse(marc.has_usable_password())
        self.assertEqual(marc.get_full_name(), "Marc Giner")
        ficha = Entrenador.objects.get(user=marc)
        self.assertEqual(ficha.nombre, "Marc Giner")
        self.assertTrue(ficha.activo and ficha.solo_manual)
        self.assertFalse(ficha.coaches.exists())

    def test_se_deshace_como_estaba(self):
        self.mig.aplicar(self.apps, None)
        self.mig.deshacer(self.apps, None)
        for o in (self.alberto, self.gonzalo):
            o.refresh_from_db()
        self.assertTrue(self.alberto.activo)
        self.assertTrue(self.gonzalo.activo)
        self.assertEqual(self.jornada(self.milla), {})
        self.assertEqual(self.jornada(self.salva), {0: (True, False)})
        self.assertFalse(User.objects.filter(username="marc.giner").exists())
        self.assertFalse(Entrenador.objects.filter(nombre="Marc Giner").exists())

    def test_sin_el_gonzalo_bueno_no_toca_al_otro_y_no_duplica_a_marc(self):
        self.revert.delete()
        User.objects.create_user(username="marc.giner", password="x", role=User.Role.ENTRENADOR)
        self.mig.aplicar(self.apps, None)
        self.gonzalo.refresh_from_db()
        self.assertTrue(self.gonzalo.activo)
        self.assertEqual(User.objects.filter(username="marc.giner").count(), 1)
        self.assertFalse(Entrenador.objects.filter(nombre="Marc Giner").exists())
