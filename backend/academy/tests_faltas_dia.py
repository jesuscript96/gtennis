"""Faltas del día por grupos (25/11/2026): `GET /api/grupos/faltas/?fecha=`.

Dirección ve todos los grupos y a quien no está en ninguno; el head coach de
un color, todas las columnas de su color; el entrenador, solo la suya.
"""
from datetime import date, datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from academy.models import Coach, Entrenador, Jugador, VacacionesEntrenador
from scheduling.models import AusenciaJugador
from users.models import User

MIE = date(2026, 11, 25)


class FaltasDelDiaTests(TestCase):
    def setUp(self):
        self.u_dir = User.objects.create_user(username="dir", password="x", role=User.Role.SUPERADMIN)
        self.u_dani = User.objects.create_user(username="dani", password="x", role=User.Role.COACH)
        self.u_blas = User.objects.create_user(username="blas", password="x", role=User.Role.ENTRENADOR)
        self.u_admin = User.objects.create_user(
            username="mireia", password="x", role=User.Role.ADMINISTRACION)
        self.dani = Entrenador.objects.create(nombre="Dani", user=self.u_dani)
        self.blas = Entrenador.objects.create(nombre="Blas", user=self.u_blas)
        self.javi = Entrenador.objects.create(nombre="Javi")
        self.nacho = Entrenador.objects.create(nombre="Nacho")
        amarillo = Coach.objects.create(nombre="Dani", color="amarillo", user=self.u_dani)
        amarillo.entrenadores.set([self.dani, self.blas, self.javi])
        naranja = Coach.objects.create(nombre="Santi", color="naranja")
        naranja.entrenadores.set([self.nacho])

        self.de_blas = Jugador.objects.create(nombre="FD De Blas", entrenador_responsable=self.blas)
        self.de_javi = Jugador.objects.create(nombre="FD De Javi", entrenador_responsable=self.javi)
        self.compartido = Jugador.objects.create(nombre="FD Compartido", entrenador_responsable=self.javi)
        self.compartido.cogestores.set([self.blas])
        self.de_nacho = Jugador.objects.create(nombre="FD De Nacho", entrenador_responsable=self.nacho)
        self.sin_grupo = Jugador.objects.create(nombre="FD Sin grupo")
        Jugador.objects.create(nombre="FD Viene", entrenador_responsable=self.blas)

        def falta(j, ini, fin=None, **kw):
            return AusenciaJugador.objects.create(jugador=j, fecha_inicio=ini, fecha_fin=fin or ini, **kw)

        falta(self.de_blas, MIE, subtipo="ENFERMEDAD")
        falta(self.de_blas, MIE + timedelta(days=1), subtipo="DESCANSO")  # otro día
        falta(self.de_javi, MIE - timedelta(days=1), MIE + timedelta(days=2), estado="EN_TORNEO")
        falta(self.compartido, MIE, ambito="M1", hora_desde=time(8, 30), hora_hasta=time(10, 0))
        falta(self.de_nacho, MIE, subtipo="LESION")
        falta(self.sin_grupo, MIE)
        VacacionesEntrenador.objects.create(entrenador=self.javi, fecha_inicio=MIE,
                                            fecha_fin=MIE, motivo="Torneo")
        self.api = APIClient()

    def _get(self, user, fecha=MIE):
        self.api.force_authenticate(user)
        return self.api.get("/api/grupos/faltas/", {"fecha": fecha.isoformat()} if fecha else {})

    def _faltan(self, datos):
        """{columna: {jugador: [motivos]}} de las columnas de los bloques."""
        return {
            g["entrenador"]["nombre"]: {f["jugador"]["nombre"]: [x["motivo"] for x in f["faltas"]]
                                        for f in g["faltan"]}
            for b in datos["bloques"] for g in b["grupos"]
        }

    def test_direccion_ve_todos_los_grupos_y_a_quien_no_esta_en_ninguno(self):
        r = self._get(self.u_dir)
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["alcance"], "club")
        self.assertEqual(d["fecha"], "2026-11-25")
        cols = self._faltan(d)
        self.assertEqual(cols["Blas"], {"FD De Blas": ["Baja por enfermedad"], "FD Compartido": ["Falta"]})
        self.assertEqual(cols["Javi"], {"FD De Javi": ["Torneo"], "FD Compartido": ["Falta"]})
        self.assertEqual(cols["Nacho"], {"FD De Nacho": ["Lesión"]})
        self.assertEqual(cols["Dani"], {})
        self.assertIn("FD Sin grupo", {f["jugador"]["nombre"] for f in d["sin_grupo"]})

    def test_el_head_coach_ve_todas_las_columnas_de_su_color(self):
        d = self._get(self.u_dani).json()
        self.assertEqual(d["alcance"], "color")
        self.assertEqual([b["coach"]["color"] for b in d["bloques"]], ["amarillo"])
        cols = self._faltan(d)
        self.assertEqual(set(cols), {"Blas", "Dani", "Javi"})
        nombres = {j for c in cols.values() for j in c}
        self.assertEqual(nombres, {"FD De Blas", "FD De Javi", "FD Compartido"})
        self.assertEqual(d["sin_grupo"], [])
        # Cada alumno cuenta una vez aunque salga en dos columnas.
        self.assertEqual(d["total_faltan"], 3)

    def test_el_entrenador_ve_solo_su_columna(self):
        d = self._get(self.u_blas).json()
        self.assertEqual(d["alcance"], "grupo")
        self.assertEqual(self._faltan(d), {
            "Blas": {"FD De Blas": ["Baja por enfermedad"], "FD Compartido": ["Falta"]}})
        col = d["bloques"][0]["grupos"][0]
        self.assertEqual(col["alumnos"], 3)  # De Blas, Compartido y Viene
        self.assertEqual(d["total_alumnos"], 3)
        self.assertEqual(d["sin_grupo"], [])

    def test_la_columna_compartida_es_la_del_entrenador_que_la_comparte(self):
        # Jorge Ibáñez lleva el grupo con Mario Muniesa: ve la columna de los dos.
        self.nacho.columna_con = self.blas
        self.nacho.save()
        u_nacho = User.objects.create_user(username="nacho", password="x")
        self.nacho.user = u_nacho
        self.nacho.save()
        cols = self._faltan(self._get(u_nacho).json())
        self.assertEqual(list(cols), ["Blas / Nacho"])
        self.assertIn("FD De Nacho", cols["Blas / Nacho"])

    def test_solo_las_faltas_de_ese_dia(self):
        cols = self._faltan(self._get(self.u_blas, MIE + timedelta(days=1)).json())
        self.assertEqual(cols, {"Blas": {"FD De Blas": ["Descanso"]}})

    def test_la_falta_por_horas_lleva_su_franja(self):
        d = self._get(self.u_blas).json()
        f = next(x for g in d["bloques"][0]["grupos"] for x in g["faltan"]
                 if x["jugador"]["nombre"] == "FD Compartido")["faltas"][0]
        self.assertEqual((f["ambito"], f["hora_desde"], f["hora_hasta"]), ("M1", "08:30", "10:00"))

    def test_sale_el_entrenador_que_no_esta(self):
        d = self._get(self.u_dani).json()
        javi = next(g for b in d["bloques"] for g in b["grupos"] if g["entrenador"]["nombre"] == "Javi")
        self.assertEqual([v["motivo"] for v in javi["entrenador_fuera"]], ["Torneo"])
        blas = next(g for b in d["bloques"] for g in b["grupos"] if g["entrenador"]["nombre"] == "Blas")
        self.assertEqual(blas["entrenador_fuera"], [])

    def test_tras_el_corte_de_ese_dia(self):
        a_tiempo = AusenciaJugador.objects.get(jugador=self.de_blas, fecha_inicio=MIE)
        tarde = AusenciaJugador.objects.get(jugador=self.de_javi)
        martes = MIE - timedelta(days=1)
        AusenciaJugador.objects.filter(pk=a_tiempo.pk).update(
            created_at=timezone.make_aware(datetime.combine(martes, time(18, 0))))
        AusenciaJugador.objects.filter(pk=tarde.pk).update(
            created_at=timezone.make_aware(datetime.combine(martes, time(20, 0))))
        d = self._get(self.u_dani).json()
        corte = {f["jugador"]["nombre"]: f["faltas"][0]["tras_corte"]
                 for b in d["bloques"] for g in b["grupos"] for f in g["faltan"]}
        self.assertFalse(corte["FD De Blas"])
        # El torneo empezó el martes, pero para el miércoles llegó tarde.
        self.assertTrue(corte["FD De Javi"])

    def test_sin_fecha_es_hoy_y_una_fecha_mala_da_400(self):
        r = self._get(self.u_blas, fecha=None)
        self.assertEqual(r.json()["fecha"], timezone.localdate().isoformat())
        self.api.force_authenticate(self.u_blas)
        self.assertEqual(self.api.get("/api/grupos/faltas/", {"fecha": "25/11"}).status_code, 400)

    def test_quien_no_lleva_grupos_no_entra(self):
        self.assertEqual(self._get(self.u_admin).status_code, 403)

    def test_quien_ya_se_ha_ido_no_cuenta(self):
        self.de_blas.fecha_baja = MIE - timedelta(days=1)
        self.de_blas.save()
        d = self._get(self.u_blas).json()
        self.assertNotIn("FD De Blas", self._faltan(d)["Blas"])
