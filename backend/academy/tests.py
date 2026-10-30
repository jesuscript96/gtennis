"""Reglas de la ficha del alumno que el motor tiene que respetar.

Run: python manage.py test academy
"""
from datetime import date, time, timedelta
from io import StringIO

from django.core.management import call_command
from django.db.models import Q
from django.test import SimpleTestCase, TestCase

from academy.models import (
    Coach, Entrenador, HorarioJugador, Invitado, Jugador, Pista, ResponsableJugador, Sede, Turno,
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



class RespetaLoHechoAManoTests(TestCase):
    """Rehacer el día (01/10/2026) no deshace lo que se tocó a mano: lo puesto
    a mano se queda, a quien se quitó no se le vuelve a poner, y una falta
    declarada después sí manda."""

    # Mismo escenario que la mañana entera, sin heredar sus tests.
    _jugadores = MananaEnteraMotorTests._jugadores

    def setUp(self):
        MananaEnteraMotorTests.setUp(self)
        self.a = Entrenador.objects.create(nombre="A")
        self.b = Entrenador.objects.create(nombre="B")
        self.jugadores = self._jugadores(6)
        generate(self.semana, dias=[0], bloques=["MANANA"])

    def _fila(self, jugador):
        return Asignacion.objects.get(semana=self.semana, dia=0, jugador=jugador)

    def test_lo_puesto_a_mano_sigue_igual_tras_rehacer(self):
        fila = self._fila(self.jugadores[0])
        fila.manual = True
        fila.entrenador = self.b
        fila.save()
        antes = (fila.turno_id, fila.pista_id, fila.entrenador_id)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        despues = self._fila(self.jugadores[0])
        self.assertEqual((despues.turno_id, despues.pista_id, despues.entrenador_id), antes)
        self.assertTrue(despues.manual)
        # Nadie más entra en esa pista a esa hora.
        self.assertEqual(Asignacion.objects.filter(
            semana=self.semana, dia=0, turno_id=antes[0], pista_id=antes[1]).count(), 1)

    def test_el_quitado_a_mano_no_vuelve(self):
        from rest_framework.test import APIClient

        from users.models import User

        admin = User.objects.create_user(
            username="ivan", password="x", role=User.Role.SUPERADMIN)
        api = APIClient()
        api.force_authenticate(admin)
        fila = self._fila(self.jugadores[1])
        self.assertEqual(api.delete(f"/api/asignaciones/{fila.id}/").status_code, 204)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertFalse(Asignacion.objects.filter(
            semana=self.semana, dia=0, jugador=self.jugadores[1]).exists())

    def test_una_falta_despues_saca_al_puesto_a_mano(self):
        from scheduling.models import AusenciaJugador

        fila = self._fila(self.jugadores[2])
        fila.manual = True
        fila.save()
        AusenciaJugador.objects.create(
            jugador=self.jugadores[2], fecha_inicio=LUNES, fecha_fin=LUNES,
            ambito="DIA", estado="AUSENCIA_JUGADOR",
        )
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertFalse(Asignacion.objects.filter(
            semana=self.semana, dia=0, jugador=self.jugadores[2]).exists())


class SuperficiePorFechasTests(TestCase):
    """«Del 5 al 9, resina»: se declara desde el calendario de faltas, la pone
    el coach o el entrenador (06/10/2026, con aviso a su head coach) para los
    alumnos que ve, y manda sobre la superficie fija de la ficha."""

    def setUp(self):
        from rest_framework.test import APIClient

        from academy.models import Coach
        from users.models import User

        self.usuario_dani = User.objects.create_user(
            username="dani", password="x", role=User.Role.ENTRENADOR)
        self.dani = Entrenador.objects.create(nombre="Dani", user=self.usuario_dani)
        self.suyo = Jugador.objects.create(nombre="Carlos", entrenador_responsable=self.dani)
        self.dani.jugadores_gestionados.add(self.suyo)
        self.ajeno = Jugador.objects.create(
            nombre="Otro", entrenador_responsable=Entrenador.objects.create(nombre="Otro"))
        usuario = User.objects.create_user(
            username="pablo", password="x", role=User.Role.COACH)
        self.usuario_pablo = usuario
        Coach.objects.create(nombre="Pablo", user=usuario).entrenadores.add(self.dani)
        self.api = APIClient()
        self.api.force_authenticate(usuario)

    def test_el_entrenador_la_pone_para_los_suyos_y_avisa_al_head_coach(self):
        from rest_framework.test import APIClient

        from academy.models import Aviso

        api = APIClient()
        api.force_authenticate(self.usuario_dani)
        datos = {"superficie": "RESINA", "fecha_desde": "2026-10-05",
                 "fecha_hasta": "2026-10-09", "estricta": True}
        r = api.post("/api/preferencias-superficie/",
                     {"jugador": self.suyo.id, **datos}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        pref_id = r.json()["id"]
        aviso = Aviso.objects.get(usuario=self.usuario_pablo)
        self.assertIn("Carlos entrena en resina del 05/10 al 09/10", aviso.titulo)
        self.assertIn("Dani", aviso.mensaje)
        r = api.post("/api/preferencias-superficie/",
                     {"jugador": self.ajeno.id, **datos}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(api.delete(f"/api/preferencias-superficie/{pref_id}/").status_code, 204)
        self.assertTrue(Aviso.objects.filter(
            usuario=self.usuario_pablo, titulo__startswith="Superficie quitada").exists())

    def _crear(self, jugador, sup, desde, hasta):
        return self.api.post("/api/preferencias-superficie/", {
            "jugador": jugador.id, "superficie": sup,
            "fecha_desde": desde, "fecha_hasta": hasta, "estricta": True,
        }, format="json")

    def test_el_coach_la_declara_para_su_grupo_y_no_para_otro(self):
        self.assertEqual(self._crear(self.suyo, "RESINA", "2026-10-05", "2026-10-09").status_code, 201)
        self.assertEqual(self._crear(self.ajeno, "RESINA", "2026-10-05", "2026-10-09").status_code, 403)
        r = self.api.get("/api/preferencias-superficie/")
        filas = r.json().get("results", r.json())
        self.assertEqual([f["jugador"] for f in filas], [self.suyo.id])

    def test_no_se_pisan_dos_superficies_en_las_mismas_fechas(self):
        self._crear(self.suyo, "RESINA", "2026-10-05", "2026-10-09")
        r = self._crear(self.suyo, "TIERRA", "2026-10-08", "2026-10-12")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self._crear(self.suyo, "TIERRA", "2026-10-10", "2026-10-12").status_code, 201)

    def test_la_de_fechas_manda_sobre_la_fija_de_la_ficha(self):
        from academy.models import PreferenciaSuperficie
        from engine.service import _jugador_motor

        PreferenciaSuperficie.objects.create(jugador=self.suyo, superficie="TIERRA")
        self._crear(self.suyo, "RESINA", "2026-10-05", "2026-10-09")
        prefs = sorted(
            PreferenciaSuperficie.objects.filter(estricta=True),
            key=lambda ps: (ps.fecha_desde is None and ps.fecha_hasta is None, -ps.id),
        )
        tabla = {self.suyo.id: [(p.superficie, p.fecha_desde, p.fecha_hasta) for p in prefs]}
        dentro = _jugador_motor(self.suyo, date(2026, 10, 7), {}, tabla, 1, False)
        fuera = _jugador_motor(self.suyo, date(2026, 10, 12), {}, tabla, 1, False)
        self.assertEqual((dentro.surface_pref, fuera.surface_pref), ("RESINA", "TIERRA"))


class EntrenadorSoloManualTests(TestCase):
    """Álvaro, Alberto y Jorge Milla: el motor no les pone nunca, ni siendo
    los responsables del alumno. Solo entran a mano desde el cuadrante."""

    def test_el_motor_no_le_pone_aunque_sea_el_responsable(self):
        sede = Sede.objects.create(nombre="Prueba solo manual")
        Pista.objects.create(sede=sede, numero=1)
        manual = Entrenador.objects.create(nombre="Solo a mano", solo_manual=True)
        normal = Entrenador.objects.create(nombre="Normal")
        semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)
        for n in ("A", "B"):
            j = Jugador.objects.create(nombre=n, activo=True, entrenador_responsable=manual)
            ResponsableJugador.objects.create(
                jugador=j, entrenador=manual, prioridad=1, porcentaje_objetivo=100)
        generate(semana, dias=[0])
        asignadas = Asignacion.objects.filter(semana=semana)
        self.assertTrue(asignadas.exists())
        self.assertFalse(asignadas.filter(entrenador=manual).exists())
        self.assertTrue(asignadas.filter(entrenador=normal).exists())


class TorneoSacaDelCuadranteTests(TestCase):
    """«En torneo» es una falta: el alumno no está en el club y no sale en
    pista, igual que con una lesión."""

    def test_en_torneo_no_entra(self):
        from scheduling.models import AusenciaJugador

        turno, _ = Turno.objects.get_or_create(
            codigo="M1",
            defaults={"nombre": "M1", "bloque": Turno.Bloque.MANANA,
                      "hora_inicio": time(8, 30), "hora_fin": time(10, 0), "orden": 1},
        )
        semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)
        fuera = Jugador.objects.create(nombre="De torneo", activo=True)
        queda = Jugador.objects.create(nombre="En casa", activo=True)
        AusenciaJugador.objects.create(
            jugador=fuera, fecha_inicio=LUNES, fecha_fin=LUNES, estado=Estado.EN_TORNEO)
        ids = [p.id for p in _available_players(semana, 0, turno, {})]
        self.assertNotIn(fuera.id, ids)
        self.assertIn(queda.id, ids)


class TopeDiasParejaTests(TestCase):
    """Dos alumnos no comparten pista más de 3 días a la semana, aunque su
    pareja esté declarada y sean los únicos de su nivel."""

    def _dias_juntos(self, tope):
        from academy.models import PreferenciaPareja
        from scheduling.models import ConfiguracionMotor

        cfg = ConfiguracionMotor.objects.first() or ConfiguracionMotor.objects.create()
        cfg.max_dias_misma_pista = tope
        cfg.peso_repeticion = 0
        cfg.time_limit_s = 2
        cfg.save()
        # Una pista y un entrenador: o entrenan juntos o uno se queda fuera.
        # Las migraciones siembran alumnos, entrenadores y pistas reales: fuera.
        Jugador.objects.update(activo=False)
        Entrenador.objects.update(activo=False)
        Pista.objects.update(activa=False)
        sede = Sede.objects.create(nombre="Prueba tope pareja")
        Pista.objects.create(sede=sede, numero=1)
        Entrenador.objects.create(nombre="Uno")
        semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)
        a = Jugador.objects.create(nombre="A", activo=True)
        b = Jugador.objects.create(nombre="B", activo=True)
        PreferenciaPareja.objects.create(jugador=a, jugador_objetivo=b, tipo="SOFT")
        for j in (a, b):
            for d in range(6):
                HorarioJugador.objects.create(
                    jugador=j, dia=d, entrena_manana=d < 5, entrena_tarde=False)
        generate(semana, dias=[0, 1, 2, 3, 4])
        celdas = {}
        for x in Asignacion.objects.filter(semana=semana):
            celdas.setdefault((x.dia, x.turno_id, x.pista_id), set()).add(x.jugador_id)
        return {d for (d, _t, _p), ids in celdas.items() if {a.id, b.id} <= ids}

    def test_no_pasan_de_tres_dias_juntos(self):
        self.assertLessEqual(len(self._dias_juntos(3)), 3)

    def test_sin_tope_repiten_mas(self):
        # Control: sin tope y sin penalizar la repetición, la pareja declarada
        # sale junta los cinco días. Si esto falla, el test de arriba no prueba
        # nada.
        self.assertGreater(len(self._dias_juntos(0)), 3)


class TardeConT2YEntrenadorDeTardeTests(TestCase):
    """13/10/2026: por la tarde, quien no cabe en T1 pasa a T2 (aunque T2 sea
    la franja de una escuela); y el entrenador que solo entra con unos
    jugadores (Dani con su lista, mañana y tarde desde el 14/10) entra solo si
    alguno viene, y a una pista solo de ellos."""

    def setUp(self):
        from academy.models import Escuela
        from scheduling.models import ConfiguracionMotor

        cfg = ConfiguracionMotor.objects.first() or ConfiguracionMotor.objects.create()
        cfg.time_limit_s = 2
        cfg.modo_satelites = "NUNCA"
        cfg.save()
        Jugador.objects.update(activo=False)
        Entrenador.objects.update(activo=False)
        Pista.objects.update(activa=False)
        self.t1 = Turno.objects.get(codigo="T1")
        self.t2 = Turno.objects.get(codigo="T2")
        Turno.objects.filter(pk__in=[self.t1.pk, self.t2.pk]).update(activo=True)
        Escuela.objects.create(nombre="Escuela de prueba T2", turno_unico=self.t2)
        self.sede = Sede.objects.create(nombre="Prueba tarde")
        self.semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)

    def _jugador(self, nombre, nivel, tarde=True):
        from academy.models import Division

        division, _ = Division.objects.get_or_create(nivel=nivel)
        j = Jugador.objects.create(nombre=nombre, activo=True, division=division)
        HorarioJugador.objects.create(
            jugador=j, dia=0, entrena_manana=False, entrena_tarde=tarde,
            turno_tarde=self.t1 if tarde else None)
        return j

    def _tarde(self):
        generate(self.semana, dias=[0], bloques=["TARDE"])
        return Asignacion.objects.filter(semana=self.semana, dia=0)

    def test_quien_no_cabe_en_t1_va_a_t2(self):
        Pista.objects.create(sede=self.sede, numero=1)
        Entrenador.objects.create(nombre="Uno")
        for i in range(4):
            self._jugador(f"J{i}", 5)
        asig = self._tarde()
        self.assertEqual(asig.filter(turno=self.t1).count(), 3)
        self.assertEqual(asig.filter(turno=self.t2).count(), 1)

    def test_en_t2_puede_ir_solo_antes_que_quedarse_fuera(self):
        # Una pista: T1 con tres del mismo nivel y el cuarto, de otro, a T2
        # aunque no tenga con quién.
        Pista.objects.create(sede=self.sede, numero=1, superficie="TIERRA")
        Entrenador.objects.create(nombre="Uno")
        for i in range(3):
            self._jugador(f"J{i}", 5)
        solo = self._jugador("Solo", 9)
        asig = self._tarde()
        self.assertEqual(asig.filter(turno=self.t2, jugador=solo).count(), 1)

    def _con_dani(self, viene_taberner):
        # Los D1 juegan en tierra.
        for n in (1, 2):
            Pista.objects.create(sede=self.sede, numero=n, superficie="TIERRA")
        dani = Entrenador.objects.create(nombre="Dani")
        otro = Entrenador.objects.create(nombre="Otro")
        taberner = self._jugador("Taberner", 1, tarde=viene_taberner)
        dani.solo_con.add(taberner)
        for i in range(3):
            self._jugador(f"D6-{i}", 6)
        return dani, otro, taberner, self._tarde()

    def test_dani_va_con_taberner_y_a_ninguna_otra(self):
        dani, otro, taberner, asig = self._con_dani(True)
        de_dani = asig.filter(entrenador=dani)
        self.assertEqual(set(de_dani.values_list("jugador", flat=True)), {taberner.id})
        self.assertEqual(asig.filter(turno=self.t1, entrenador=otro).count(), 3)

    def test_sin_taberner_dani_no_entra_por_la_tarde(self):
        dani, otro, _t, asig = self._con_dani(False)
        self.assertFalse(asig.filter(entrenador=dani).exists())
        self.assertEqual(asig.filter(entrenador=otro).count(), 3)

    def test_dani_junta_a_los_de_su_lista_en_su_pista(self):
        # 14/10/2026: Dani solo entra con su lista, y el motor los junta.
        for n in (1, 2):
            Pista.objects.create(sede=self.sede, numero=n, superficie="TIERRA")
        dani = Entrenador.objects.create(nombre="Dani")
        Entrenador.objects.create(nombre="Otro")
        taberner = self._jugador("Taberner", 1)
        lopez = self._jugador("Lopez", 2)
        dani.solo_con.add(taberner, lopez)
        for i in range(3):
            self._jugador(f"D6-{i}", 6)
        asig = self._tarde()
        self.assertEqual(set(asig.filter(entrenador=dani).values_list("jugador", flat=True)),
                         {taberner.id, lopez.id})

    def test_en_la_pista_de_dani_no_entra_nadie_de_fuera_de_su_lista(self):
        for n in (1, 2):
            Pista.objects.create(sede=self.sede, numero=n, superficie="TIERRA")
        dani = Entrenador.objects.create(nombre="Dani")
        Entrenador.objects.create(nombre="Otro")
        taberner = self._jugador("Taberner", 1)
        self._jugador("Ajeno", 1)
        dani.solo_con.add(taberner)
        asig = self._tarde()
        self.assertEqual(asig.count(), 2)
        self.assertTrue(set(asig.filter(entrenador=dani).values_list("jugador", flat=True))
                        <= {taberner.id})

    def test_por_la_manana_dani_tambien_solo_con_su_lista(self):
        from academy.models import Division

        m1 = Turno.objects.get(codigo="M1")
        for n in (1, 2, 3):
            Pista.objects.create(sede=self.sede, numero=n, superficie="TIERRA")
        dani = Entrenador.objects.create(nombre="Dani")
        for i in range(2):
            Entrenador.objects.create(nombre=f"Otro{i}")

        def de_manana(nombre, nivel):
            division, _ = Division.objects.get_or_create(nivel=nivel)
            j = Jugador.objects.create(nombre=nombre, activo=True, division=division)
            HorarioJugador.objects.create(
                jugador=j, dia=0, entrena_manana=True, entrena_tarde=False,
                turno_manana=m1)
            return j

        taberner, sanchez = de_manana("Taberner", 1), de_manana("Sanchez", 1)
        dani.solo_con.add(taberner, sanchez)
        for i in range(4):
            de_manana(f"D2-{i}", 2)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        asig = Asignacion.objects.filter(semana=self.semana, dia=0)
        self.assertEqual(asig.count(), 6)
        self.assertEqual(set(asig.filter(entrenador=dani).values_list("jugador", flat=True)),
                         {taberner.id, sanchez.id})

    def test_el_contrato_no_le_lleva_a_una_pista_con_alguien_de_fuera(self):
        from academy.models import Contrato

        Pista.objects.create(sede=self.sede, numero=1, superficie="TIERRA")
        dani = Entrenador.objects.create(nombre="Dani")
        Entrenador.objects.create(nombre="Otro")
        taberner = self._jugador("Taberner", 1)
        dani.solo_con.add(taberner)
        Contrato.objects.create(jugador=taberner, entrenador=dani, tipo="DURO", activo=True)
        self._jugador("Ajeno", 1)
        asig = self._tarde()
        self.assertEqual(asig.filter(turno=self.t1).count(), 2)
        self.assertFalse(asig.filter(entrenador=dani).exists())

    def test_sin_nadie_de_su_lista_dani_se_queda_en_el_banquillo(self):
        Pista.objects.create(sede=self.sede, numero=1, superficie="TIERRA")
        dani = Entrenador.objects.create(nombre="Dani")
        dani.solo_con.add(self._jugador("Taberner", 1, tarde=False))
        for i in range(2):
            self._jugador(f"D1-{i}", 1)
        asig = self._tarde()
        self.assertEqual(asig.count(), 2)
        self.assertFalse(asig.filter(entrenador=dani).exists())


class ResponsableGestionTests(TestCase):
    """El responsable de un alumno («Gestión») lo ve —y lo tiene el primero de
    su lista—, y quien lo tiene a su cargo (`jugadores_gestionados`) también,
    aunque ya no sea su responsable."""

    def setUp(self):
        from rest_framework.test import APIClient

        from users.models import User

        usuario = User.objects.create_user(
            username="victor", password="x", role=User.Role.ENTRENADOR)
        self.victor = Entrenador.objects.create(nombre="Victor", user=usuario)
        self.otro = Entrenador.objects.create(nombre="Otro")
        self.api = APIClient()
        self.api.force_authenticate(usuario)

    def test_ve_a_los_suyos_y_a_los_que_tiene_a_cargo(self):
        from academy.scope import jugadores_visibles

        suyo = Jugador.objects.create(nombre="Suyo", entrenador_responsable=self.victor)
        a_cargo = Jugador.objects.create(nombre="A cargo", entrenador_responsable=self.otro)
        self.victor.jugadores_gestionados.add(a_cargo)
        Jugador.objects.create(nombre="Ajeno", entrenador_responsable=self.otro)
        ids = set(jugadores_visibles(self.victor.user).values_list("id", flat=True))
        self.assertEqual(ids, {suyo.id, a_cargo.id})

    def test_el_entrenador_ve_quien_lo_gestiona_pero_no_lo_cambia(self):
        j = Jugador.objects.create(nombre="Carlos", entrenador_responsable=self.victor)
        fila = self.api.get("/api/jugadores/").json()
        fila = fila.get("results", fila)[0]
        self.assertEqual((fila["entrenador_responsable"], fila["entrenador_nombre"]),
                         (self.victor.id, "Victor"))
        self.api.patch(f"/api/jugadores/{j.id}/", {"entrenador_responsable": self.otro.id},
                       format="json")
        j.refresh_from_db()
        self.assertEqual(j.entrenador_responsable_id, self.victor.id)


class GestionCompartidaTests(TestCase):
    """Dos entrenadores gestionan al mismo alumno (06/10/2026: Mario y Jorge
    Ibáñez): los dos lo ven y a los dos les sale como suyo."""

    def test_el_cogestor_lo_ve_y_le_sale_como_suyo(self):
        from rest_framework.test import APIClient

        from academy.scope import jugadores_visibles
        from users.models import User

        mario = Entrenador.objects.create(nombre="Mario")
        u_jorge = User.objects.create_user(
            username="jorge", password="x", role=User.Role.ENTRENADOR)
        jorge = Entrenador.objects.create(nombre="Jorge", user=u_jorge)
        marcos = Jugador.objects.create(nombre="Marcos", entrenador_responsable=mario)
        Jugador.objects.create(nombre="Otro", entrenador_responsable=mario)
        self.assertFalse(jugadores_visibles(u_jorge).exists())

        marcos.cogestores.add(jorge)
        self.assertEqual(list(jugadores_visibles(u_jorge)), [marcos])
        self.assertTrue(jorge.puede_gestionar(marcos))
        api = APIClient()
        api.force_authenticate(u_jorge)
        filas = api.get("/api/jugadores/").json()
        filas = filas.get("results", filas)
        self.assertEqual([(f["nombre"], f["cogestores"]) for f in filas],
                         [("Marcos", [jorge.id])])


class GrupoDeGestionTests(TestCase):
    """Cada color de la tabla del club es un grupo de gestión (13/10/2026):
    el entrenador ve a los jugadores que gestionan los demás de su bloque
    (y les declara faltas), pero no los de otro color ni por estar en el
    bloque de todos."""

    def setUp(self):
        from rest_framework.test import APIClient

        from users.models import User

        u_blas = User.objects.create_user(
            username="blas", password="x", role=User.Role.ENTRENADOR)
        self.blas = Entrenador.objects.create(nombre="Blas", user=u_blas)
        javi = Entrenador.objects.create(nombre="Javi")
        mario = Entrenador.objects.create(nombre="Mario")
        nacho = Entrenador.objects.create(nombre="Nacho")
        amarillo = Coach.objects.create(nombre="Dani", color="amarillo")
        amarillo.entrenadores.set([self.blas, javi])
        Coach.objects.create(nombre="Pablo", color="turquesa").entrenadores.set([mario])
        # El bloque de Sergio abarca a todos y no tiene color.
        Coach.objects.create(nombre="Sergio").entrenadores.set(
            [self.blas, javi, mario, nacho])

        self.suyo = Jugador.objects.create(nombre="Toprak", entrenador_responsable=self.blas)
        self.de_javi = Jugador.objects.create(nombre="Yanaki", entrenador_responsable=javi)
        self.cogestionado = Jugador.objects.create(nombre="Lucca", entrenador_responsable=nacho)
        self.cogestionado.cogestores.add(javi)
        self.de_mario = Jugador.objects.create(nombre="Marcos", entrenador_responsable=mario)
        self.de_nacho = Jugador.objects.create(nombre="Arrow", entrenador_responsable=nacho)
        self.api = APIClient()
        self.api.force_authenticate(u_blas)

    def test_ve_a_los_de_su_color_y_no_a_los_demas(self):
        from academy.scope import jugadores_visibles

        ids = set(jugadores_visibles(self.blas.user).values_list("id", flat=True))
        self.assertEqual(ids, {self.suyo.id, self.de_javi.id, self.cogestionado.id})
        self.assertTrue(self.blas.puede_gestionar(self.de_javi))
        self.assertFalse(self.blas.puede_gestionar(self.de_mario))

    def test_abre_al_de_un_companero_pero_no_al_de_otro_color(self):
        self.assertEqual(self.api.get(f"/api/jugadores/{self.de_javi.id}/").status_code, 200)
        self.assertEqual(self.api.get(f"/api/jugadores/{self.de_mario.id}/").status_code, 404)

    def test_sin_color_solo_los_suyos(self):
        from academy.scope import jugadores_visibles

        Coach.objects.update(color="")
        self.assertEqual(list(jugadores_visibles(self.blas.user)), [self.suyo])


class GruposPorColoresTests(TestCase):
    """La pestaña Grupos enseña los grupos de gestión primero y con su color,
    cada entrenador en el suyo aunque esté también en el bloque de todos, y a
    quien comparte la gestión con los alumnos en su columna."""

    def setUp(self):
        from rest_framework.test import APIClient

        from users.models import User

        self.mario = Entrenador.objects.create(nombre="Mario")
        self.jorge = Entrenador.objects.create(nombre="Jorge I")
        self.salva = Entrenador.objects.create(nombre="Salva")
        self.turquesa = Coach.objects.create(nombre="Pablo", color="turquesa")
        self.turquesa.entrenadores.set([self.mario, self.jorge, self.salva])
        # «Ivan» va antes que «Pablo»: sin color, ahí acababan todos.
        self.todos = Coach.objects.create(nombre="Ivan")
        self.todos.entrenadores.set([self.mario, self.jorge, self.salva])
        self.marcos = Jugador.objects.create(nombre="Marcos", entrenador_responsable=self.mario)
        self.marcos.cogestores.add(self.jorge)
        direccion = User.objects.create_user(
            username="dir", password="x", role=User.Role.SUPERADMIN)
        self.api = APIClient()
        self.api.force_authenticate(direccion)

    def _grupos(self):
        return self.api.get("/api/grupos/").json()["bloques"]

    def test_el_grupo_de_color_va_primero_con_sus_entrenadores(self):
        bloques = [b for b in self._grupos() if b["coach"]]
        self.assertEqual((bloques[0]["coach"]["nombre"], bloques[0]["coach"]["color"]),
                         ("Pablo", "turquesa"))
        columnas = {g["entrenador"]["nombre"]: g["jugadores"] for g in bloques[0]["grupos"]}
        self.assertEqual(set(columnas), {"Mario", "Jorge I", "Salva"})
        ivan = next(b for b in bloques if b["coach"]["nombre"] == "Ivan")
        self.assertEqual(ivan["grupos"], [])
        self.assertEqual([(j["nombre"], j["con"]) for j in columnas["Jorge I"]],
                         [("Marcos", ["Mario"])])
        self.assertEqual([(j["nombre"], j["con"]) for j in columnas["Mario"]],
                         [("Marcos", ["Jorge I"])])

    def test_mover_a_otra_columna_quita_la_gestion_compartida(self):
        self.api.post("/api/grupos/mover/",
                      {"jugador": self.marcos.id, "entrenador": self.salva.id}, format="json")
        self.marcos.refresh_from_db()
        self.assertEqual(self.marcos.entrenador_responsable, self.salva)
        self.assertFalse(self.marcos.cogestores.exists())

    def test_cambiar_de_color_no_le_saca_del_bloque_de_todos(self):
        naranja = Coach.objects.create(nombre="Santi", color="naranja")
        self.api.post("/api/grupos/mover_entrenador/", {
            "entrenador": self.salva.id, "coach": naranja.id, "desde": self.turquesa.id,
        }, format="json")
        self.assertEqual(set(self.salva.coaches.all()), {naranja, self.todos})


class HeadCoachGestionaSuColorTests(TestCase):
    """El head coach de un color (Dani, Pablo, Santi) gestiona en Grupos a
    todos los alumnos de su color, y nada fuera de él; mover columnas entre
    bloques sigue siendo de dirección. Sin «también entrena» (13/10/2026)."""

    def setUp(self):
        from rest_framework.test import APIClient

        from users.models import User

        self.mario = Entrenador.objects.create(nombre="Mario")
        self.salva = Entrenador.objects.create(nombre="Salva")
        self.nacho = Entrenador.objects.create(nombre="Nacho")
        u_pablo = User.objects.create_user(
            username="pablo", password="x", role=User.Role.COACH)
        self.pablo = Coach.objects.create(nombre="Pablo", color="turquesa", user=u_pablo)
        self.pablo.entrenadores.set([self.mario, self.salva])
        Coach.objects.create(nombre="Santi", color="naranja").entrenadores.set([self.nacho])
        self.marcos = Jugador.objects.create(nombre="Marcos", entrenador_responsable=self.mario)
        self.arrow = Jugador.objects.create(nombre="Arrow", entrenador_responsable=self.nacho)
        self.alta = Jugador.objects.create(nombre="Nazim")
        # Arrow lo gestiona Nacho, pero entrena con Salva: Pablo lo ve, no es suyo.
        ResponsableJugador.objects.create(jugador=self.arrow, entrenador=self.salva,
                                          prioridad=1, activo=True)
        self.api = APIClient()
        self.api.force_authenticate(u_pablo)

    def _mover(self, jugador, entrenador):
        return self.api.post("/api/grupos/mover/", {
            "jugador": jugador.id, "entrenador": entrenador.id}, format="json")

    def test_mueve_y_coloca_a_los_de_su_color(self):
        self.assertEqual(self._mover(self.marcos, self.salva).status_code, 200)
        self.assertEqual(self._mover(self.alta, self.mario).status_code, 200)
        self.marcos.refresh_from_db(); self.alta.refresh_from_db()
        self.assertEqual(self.marcos.entrenador_responsable, self.salva)
        self.assertEqual(self.alta.entrenador_responsable, self.mario)
        r = self.api.post("/api/grupos/quitar/", {
            "jugador": self.marcos.id, "entrenador": self.salva.id}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_no_toca_lo_de_otro_color_ni_las_columnas(self):
        self.assertEqual(self._mover(self.arrow, self.salva).status_code, 403)
        self.assertEqual(self._mover(self.marcos, self.nacho).status_code, 403)
        r = self.api.post("/api/grupos/mover_entrenador/", {
            "entrenador": self.salva.id, "coach": ""}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_la_pestana_sin_tambien_ni_ajenos_en_sin_grupo(self):
        datos = self.api.get("/api/grupos/").json()
        self.assertTrue(datos["puede_editar"])
        self.assertFalse(datos["puede_mover_entrenadores"])
        sin_grupo = {j["nombre"] for j in datos["sin_grupo"]}
        self.assertIn("Nazim", sin_grupo)
        self.assertNotIn("Arrow", sin_grupo)
        for b in datos["bloques"]:
            for g in b["grupos"]:
                self.assertNotIn("tambien", g)


class GruposGestionNombresTests(SimpleTestCase):
    """El comando casa los nombres de la tabla del club con las fichas."""

    def test_casa_erratas_y_abreviaturas_y_prefiere_la_activa(self):
        from academy.management.commands.grupos_gestion import buscar

        fichas = [
            Jugador(pk=1, nombre="Maria Adrienko", activo=True),
            Jugador(pk=2, nombre="Javier Ballester Galarza", activo=True),
            Jugador(pk=3, nombre="Carla Guerrero Blanco", activo=False),
            Jugador(pk=4, nombre="Carla Guerrero", activo=True),
            Jugador(pk=5, nombre="Maria Ruiz Naranjo", activo=True),
        ]
        casa = lambda n: buscar(n, fichas)[0]  # noqa: E731
        self.assertEqual(casa("Maria Andrienko").pk, 1)
        self.assertEqual(casa("Javi Ballester").pk, 2)
        self.assertEqual(casa("Carla Guerrero").pk, 4)
        self.assertEqual(casa("Maria Ruiz").pk, 5)
        self.assertIsNone(casa("Yagiz Yildiz 17"))


class FichaDeportivaCoachTests(TestCase):
    """El head coach completa lo deportivo de las altas nuevas (06/10/2026)."""

    def test_ve_el_alta_sin_gestion_y_le_pone_division_y_entrenador(self):
        from rest_framework.test import APIClient

        from academy.models import Coach
        from users.models import User

        u = User.objects.create_user(username="sergio", password="x", role=User.Role.COACH)
        blas = Entrenador.objects.create(nombre="Blas")
        Coach.objects.create(nombre="Sergio", user=u).entrenadores.add(blas)
        ajeno = Entrenador.objects.create(nombre="Otro")
        Jugador.objects.create(nombre="De otro", entrenador_responsable=ajeno)
        nuevo = Jugador.objects.create(nombre="Nuevo")
        from academy.models import Division

        div, _ = Division.objects.get_or_create(nivel=4)
        api = APIClient()
        api.force_authenticate(u)
        filas = api.get("/api/jugadores/").json()
        filas = filas.get("results", filas)
        nombres = {f["nombre"] for f in filas}
        self.assertIn("Nuevo", nombres)
        self.assertNotIn("De otro", nombres)
        r = api.patch(f"/api/jugadores/{nuevo.id}/", {
            "division": div.id, "entrenador_responsable": blas.id,
            "cogestores": [ajeno.id], "vecindad": "SOLO",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        nuevo.refresh_from_db()
        self.assertEqual((nuevo.division_id, nuevo.entrenador_responsable_id, nuevo.vecindad),
                         (div.id, blas.id, "SOLO"))
        self.assertEqual(list(nuevo.cogestores.all()), [ajeno])


class GruposParaTodosTests(TestCase):
    """14/10/2026: la página de Grupos se ve igual para todos; el head coach
    no sale como columna vacía de su grupo, y las columnas se ordenan."""

    def setUp(self):
        from rest_framework.test import APIClient

        from users.models import User

        u_dani = User.objects.create_user(
            username="dani", password="x", role=User.Role.COACH)
        u_blas = User.objects.create_user(
            username="blas", password="x", role=User.Role.ENTRENADOR)
        self.dani_e = Entrenador.objects.create(nombre="Dani", user=u_dani)
        self.blas = Entrenador.objects.create(nombre="Blas", user=u_blas)
        self.javi = Entrenador.objects.create(nombre="Javi")
        self.nacho = Entrenador.objects.create(nombre="Nacho")
        self.amarillo = Coach.objects.create(nombre="Dani", color="amarillo", user=u_dani)
        self.amarillo.entrenadores.set([self.dani_e, self.blas, self.javi])
        self.naranja = Coach.objects.create(nombre="Santi", color="naranja")
        self.naranja.entrenadores.set([self.nacho])
        Jugador.objects.create(nombre="De Blas", entrenador_responsable=self.blas)
        Jugador.objects.create(nombre="De Nacho", entrenador_responsable=self.nacho)
        self.api = APIClient()
        self.u_dani, self.u_blas = u_dani, u_blas

    def _bloques(self, user):
        self.api.force_authenticate(user)
        r = self.api.get("/api/grupos/")
        self.assertEqual(r.status_code, 200)
        mios = {self.amarillo.id, self.naranja.id}
        return {b["coach"]["nombre"]: [g["entrenador"]["nombre"] for g in b["grupos"]]
                for b in r.json()["bloques"] if b["coach"] and b["coach"]["id"] in mios}

    def test_el_entrenador_ve_todos_los_grupos_y_sin_el_head_coach(self):
        bloques = self._bloques(self.u_blas)
        self.assertEqual(bloques, {"Dani": ["Blas", "Javi"], "Santi": ["Nacho"]})
        self.assertEqual(self._bloques(self.u_dani), bloques)

    def test_el_head_coach_ordena_su_grupo_y_no_otro(self):
        self.api.force_authenticate(self.u_dani)
        r = self.api.post("/api/grupos/ordenar/", {
            "coach": self.amarillo.id, "orden": [self.javi.id, self.blas.id]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._bloques(self.u_dani)["Dani"], ["Javi", "Blas"])
        r = self.api.post("/api/grupos/ordenar/", {
            "coach": self.naranja.id, "orden": [self.nacho.id]}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_el_entrenador_no_ordena(self):
        self.api.force_authenticate(self.u_blas)
        r = self.api.post("/api/grupos/ordenar/", {
            "coach": self.amarillo.id, "orden": [self.javi.id]}, format="json")
        self.assertEqual(r.status_code, 403)


class InvitadoComoJugadorTests(TestCase):
    """14/10/2026: el invitado es una persona con su ficha deportiva y todo lo
    que mira el motor; los días que viene son visitas, y dirección aprueba la
    ficha y cada visita. Volver a invitarle solo añade días."""

    def setUp(self):
        from rest_framework.test import APIClient

        from academy.models import Division
        from users.models import User

        u_ent = User.objects.create_user(
            username="ivan", password="x", role=User.Role.ENTRENADOR)
        u_otro = User.objects.create_user(
            username="blas", password="x", role=User.Role.ENTRENADOR)
        u_dir = User.objects.create_user(
            username="dir", password="x", role=User.Role.SUPERADMIN)
        self.ivan = Entrenador.objects.create(nombre="Ivan", user=u_ent)
        self.blas = Entrenador.objects.create(nombre="Blas", user=u_otro)
        self.otro = Entrenador.objects.create(nombre="Otro")
        self.d3, _ = Division.objects.get_or_create(nivel=3)
        self.amigo = Jugador.objects.create(nombre="Amigo")
        self.enemigo = Jugador.objects.create(nombre="Enemigo")
        self.ent, self.dir, self.ent2 = APIClient(), APIClient(), APIClient()
        self.ent.force_authenticate(u_ent)
        self.ent2.force_authenticate(u_otro)
        self.dir.force_authenticate(u_dir)

    def _proponer(self, **extra):
        datos = {
            "nombre": "Llorca", "division": self.d3.id, "edad": 15, "sexo": "CHICO",
            "fechas": {"2026-10-19": {"manana": "M1", "tarde": ""},
                       "2026-10-21": {"manana": "", "tarde": "T1"}},
            "vecindad": "ARRIBA", "superficie_pref": "TIERRA",
            "jugar_con": self.amigo.id, "pareja_estricta": False,
            "no_coincidir_con": [self.enemigo.id],
            "entrena_con": self.ivan.id, "no_entrena_con": [self.otro.id],
        }
        datos.update(extra)
        return self.ent.post("/api/invitados/", datos, format="json")

    def test_sin_dias_no_se_puede_proponer(self):
        self.assertEqual(self._proponer(fechas={}).status_code, 400)

    def test_al_aprobar_sale_un_jugador_con_todo(self):
        from academy.models import (
            Contrato, PreferenciaPareja, PreferenciaSuperficie, Rencilla,
            VetoEntrenador, VisitaInvitado,
        )

        r = self._proponer()
        self.assertEqual(r.status_code, 201, r.content)
        inv = r.json()
        self.assertEqual(len(inv["visitas"]), 2)
        r = self.dir.post(f"/api/invitados/{inv['id']}/aprobar/")
        self.assertEqual(r.status_code, 200, r.content)
        j = Jugador.objects.get(pk=r.json()["jugador_creado"])
        self.assertEqual((j.division, j.edad, j.sexo, j.vecindad, j.entrenador_responsable),
                         (self.d3, 15, "CHICO", "ARRIBA", self.ivan))
        self.assertEqual((str(j.fecha_alta), str(j.fecha_baja)), ("2026-10-19", "2026-10-21"))
        self.assertFalse(HorarioJugador.objects.filter(jugador=j).filter(
            Q(entrena_manana=True) | Q(entrena_tarde=True)).exists())
        # El miércoles por la tarde está cerrado y se descarta.
        v = VisitaInvitado.objects.get(invitado_id=inv["id"], fecha=date(2026, 10, 21))
        self.assertEqual((v.manana, v.tarde, v.estado), ("", None, "APROBADA"))
        self.assertTrue(PreferenciaSuperficie.objects.filter(jugador=j, superficie="TIERRA").exists())
        self.assertEqual(PreferenciaPareja.objects.get(jugador=j).tipo, "SOFT")
        self.assertTrue(Rencilla.objects.filter(jugador_a__in=[j, self.enemigo],
                                                jugador_b__in=[j, self.enemigo]).exists())
        self.assertEqual(Contrato.objects.get(jugador=j).entrenador, self.ivan)
        self.assertEqual(VetoEntrenador.objects.get(jugador=j).entrenador, self.otro)

    def test_volver_a_invitar_solo_anade_dias_y_hay_que_aprobarlos(self):
        from academy.models import VisitaInvitado

        inv = self._proponer().json()
        self.dir.post(f"/api/invitados/{inv['id']}/aprobar/")
        # Otro entrenador le invita en noviembre: la ficha no se toca.
        r = self.ent2.post(f"/api/invitados/{inv['id']}/dias/",
                           {"fechas": {"2026-11-16": {"manana": "M2"}}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        v = VisitaInvitado.objects.get(invitado_id=inv["id"], fecha=date(2026, 11, 16))
        self.assertEqual((v.estado, v.solicitante), ("PENDIENTE", self.blas))
        self.assertEqual(Invitado.objects.filter(nombre="Llorca").count(), 1)
        j = Jugador.objects.get(pk=Invitado.objects.get(pk=inv["id"]).jugador_creado_id)
        self.assertEqual(str(j.fecha_baja), "2026-10-21")
        self.dir.post(f"/api/visitas-invitado/{v.id}/aprobar/")
        j.refresh_from_db()
        self.assertEqual((str(j.fecha_alta), str(j.fecha_baja)), ("2026-10-19", "2026-11-16"))
        self.assertEqual(Jugador.objects.filter(nombre__startswith="Llorca").count(), 1)

    def test_el_calendario_lista_las_visitas_del_mes(self):
        self._proponer()
        r = self.ent2.get("/api/visitas-invitado/?desde=2026-10-01&hasta=2026-10-31")
        filas = r.json().get("results", r.json())
        self.assertEqual([(f["fecha"], f["invitado_nombre"], f["estado"]) for f in filas],
                         [("2026-10-19", "Llorca", "PENDIENTE"),
                          ("2026-10-21", "Llorca", "PENDIENTE")])

    def test_la_ficha_aprobada_solo_la_cambia_direccion_y_pasa_al_jugador(self):
        inv = self._proponer().json()
        self.assertEqual(self.ent.patch(f"/api/invitados/{inv['id']}/", {"edad": 16},
                                        format="json").status_code, 200)
        self.dir.post(f"/api/invitados/{inv['id']}/aprobar/")
        self.assertEqual(self.ent.patch(f"/api/invitados/{inv['id']}/", {"edad": 17},
                                        format="json").status_code, 403)
        self.assertEqual(self.dir.patch(f"/api/invitados/{inv['id']}/", {"edad": 17},
                                        format="json").status_code, 200)
        self.assertEqual(Jugador.objects.get(nombre__startswith="Llorca").edad, 17)

    def test_dani_e_ivan_lo_meten_ya_aprobado(self):
        """21/10/2026: si lo pone dirección, Dani o Iván (aunque sean coaches),
        el invitado y sus días quedan aprobados al momento."""
        from rest_framework.test import APIClient

        from academy.models import Aviso, VisitaInvitado
        from users.models import User

        u_dani = User.objects.create_user(
            username="daniel.gimeno", password="x", role=User.Role.COACH)
        dani = Entrenador.objects.create(nombre="Dani", user=u_dani)
        c = APIClient()
        c.force_authenticate(u_dani)
        self.assertIs(c.get("/api/auth/me/").json()["aprueba_invitados"], True)
        datos = {"nombre": "Chicote", "division": self.d3.id,
                 "fechas": {"2026-10-22": {"manana": "M1"}}}
        r = c.post("/api/invitados/", datos, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        inv = Invitado.objects.get(pk=r.json()["id"])
        self.assertEqual((inv.estado, inv.entrenador_solicitante), ("APROBADO", dani))
        self.assertIsNotNone(inv.jugador_creado_id)
        self.assertEqual(list(inv.visitas.values_list("estado", flat=True)), ["APROBADA"])
        self.assertFalse(Aviso.objects.filter(titulo__startswith="Invitado pendiente").exists())
        # Volver a invitarle: también directo.
        c.post(f"/api/invitados/{inv.id}/dias/",
               {"fechas": {"2026-10-26": {"manana": "M2"}}}, format="json")
        self.assertEqual(VisitaInvitado.objects.get(invitado=inv, fecha=date(2026, 10, 26)).estado,
                         "APROBADA")
        # Y aprueba lo que proponen los demás.
        otro = self._proponer().json()
        self.assertEqual(c.post(f"/api/invitados/{otro['id']}/aprobar/").status_code, 200)
        # Un entrenador cualquiera sigue necesitando aprobación.
        self.assertEqual(Invitado.objects.get(pk=otro["id"]).estado, "APROBADO")
        r = self.ent2.post("/api/invitados/", {**datos, "nombre": "Otro"}, format="json")
        self.assertEqual(Invitado.objects.get(pk=r.json()["id"]).estado, "PENDIENTE")


class InvitadoEnElMotorTests(TestCase):
    """El invitado entra en el cuadrante los días de sus visitas aprobadas, y
    en ningún otro."""

    def test_viene_solo_el_dia_aprobado(self):
        from academy.models import Division, VisitaInvitado

        Jugador.objects.update(activo=False)
        Entrenador.objects.update(activo=False)
        Pista.objects.update(activa=False)
        sede = Sede.objects.create(nombre="Prueba invitado")
        Pista.objects.create(sede=sede, numero=1, superficie="TIERRA")
        ent = Entrenador.objects.create(nombre="Uno")
        d5, _ = Division.objects.get_or_create(nivel=5)
        m1 = Turno.objects.get(codigo="M1")
        local = Jugador.objects.create(nombre="Local", activo=True, division=d5)
        for d in range(5):
            HorarioJugador.objects.create(jugador=local, dia=d, entrena_manana=True,
                                          entrena_tarde=False, turno_manana=m1)
        kira = Jugador.objects.create(nombre="Kira (invitado)", activo=True, division=d5,
                                      fecha_alta=LUNES, fecha_baja=LUNES + timedelta(days=2))
        for d in range(6):
            HorarioJugador.objects.create(jugador=kira, dia=d, entrena_manana=False,
                                          entrena_tarde=False)
        inv = Invitado.objects.create(nombre="Kira", entrenador_solicitante=ent,
                                      estado="APROBADO", jugador_creado=kira)
        VisitaInvitado.objects.create(invitado=inv, fecha=LUNES + timedelta(days=2),
                                      manana="M1", estado="APROBADA")
        VisitaInvitado.objects.create(invitado=inv, fecha=LUNES + timedelta(days=1),
                                      manana="M1", estado="PENDIENTE")
        semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)
        generate(semana, dias=[0, 1, 2], bloques=["MANANA"])
        dias = set(Asignacion.objects.filter(semana=semana, jugador=kira).values_list("dia", flat=True))
        self.assertEqual(dias, {2})


class RellenoForzadoTests(TestCase):
    """14/10/2026 (Iván, Nik con Chimo): si queda un hueco en una pista ya
    abierta y alguien en el banquillo, se le mete aunque rompa reglas base, y
    la asignación queda marcada como forzada. Una rencilla no se rompe: deja
    un aviso en el banquillo."""

    def setUp(self):
        from academy.models import Division
        from scheduling.models import ConfiguracionMotor

        cfg = ConfiguracionMotor.objects.first() or ConfiguracionMotor.objects.create()
        cfg.time_limit_s = 2
        cfg.modo_satelites = "NUNCA"
        cfg.save()
        Jugador.objects.update(activo=False)
        Entrenador.objects.update(activo=False)
        Pista.objects.update(activa=False)
        self.m1 = Turno.objects.get(codigo="M1")
        sede = Sede.objects.create(nombre="Prueba relleno")
        self.pista = Pista.objects.create(sede=sede, numero=1, superficie="TIERRA")
        self.pablo = Entrenador.objects.create(nombre="Pablo")
        self.semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)

        def jugador(nombre, nivel, sexo, edad):
            d, _ = Division.objects.get_or_create(nivel=nivel)
            j = Jugador.objects.create(nombre=nombre, activo=True, division=d,
                                       sexo=sexo, edad=edad)
            HorarioJugador.objects.create(jugador=j, dia=0, entrena_manana=True,
                                          entrena_tarde=False, turno_manana=self.m1)
            return j

        self.chimo = jugador("Chimo", 3, "CHICO", 16)
        self.nik = jugador("Nik", 9, "CHICA", 13)
        # Chimo, puesto a mano solo con Pablo: la única pista abierta.
        Asignacion.objects.create(semana=self.semana, dia=0, turno=self.m1,
                                  pista=self.pista, jugador=self.chimo,
                                  entrenador=self.pablo, manual=True)

    def test_nik_entra_con_chimo_marcada_como_forzada(self):
        rep = generate(self.semana, dias=[0], bloques=["MANANA"])
        a = Asignacion.objects.get(semana=self.semana, dia=0, jugador=self.nik)
        self.assertEqual((a.pista, a.entrenador, a.forzada), (self.pista, self.pablo, True))
        self.assertIn("división D3–D9", a.motivo_forzado)
        self.assertIn("chico/chica", a.motivo_forzado)
        self.assertEqual(len(rep["forzadas"]), 1)
        # Lo de Chimo, puesto a mano, sigue igual.
        self.assertTrue(Asignacion.objects.get(jugador=self.chimo).manual)

    def test_una_rencilla_no_se_rompe_y_queda_aviso(self):
        from academy.models import Rencilla
        from scheduling.models import AvisoBanquillo

        Rencilla.objects.create(jugador_a=self.chimo, jugador_b=self.nik)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertFalse(Asignacion.objects.filter(jugador=self.nik).exists())
        aviso = AvisoBanquillo.objects.get(jugador=self.nik)
        self.assertIn("rencilla", aviso.motivo)

    def test_sin_nada_a_mano_el_motor_fuerza_y_lo_marca(self):
        # Una sola pista para los dos: sin forzar, uno se queda fuera.
        Asignacion.objects.filter(jugador=self.chimo).delete()
        rep = generate(self.semana, dias=[0], bloques=["MANANA"])
        filas = Asignacion.objects.filter(semana=self.semana, dia=0)
        self.assertEqual(set(filas.values_list("jugador", flat=True)), {self.chimo.id, self.nik.id})
        self.assertTrue(all(a.forzada for a in filas))
        self.assertIn("división D3–D9", filas[0].motivo_forzado)
        self.assertTrue(rep["forzadas"])

    def test_moverla_a_mano_quita_la_marca(self):
        generate(self.semana, dias=[0], bloques=["MANANA"])
        a = Asignacion.objects.get(jugador=self.nik)
        a.manual = True
        a.save()
        a.refresh_from_db()
        self.assertEqual((a.forzada, a.motivo_forzado), (False, ""))


class GruposPorDivisionTests(TestCase):
    """21/10/2026: segunda pestaña de Grupos, los alumnos por división."""

    def test_alumnos_por_division_sin_los_que_ya_no_entrenan(self):
        from datetime import timedelta

        from rest_framework.test import APIClient

        from academy.models import Division
        from users.models import User

        d1, _ = Division.objects.get_or_create(nivel=1)
        d2, _ = Division.objects.get_or_create(nivel=2)
        ent = Entrenador.objects.create(nombre="Blas")
        Jugador.objects.create(nombre="Bea", division=d2, entrenador_responsable=ent)
        Jugador.objects.create(nombre="Ana", division=d2)
        Jugador.objects.create(nombre="Sin div")
        Jugador.objects.create(nombre="Baja", division=d1,
                               fecha_baja=date.today() - timedelta(days=1))
        Jugador.objects.create(nombre="Inactivo", division=d1, activo=False)
        c = APIClient()
        c.force_authenticate(User.objects.create_user(
            username="e", password="x", role=User.Role.ENTRENADOR))
        r = c.get("/api/grupos/divisiones/")
        self.assertEqual(r.status_code, 200, r.content)
        # Las migraciones ya traen alumnos: se miran solo los de esta prueba.
        mios = {"Ana", "Bea", "Sin div", "Baja", "Inactivo"}
        filas = {d["nivel"]: [j for j in d["jugadores"] if j["nombre"] in mios]
                 for d in r.json()["divisiones"]}
        self.assertEqual(filas[1], [])
        self.assertEqual([(j["nombre"], j["responsable"]) for j in filas[2]],
                         [("Ana", None), ("Bea", "Blas")])
        self.assertEqual([j["nombre"] for j in filas[None]], ["Sin div"])


class HorarioHabitualSoloDireccionTests(TestCase):
    """«Sigue apareciendo en el perfil de los entrenadores la posibilidad de
    que modifiquen su horario habitual» (30/10/2026): lo fija dirección; el
    entrenador y su head coach lo ven, pero no lo cambian."""

    def setUp(self):
        from users.models import User

        self.usuario_victor = User.objects.create_user(
            username="victor", password="x", role=User.Role.ENTRENADOR)
        self.victor = Entrenador.objects.create(nombre="Víctor", user=self.usuario_victor)
        self.usuario_dani = User.objects.create_user(
            username="dani", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Dani", user=self.usuario_dani).entrenadores.add(self.victor)
        self.usuario_ivan = User.objects.create_user(
            username="ivan", password="x", role=User.Role.SUPERADMIN)

    def _api(self, usuario):
        from rest_framework.test import APIClient

        api = APIClient()
        api.force_authenticate(usuario)
        return api

    def _guardar(self, usuario):
        return self._api(usuario).patch(
            f"/api/mi-agenda/semana/?entrenador={self.victor.id}",
            {"semana": [{"dia": 1, "manana": True, "tarde": False}]}, format="json")

    def test_el_entrenador_lo_ve_pero_no_lo_cambia(self):
        r = self._api(self.usuario_victor).get("/api/mi-agenda/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["puede_editar_semana"])
        self.assertEqual(len(r.json()["semana"]), 6)
        self.assertEqual(self._guardar(self.usuario_victor).status_code, 403)
        self.assertFalse(self.victor.horario.exists())

    def test_el_head_coach_tampoco(self):
        r = self._api(self.usuario_dani).get(f"/api/mi-agenda/?entrenador={self.victor.id}")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["puede_editar_semana"])
        self.assertEqual(self._guardar(self.usuario_dani).status_code, 403)

    def test_direccion_lo_fija(self):
        r = self._api(self.usuario_ivan).get(f"/api/mi-agenda/?entrenador={self.victor.id}")
        self.assertTrue(r.json()["puede_editar_semana"])
        r = self._guardar(self.usuario_ivan)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["semana"][1]["tarde"], False)
        h = self.victor.horario.get(dia=1)
        self.assertEqual((h.manana, h.tarde), (True, False))

    def test_sus_faltas_las_sigue_marcando_el(self):
        r = self._api(self.usuario_victor).post("/api/mi-agenda/ausencias/", {
            "fecha_inicio": "2026-11-03", "fecha_fin": "2026-11-03", "motivo": "Médico",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(VacacionesEntrenador.objects.filter(entrenador=self.victor).count(), 1)


class HorarioHabitualJugadorTests(TestCase):
    """«Los entrenadores tampoco deben poder cambiar el horario habitual de un
    jugador. Solo declaran faltas o viene además» (30/10/2026). Su head coach
    y dirección, sí."""

    def setUp(self):
        from users.models import User

        self.u_victor = User.objects.create_user(
            username="victor", password="x", role=User.Role.ENTRENADOR)
        victor = Entrenador.objects.create(nombre="Víctor", user=self.u_victor)
        self.u_dani = User.objects.create_user(
            username="dani", password="x", role=User.Role.COACH)
        Coach.objects.create(nombre="Dani", user=self.u_dani).entrenadores.add(victor)
        self.u_ivan = User.objects.create_user(
            username="ivan", password="x", role=User.Role.SUPERADMIN)
        self.carlos = Jugador.objects.create(nombre="Carlos", entrenador_responsable=victor)
        self.m1 = Turno.objects.get(codigo="M1")

    def _api(self, usuario):
        from rest_framework.test import APIClient

        api = APIClient()
        api.force_authenticate(usuario)
        return api

    def test_el_entrenador_ni_la_franja_ni_los_dias(self):
        api = self._api(self.u_victor)
        url = f"/api/jugadores/{self.carlos.id}/"
        self.assertEqual(api.get(url).status_code, 200)
        r = api.patch(url, {"turno_manana": self.m1.id}, format="json")
        self.assertEqual(r.status_code, 403, r.content)
        r = api.patch(url, {"horario": [{"dia": 1, "entrena_tarde": False}]}, format="json")
        self.assertEqual(r.status_code, 403, r.content)
        self.carlos.refresh_from_db()
        self.assertIsNone(self.carlos.turno_manana_id)
        self.assertFalse(HorarioJugador.objects.filter(jugador=self.carlos).exists())

    def test_el_head_coach_y_direccion_si(self):
        url = f"/api/jugadores/{self.carlos.id}/"
        r = self._api(self.u_dani).patch(url, {"turno_manana": self.m1.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        r = self._api(self.u_ivan).patch(url, {"turno_manana": None}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_el_entrenador_sigue_apuntando_viene_ademas(self):
        r = self._api(self.u_victor).post(
            f"/api/jugadores/{self.carlos.id}/extra/",
            {"fecha": "2026-11-03", "turno": "M1"}, format="json")
        self.assertNotEqual(r.status_code, 403, r.content)
