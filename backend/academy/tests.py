"""Reglas de la ficha del alumno que el motor tiene que respetar.

Run: python manage.py test academy
"""
from datetime import date, time
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from academy.models import (
    Entrenador, HorarioJugador, Jugador, Pista, ResponsableJugador, Sede, Turno,
    VacacionesEntrenador,
)
from academy.pesos import errores, reparto_por_defecto
from engine.service import _available_players, entrenador_en_franja, generate
from scheduling.models import Asignacion, Disponibilidad, Estado, Semana

LUNES = date(2026, 9, 14)


class EnAltaTests(SimpleTestCase):
    """El alta a mitad de mes: "entra el 16" quiere decir el 16, no el 1."""

    def test_sin_fechas_entrena_siempre(self):
        self.assertTrue(Jugador(nombre="X").en_alta(LUNES))

    def test_antes_de_su_alta_no(self):
        j = Jugador(nombre="X", fecha_alta=date(2026, 9, 16))
        self.assertFalse(j.en_alta(date(2026, 9, 15)))

    def test_el_dia_del_alta_ya_si(self):
        j = Jugador(nombre="X", fecha_alta=date(2026, 9, 16))
        self.assertTrue(j.en_alta(date(2026, 9, 16)))

    def test_despues_de_su_baja_no(self):
        j = Jugador(nombre="X", fecha_baja=date(2026, 9, 16))
        self.assertTrue(j.en_alta(date(2026, 9, 16)))
        self.assertFalse(j.en_alta(date(2026, 9, 17)))


class MotorRespetaElAltaTests(TestCase):
    """Lo mismo, pero donde importa: el alumno no puede salir en el cuadrante
    de un día en el que todavía no había empezado."""

    def setUp(self):
        # Las migraciones ya dejan sembrados los turnos del curso: se reusa el
        # que haya en vez de crear uno que choque con el código único.
        self.turno, _ = Turno.objects.get_or_create(
            codigo="M1",
            defaults={
                "nombre": "Mañana 1", "bloque": Turno.Bloque.MANANA,
                "hora_inicio": time(8, 30), "hora_fin": time(10, 0), "orden": 1,
            },
        )
        self.semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)
        self.nuevo = Jugador.objects.create(
            nombre="Alta el 16", activo=True, fecha_alta=date(2026, 9, 16),
        )
        self.veterano = Jugador.objects.create(nombre="De siempre", activo=True)

    def _ids(self, dia):
        return [p.id for p in _available_players(self.semana, dia, self.turno, {})]

    def test_no_sale_antes_de_su_alta(self):
        self.assertNotIn(self.nuevo.id, self._ids(0))  # lunes 14
        self.assertNotIn(self.nuevo.id, self._ids(1))  # martes 15

    def test_entra_el_dia_de_su_alta(self):
        self.assertIn(self.nuevo.id, self._ids(2))     # miércoles 16

    def test_a_los_demas_no_les_afecta(self):
        self.assertIn(self.veterano.id, self._ids(0))


class FranjaDelEntrenadorTests(SimpleTestCase):
    """El entrenador declara franja igual que el alumno; sin declararla entra
    en cualquiera, que es lo que hace la academia."""

    def setUp(self):
        self.m1 = Turno(id=1, codigo="M1", bloque=Turno.Bloque.MANANA)
        self.m2 = Turno(id=2, codigo="M2", bloque=Turno.Bloque.MANANA)
        self.t1 = Turno(id=3, codigo="T1", bloque=Turno.Bloque.TARDE)

    def test_sin_declarar_entra_en_todas(self):
        e = Entrenador(nombre="X")
        self.assertTrue(entrenador_en_franja(e, self.m1))
        self.assertTrue(entrenador_en_franja(e, self.m2))
        self.assertTrue(entrenador_en_franja(e, self.t1))

    def test_con_franja_solo_esa(self):
        e = Entrenador(nombre="X", turno_manana_id=2)
        self.assertFalse(entrenador_en_franja(e, self.m1))
        self.assertTrue(entrenador_en_franja(e, self.m2))

    def test_la_manana_no_condiciona_la_tarde(self):
        # Declarar M2 no le saca de las tardes: cada bloque va por su cuenta.
        e = Entrenador(nombre="X", turno_manana_id=2)
        self.assertTrue(entrenador_en_franja(e, self.t1))


class DiaDistintoTests(TestCase):
    """Cada bloque de un día tiene tres respuestas. «El martes por la tarde no»
    no puede sacarle también de las mañanas del martes, que es lo que pasaba
    cuando un turno vacío valía por «no entrena»."""

    FRANJAS = {
        "M1": (Turno.Bloque.MANANA, time(8, 30), time(10, 0), 1),
        "M2": (Turno.Bloque.MANANA, time(10, 30), time(12, 30), 2),
        "T1": (Turno.Bloque.TARDE, time(14, 15), time(15, 30), 4),
        "T2": (Turno.Bloque.TARDE, time(15, 30), time(17, 30), 5),
    }

    def setUp(self):
        self.turnos = {}
        for codigo, (bloque, ini, fin, orden) in self.FRANJAS.items():
            self.turnos[codigo], _ = Turno.objects.get_or_create(
                codigo=codigo,
                defaults={"nombre": codigo, "bloque": bloque, "hora_inicio": ini,
                          "hora_fin": fin, "orden": orden},
            )
        self.semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)
        self.jug = Jugador.objects.create(nombre="Sin franja fija", activo=True)

    def _donde(self, dia):
        mapa = {
            (h.jugador_id, h.dia): (h.turno_manana_id, h.turno_tarde_id,
                                    h.entrena_manana, h.entrena_tarde)
            for h in HorarioJugador.objects.all()
        }
        return {
            codigo for codigo, t in self.turnos.items()
            if any(p.id == self.jug.id for p in _available_players(
                self.semana, dia, t, {}, horario=mapa))
        }

    def test_la_tarde_no_deja_las_mananas_como_estaban(self):
        HorarioJugador.objects.create(jugador=self.jug, dia=1, entrena_tarde=False)
        self.assertEqual(self._donde(1), {"M1", "M2"})

    def test_no_entrena_ese_dia(self):
        HorarioJugador.objects.create(
            jugador=self.jug, dia=1, entrena_manana=False, entrena_tarde=False,
        )
        self.assertEqual(self._donde(1), set())

    def test_franja_concreta_por_la_manana_y_tarde_no(self):
        HorarioJugador.objects.create(
            jugador=self.jug, dia=1, turno_manana=self.turnos["M2"],
            entrena_tarde=False,
        )
        self.assertEqual(self._donde(1), {"M2"})

    def test_el_resto_de_dias_no_cambian(self):
        HorarioJugador.objects.create(jugador=self.jug, dia=1, entrena_tarde=False)
        self.assertEqual(self._donde(3), {"M1", "M2", "T1", "T2"})


class AusenciaEntrenadorPorFranjaTests(SimpleTestCase):
    """El entrenador falta el día entero, un bloque o una sola franja."""

    def _t(self, codigo, bloque):
        return Turno(codigo=codigo, bloque=bloque)

    def test_todo_el_dia(self):
        v = VacacionesEntrenador(ambito="DIA")
        self.assertTrue(v.afecta_turno(self._t("M1", "MANANA")))
        self.assertTrue(v.afecta_turno(self._t("T2", "TARDE")))

    def test_solo_una_franja(self):
        v = VacacionesEntrenador(ambito="M1")
        self.assertTrue(v.afecta_turno(self._t("M1", "MANANA")))
        self.assertFalse(v.afecta_turno(self._t("M2", "MANANA")))

    def test_un_bloque_no_toca_el_otro(self):
        v = VacacionesEntrenador(ambito="TARDE")
        self.assertFalse(v.afecta_turno(self._t("M2", "MANANA")))
        self.assertTrue(v.afecta_turno(self._t("T1", "TARDE")))


class VieneAdemasTests(TestCase):
    """El entrenador apunta que un día viene a una franja que no le toca: entra
    en esa, y solo en esa, aunque su horario o sus topes digan que no."""

    def setUp(self):
        self.turnos = {}
        for codigo, (bloque, ini, fin, orden) in DiaDistintoTests.FRANJAS.items():
            self.turnos[codigo], _ = Turno.objects.get_or_create(
                codigo=codigo,
                defaults={"nombre": codigo, "bloque": bloque, "hora_inicio": ini,
                          "hora_fin": fin, "orden": orden},
            )
        self.semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)
        self.jug = Jugador.objects.create(nombre="Excepción", activo=True)
        # Según su horario, los martes no viene por la mañana.
        HorarioJugador.objects.create(jugador=self.jug, dia=1, entrena_manana=False)

    def _entra(self, codigo, **extra):
        mapa = {
            (h.jugador_id, h.dia): (h.turno_manana_id, h.turno_tarde_id,
                                    h.entrena_manana, h.entrena_tarde)
            for h in HorarioJugador.objects.all()
        }
        return any(p.id == self.jug.id for p in _available_players(
            self.semana, 1, self.turnos[codigo], {}, horario=mapa, **extra))

    def _apuntar(self, ambito="M2"):
        Disponibilidad.objects.create(
            semana=self.semana, jugador=self.jug, dia=1, ambito=ambito,
            estado=Estado.EXTRA,
        )

    def test_sin_excepcion_manda_el_horario(self):
        self.assertFalse(self._entra("M2"))

    def test_viene_ademas_solo_a_esa_franja(self):
        self._apuntar("M2")
        self.assertTrue(self._entra("M2"))
        self.assertFalse(self._entra("M1"))

    def test_aunque_ya_haya_cubierto_sus_topes(self):
        self._apuntar("M2")
        self.assertTrue(self._entra(
            "M2",
            hechas_bloque={(self.jug.id, "MANANA"): 5},
            hechas_dia={self.jug.id: 5},
        ))


class OrganigramaFueraDeServicioTests(TestCase):
    """Quien está fuera de servicio sigue en su bloque pero no responde por
    ningún alumno, se escriba su ficha como se escriba. En producción es
    «Jorge Ibañez» y la tabla dice «JORGE IBAÑEZ»: comparando letra a letra se
    quedó con la mitad de la D5."""

    def test_no_se_le_asignan_alumnos_con_el_nombre_de_produccion(self):
        jorge = Entrenador.objects.create(nombre="Jorge Ibañez", activo=True)
        mario = Entrenador.objects.create(nombre="Mario Muniesa", activo=True)
        call_command("aplicar_grupos", stdout=StringIO())

        self.assertFalse(Jugador.objects.filter(entrenador_responsable=jorge).exists())
        self.assertTrue(Jugador.objects.filter(entrenador_responsable=mario).exists())
        jorge.refresh_from_db()
        self.assertFalse(jorge.disponible_semana)
        # Sigue en su bloque, pero no entrena a nadie: no tiene porcentajes.
        self.assertFalse(ResponsableJugador.objects.filter(entrenador=jorge).exists())


class RepartoPorDefectoTests(SimpleTestCase):
    """La regla de dirección: los secundarios con un 10% cada uno como mínimo
    y el principal, lo que queda."""

    def test_el_ejemplo_de_carlos_taberner(self):
        self.assertEqual(
            reparto_por_defecto(["Víctor"], ["Dani", "Javi", "Blas", "Emilio"]),
            [("Víctor", 1, 60), ("Dani", 2, 10), ("Javi", 2, 10),
             ("Blas", 2, 10), ("Emilio", 2, 10)],
        )

    def test_si_la_columna_la_firman_varios_se_reparten_el_principal(self):
        self.assertEqual(
            reparto_por_defecto(["Javi", "Blas", "Emilio"], ["Dani", "Víctor"]),
            [("Javi", 1, 27), ("Blas", 1, 27), ("Emilio", 1, 26),
             ("Dani", 2, 10), ("Víctor", 2, 10)],
        )

    def test_lo_que_no_se_puede_guardar(self):
        self.assertEqual(errores([("V", 1, 90), ("D", 2, 10)]), [])
        self.assertIn("mínimo", " ".join(errores([("V", 1, 95), ("D", 2, 5)])))
        self.assertIn("suman 90", " ".join(errores([("V", 1, 80), ("D", 2, 10)])))
        self.assertIn("principal", " ".join(errores([("D", 2, 100)])))


class OrganigramaPorcentajesTests(TestCase):
    """Del organigrama salen por separado el nivel, quién gestiona y con quién
    entrena cada alumno."""

    @classmethod
    def setUpTestData(cls):
        call_command("aplicar_grupos", stdout=StringIO())

    def _ficha(self, modelo, nombre):
        """La ficha que el comando le da a un nombre de la tabla: la base de
        pruebas ya trae alumnos y entrenadores con su nombre completo."""
        from academy.management.commands.aplicar_grupos import Command, clave

        idx = {clave(o.nombre): o for o in modelo.objects.order_by("activo", "id")}
        return Command()._buscar(modelo, nombre, idx)

    def _entrenador(self, nombre):
        return self._ficha(Entrenador, nombre).pk

    def _porcentajes(self, nombre):
        return {r.entrenador_id: (r.prioridad, r.porcentaje_objetivo)
                for r in self._ficha(Jugador, nombre).responsables.all()}

    def test_carlos_taberner_con_victor_de_principal(self):
        victor = self._entrenador("VICTOR REDONDO")
        esperado = {victor: (1, 60)}
        for n in ("DANI GIMENO", "JAVI GIMENEZ", "BLAS GALLEGO", "EMILIO SORIO"):
            esperado[self._entrenador(n)] = (2, 10)
        self.assertEqual(self._porcentajes("Carlos Taberner"), esperado)
        j = self._ficha(Jugador, "Carlos Taberner")
        self.assertEqual((j.entrenador_responsable_id, j.division.nivel), (victor, 1))

    def test_el_nivel_no_decide_el_grupo(self):
        # Maria Adrienko es de nivel 4, pero va en la columna de Javi / Blas / Emilio.
        j = self._ficha(Jugador, "Maria Adrienko")
        self.assertEqual(j.division.nivel, 4)
        principales = {e for e, (p, _c) in self._porcentajes("Maria Adrienko").items() if p == 1}
        self.assertEqual(principales, {self._entrenador(n) for n in
                                       ("JAVI GIMENEZ", "BLAS GALLEGO", "EMILIO SORIO")})
        self.assertIn(j.entrenador_responsable_id, principales)

    def test_elina_con_su_entrenador_particular(self):
        self.assertEqual(self._porcentajes("Elina Avanesyan"),
                         {self._entrenador("JORGE GARCIA"): (1, 100)})

    def test_el_organigrama_suma_cien_y_el_resto_sale_del_grupo(self):
        totales = [sum(j.responsables.values_list("porcentaje_objetivo", flat=True))
                   for j in Jugador.objects.filter(activo=True)]
        self.assertEqual(totales.count(100), 57)
        self.assertLessEqual(set(totales), {0, 100})


class PorcentajesDelJugadorApiTests(TestCase):
    """Los porcentajes se ponen a mano y se guardan todos a la vez."""

    def setUp(self):
        from rest_framework.test import APIClient

        from users.models import User

        self.User = User
        self.api = APIClient()
        self.api.force_authenticate(User.objects.create_user(
            username="direccion", password="x", role=User.Role.SUPERADMIN))
        self.victor = Entrenador.objects.create(nombre="Víctor")
        self.dani = Entrenador.objects.create(nombre="Dani")
        self.jugador = Jugador.objects.create(nombre="Carlos")
        self.url = f"/api/jugadores/{self.jugador.id}/entrenadores/"

    def _cuerpo(self, victor, dani):
        return {"responsable": self.victor.id, "entrenadores": [
            {"entrenador": self.victor.id, "prioridad": 1, "porcentaje": victor},
            {"entrenador": self.dani.id, "prioridad": 2, "porcentaje": dani},
        ]}

    def test_guarda_los_porcentajes_y_el_responsable(self):
        r = self.api.post(self.url, self._cuerpo(90, 10), format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(
            [(f["nombre"], f["porcentaje"]) for f in r.json()["entrenadores"]],
            [("Víctor", 90), ("Dani", 10)],
        )
        self.jugador.refresh_from_db()
        self.assertEqual(self.jugador.entrenador_responsable, self.victor)

    def test_no_guarda_un_secundario_por_debajo_del_minimo(self):
        r = self.api.post(self.url, self._cuerpo(95, 5), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.jugador.responsables.exists())

    def test_un_entrenador_no_los_cambia(self):
        from rest_framework.test import APIClient

        usuario = self.User.objects.create_user(
            username="dani", password="x", role=self.User.Role.ENTRENADOR)
        Entrenador.objects.filter(pk=self.dani.pk).update(user=usuario)
        ResponsableJugador.objects.create(
            jugador=self.jugador, entrenador=self.dani, prioridad=1,
            porcentaje_objetivo=100)
        api = APIClient()
        api.force_authenticate(usuario)
        r = api.post(self.url, self._cuerpo(90, 10), format="json")
        self.assertEqual(r.status_code, 403)


class MananaEnteraMotorTests(TestCase):
    """El motor decide la mañana de una vez: reparte entre 8:30 y 10:30, no
    frena a nadie por un cupo semanal y no manda jugadores a una franja sin
    entrenadores."""

    def setUp(self):
        Sede.objects.update(activa=False)
        Turno.objects.update(activo=False)
        Entrenador.objects.update(activo=False)
        Jugador.objects.update(activo=False)
        self.sede = Sede.objects.create(
            nombre="Prueba", es_satelite=False, densidad_default=2, densidad_max=4,
            orden_desbordamiento=0, activa=True,
        )
        for n in range(1, 5):
            Pista.objects.create(sede=self.sede, numero=n, superficie="TIERRA", activa=True)
        self.turnos = {}
        for codigo, (bloque, ini, fin, orden) in DiaDistintoTests.FRANJAS.items():
            if bloque != Turno.Bloque.MANANA:
                continue
            turno, _ = Turno.objects.get_or_create(
                codigo=codigo,
                defaults={"nombre": codigo, "bloque": bloque, "hora_inicio": ini,
                          "hora_fin": fin, "orden": orden},
            )
            turno.activo = True
            turno.save(update_fields=["activo"])
            self.turnos[codigo] = turno
        self.semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)

    def _jugadores(self, n):
        return [Jugador.objects.create(nombre=f"J{i}", activo=True) for i in range(n)]

    def _por_franja(self, dia=0):
        return {
            codigo: Asignacion.objects.filter(semana=self.semana, dia=dia, turno=t).count()
            for codigo, t in self.turnos.items()
        }

    def test_reparte_la_manana_entre_las_dos_franjas(self):
        Entrenador.objects.create(nombre="A")
        Entrenador.objects.create(nombre="B")
        self._jugadores(8)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertEqual(self._por_franja(), {"M1": 4, "M2": 4})

    def test_sin_cupo_semanal_entrena_todos_los_dias(self):
        Entrenador.objects.create(nombre="A")
        jugadores = self._jugadores(2)
        generate(self.semana, dias=[0, 1, 2, 3, 4], bloques=["MANANA"])
        for j in jugadores:
            self.assertEqual(
                Asignacion.objects.filter(semana=self.semana, jugador=j).count(), 5)

    def test_el_de_reserva_no_recibe_pistas(self):
        # Está disponible, pero el motor no le da grupo: es de banquillo.
        Entrenador.objects.create(nombre="Sergio", reserva=True)
        self._jugadores(4)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertEqual(Asignacion.objects.filter(
            semana=self.semana, entrenador__nombre="Sergio").count(), 0)
        # Y sin nadie más, las pistas salen sin entrenador en vez de con él.
        self.assertTrue(Asignacion.objects.filter(semana=self.semana, entrenador=None).exists())

    def test_a_una_franja_sin_entrenadores_no_va_nadie(self):
        # El único entrenador solo da clase a las 8:30.
        Entrenador.objects.create(nombre="A", turno_manana=self.turnos["M1"])
        self._jugadores(4)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertEqual(self._por_franja(), {"M1": 4, "M2": 0})

    def test_quien_se_queda_fuera_entra_el_dia_siguiente(self):
        # Una sola pista de dos y una sola franja para tres: el que se queda
        # fuera el lunes tiene sitio el martes.
        self.turnos.pop("M2").delete()
        Pista.objects.filter(sede=self.sede).exclude(numero=1).delete()
        self.sede.densidad_max = 2
        self.sede.save(update_fields=["densidad_max"])
        Entrenador.objects.create(nombre="A")
        jugadores = self._jugadores(3)
        generate(self.semana, dias=[0, 1], bloques=["MANANA"])
        lunes = set(Asignacion.objects.filter(semana=self.semana, dia=0)
                    .values_list("jugador_id", flat=True))
        martes = set(Asignacion.objects.filter(semana=self.semana, dia=1)
                     .values_list("jugador_id", flat=True))
        fuera_el_lunes = {j.id for j in jugadores} - lunes
        self.assertEqual(len(fuera_el_lunes), 1)
        self.assertTrue(fuera_el_lunes <= martes)

