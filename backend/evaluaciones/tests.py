"""Evaluaciones: quién evalúa a quién, el guardado por bloques, la IA (simulada)
y el fichero `clave=valor`. No se llama nunca a la API de Claude de verdad."""
from datetime import date
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from academy.models import Entrenador, Jugador, ResponsableJugador
from users.models import User

from . import catalogo, fichero, ia
from .models import Evaluacion

TODAS = {k: 4 for k in catalogo.CRITERIOS}


class EvaluacionesTests(TestCase):
    def setUp(self):
        self.blas = Entrenador.objects.create(nombre="Blas Gallego")
        self.mario = Entrenador.objects.create(nombre="Mario")
        self.ana = Jugador.objects.create(nombre="Ana López", entrenador_responsable=self.blas)
        self.leo = Jugador.objects.create(nombre="Leo", entrenador_responsable=self.mario)
        ResponsableJugador.objects.create(jugador=self.ana, entrenador=self.blas, prioridad=1)
        ResponsableJugador.objects.create(jugador=self.leo, entrenador=self.mario, prioridad=1)
        self.u_blas = User.objects.create_user(username="blas", password="x", role=User.Role.ENTRENADOR)
        self.blas.user = self.u_blas
        self.blas.save(update_fields=["user"])
        self.u_mario = User.objects.create_user(username="mario", password="x", role=User.Role.ENTRENADOR)
        self.mario.user = self.u_mario
        self.mario.save(update_fields=["user"])
        self.u_dir = User.objects.create_user(username="dir", password="x", role=User.Role.SUPERADMIN)

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def crear(self, user=None, jugador=None, **extra):
        r = self.api(user or self.u_blas).post(
            "/api/evaluaciones/", {"jugador": (jugador or self.ana).id, **extra}, format="json")
        return r

    def test_evalua_a_los_suyos_con_su_nombre(self):
        r = self.crear()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["nombre_evaluador"], "Blas Gallego")
        self.assertEqual(r.data["estado"], "BORRADOR")
        self.assertEqual(r.data["fecha"], date.today().isoformat())

    def test_no_evalua_a_un_jugador_que_no_es_suyo(self):
        self.assertEqual(self.crear(jugador=self.leo).status_code, 403)

    def test_solo_ve_las_de_sus_jugadores(self):
        self.crear()
        self.crear(user=self.u_mario, jugador=self.leo)
        nombres = [e["jugador_nombre"] for e in self.api(self.u_blas).get("/api/evaluaciones/").data]
        self.assertEqual(nombres, ["Ana López"])
        self.assertEqual(len(self.api(self.u_dir).get("/api/evaluaciones/").data), 2)

    def test_otro_entrenador_no_la_cambia_y_direccion_si(self):
        ev = self.crear().data
        # Mario la ve si se le da a Ana, pero no la cambia: no es suya.
        ResponsableJugador.objects.create(jugador=self.ana, entrenador=self.mario, prioridad=2)
        url = f"/api/evaluaciones/{ev['id']}/"
        self.assertEqual(self.api(self.u_mario).patch(url, {"idioma": "EN"}, format="json").status_code, 403)
        self.assertEqual(self.api(self.u_dir).patch(url, {"idioma": "EN"}, format="json").status_code, 200)

    def test_cada_bloque_se_suma_a_lo_que_habia(self):
        ev = self.crear().data
        url = f"/api/evaluaciones/{ev['id']}/"
        c = self.api(self.u_blas)
        c.patch(url, {"puntuaciones": {"drive_preparation": 4, "drive_impact": 3}}, format="json")
        r = c.patch(url, {"puntuaciones": {"serve_toss": 5}}, format="json")
        self.assertEqual(r.data["puntuaciones"], {"drive_preparation": 4, "drive_impact": 3, "serve_toss": 5})
        self.assertEqual(r.data["puntuados"], 3)

    def test_notas_fuera_de_rango_o_desconocidas(self):
        url = f"/api/evaluaciones/{self.crear().data['id']}/"
        c = self.api(self.u_blas)
        for malas in ({"drive_impact": 6}, {"drive_impact": 0}, {"drive_impact": "4"}, {"forehand": 3}):
            self.assertEqual(c.patch(url, {"puntuaciones": malas}, format="json").status_code, 400, malas)

    @mock.patch.object(ia, "pulir", return_value="Prepara tarde la derecha cuando la bola viene alta.")
    def test_pulir_guarda_original_y_pulido(self, m):
        ev = self.crear().data
        r = self.api(self.u_blas).post(f"/api/evaluaciones/{ev['id']}/pulir/",
                                       {"bloque": "drive", "texto": "eh pues prepara tarde, la alta sobre todo"},
                                       format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIsNone(r.data["aviso"])
        com = Evaluacion.objects.get(pk=ev["id"]).comentarios["drive"]
        self.assertEqual(com["original"], "eh pues prepara tarde, la alta sobre todo")
        self.assertEqual(com["pulido"], "Prepara tarde la derecha cuando la bola viene alta.")
        m.assert_called_once_with("eh pues prepara tarde, la alta sobre todo", "ES", "el Drive")

    @mock.patch.object(ia, "pulir")
    def test_un_no_es_sin_observaciones_y_no_llama_a_claude(self, m):
        ev = self.crear().data
        self.api(self.u_blas).post(f"/api/evaluaciones/{ev['id']}/pulir/", {"bloque": "serve", "texto": "No."},
                                   format="json")
        m.assert_not_called()
        self.assertEqual(Evaluacion.objects.get(pk=ev["id"]).comentarios["serve"]["pulido"], "")

    @override_settings(ANTHROPIC_API_KEY="")
    def test_sin_clave_se_queda_el_texto_tal_cual(self):
        ev = self.crear().data
        r = self.api(self.u_blas).post(f"/api/evaluaciones/{ev['id']}/pulir/",
                                       {"bloque": "volley", "texto": "Reacciona tarde\nen la red"}, format="json")
        self.assertEqual(r.data["aviso"], "La IA no está activada.")
        self.assertEqual(r.data["comentario"]["pulido"], "Reacciona tarde | en la red")

    def test_no_se_termina_con_notas_a_medias(self):
        ev = self.crear(puntuaciones={"drive_preparation": 3}).data
        r = self.api(self.u_blas).post(f"/api/evaluaciones/{ev['id']}/terminar/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Drive (Derecha)", str(r.data))

    @mock.patch.object(ia, "resumir", return_value=(["Buen saque", "Gran derecha", "Muy motivada"],
                                                    ["Volea", "Smash", "Fuerza"]))
    def test_terminar_propone_el_resumen_una_vez(self, m):
        ev = self.crear(puntuaciones=TODAS).data
        url = f"/api/evaluaciones/{ev['id']}/terminar/"
        c = self.api(self.u_blas)
        r = c.post(url, {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["estado"], "TERMINADA")
        self.assertEqual(r.data["fortalezas"], ["Buen saque", "Gran derecha", "Muy motivada"])
        # Si el entrenador ya retocó el resumen, terminar otra vez no se lo pisa…
        c.patch(f"/api/evaluaciones/{ev['id']}/", {"fortalezas": ["Saque", "Derecha", "Actitud"]}, format="json")
        self.assertEqual(c.post(url, {}, format="json").data["fortalezas"], ["Saque", "Derecha", "Actitud"])
        # …salvo que pida otra propuesta.
        self.assertEqual(c.post(url, {"rehacer_resumen": True}, format="json").data["fortalezas"][0], "Buen saque")
        self.assertEqual(m.call_count, 2)

    @mock.patch.object(ia, "pulir", return_value="Lacks reaction at the net.")
    @mock.patch.object(ia, "resumir", return_value=(["a", "b", "c"], ["d", "e", "f"]))
    def test_al_cambiar_de_idioma_se_traduce_al_terminar(self, _resumir, pulir):
        ev = Evaluacion.objects.create(
            jugador=self.ana, evaluador=self.u_blas, nombre_evaluador="Blas", idioma="EN", puntuaciones=TODAS,
            comentarios={"volley": {"original": "carece de reacción", "pulido": "Carece de reacción.",
                                    "idioma": "ES"}})
        r = self.api(self.u_blas).post(f"/api/evaluaciones/{ev.id}/terminar/", {}, format="json")
        self.assertEqual(r.data["comentarios"]["volley"]["pulido"], "Lacks reaction at the net.")
        pulir.assert_called_once_with("carece de reacción", "EN", "la Volea")

    def test_fichero_clave_valor(self):
        ev = Evaluacion.objects.create(
            jugador=self.ana, nombre_evaluador="Blas Gallego", fecha=date(2026, 7, 22), puntuaciones=TODAS,
            comentarios={"drive": {"original": "x", "pulido": 'Muy "sólida"\n[en] cruzado'},
                         "competicion": {"original": "no", "pulido": ""}},
            fortalezas=["Saque", "Derecha", "Actitud"], mejoras=["Volea", "Smash", "Fuerza"])
        self.assertEqual(fichero.nombre(ev), "Ana López-22-07-2026-ES.txt")
        txt = fichero.contenido(ev)
        bloques = txt.strip("\n").split("\n\n")
        self.assertEqual(len(bloques), 11)  # identidad + 8 técnicos + resumen + competición
        self.assertEqual(bloques[0], "player_name=Ana López\ncoach_name=Blas Gallego\neval_date=22-07-2026")
        self.assertIn("drive_notes=Muy sólida | en cruzado", txt)
        self.assertIn("serve_notes=Sin observaciones", txt)
        self.assertIn("summary_strengths=Saque | Derecha | Actitud", txt)
        self.assertTrue(txt.endswith("competition_results=Sin resultados registrados\n"))
        lineas = [ln for ln in txt.splitlines() if ln]
        self.assertEqual(sum(ln.split("=")[1].isdigit() for ln in lineas), 34)

    def test_catalogo(self):
        r = self.api(self.u_blas).get("/api/evaluaciones/catalogo/")
        self.assertEqual([b["clave"] for b in r.data["bloques"]],
                         ["drive", "backhand", "serve", "volley", "smash", "tactic", "fitness", "psych"])
        self.assertEqual(sum(len(b["criterios"]) for b in r.data["bloques"]), 34)
