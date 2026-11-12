"""Los comandos de carga escriben en el calendario del entrenador y en las faltas
por fechas, no en el interruptor «Disponible esta semana» ni en el parte
semanal (orden de la aplicación, 10/11/2026)."""
import os
import tempfile
from datetime import date, time, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from academy.calendario import (
    MOTIVO_CARGA, MOTIVO_SEMANA, ausentes_todo_el_dia, marcar_no_disponible,
    solo_disponible, volver_disponible,
)
from academy.management.commands.cargar_excel_datos import (
    MOTIVO_NO_APARECE, NOTA_AUSENTE,
)
from academy.management.commands.sync_semana_excel import lunes_de
from academy.models import Entrenador, Jugador, Turno, VacacionesEntrenador
from scheduling.models import AusenciaJugador, Disponibilidad, DisponibilidadEntrenador

HOY = date.today()
LUNES = date(2026, 9, 14)


def _turno(codigo, ini, fin):
    bloque = "MANANA" if codigo.startswith("M") else "TARDE"
    return Turno(codigo=codigo, bloque=bloque, hora_inicio=ini, hora_fin=fin)


class CalendarioTests(TestCase):
    def setUp(self):
        self.e = Entrenador.objects.create(nombre="Zacarias Prueba", activo=True)

    def _suyas(self, motivo=MOTIVO_CARGA):
        return VacacionesEntrenador.objects.filter(entrenador=self.e, motivo=motivo)

    def test_no_disponible_indefinido_es_un_anio_y_no_se_duplica(self):
        self.assertEqual(marcar_no_disponible(self.e), "creada")
        v = self._suyas().get()
        self.assertEqual((v.fecha_inicio, v.fecha_fin), (HOY, HOY + timedelta(days=365)))
        self.assertEqual(v.ambito, "DIA")
        self.assertIsNone(v.hora_desde)
        self.assertEqual(marcar_no_disponible(self.e), "ya estaba")
        self.assertEqual(self._suyas().count(), 1)

    def test_si_pisa_o_toca_la_que_hay_la_alarga(self):
        marcar_no_disponible(self.e, LUNES, LUNES + timedelta(days=5))
        self.assertEqual(
            marcar_no_disponible(self.e, LUNES + timedelta(days=6), LUNES + timedelta(days=12)),
            "ampliada")
        v = self._suyas().get()
        self.assertEqual((v.fecha_inicio, v.fecha_fin), (LUNES, LUNES + timedelta(days=12)))

    def test_volver_disponible_cierra_lo_empezado_y_borra_lo_futuro(self):
        empezada = VacacionesEntrenador.objects.create(
            entrenador=self.e, fecha_inicio=HOY - timedelta(days=10),
            fecha_fin=HOY + timedelta(days=100), motivo=MOTIVO_CARGA)
        VacacionesEntrenador.objects.create(
            entrenador=self.e, fecha_inicio=HOY + timedelta(days=200),
            fecha_fin=HOY + timedelta(days=210), motivo=MOTIVO_CARGA)
        pasada = VacacionesEntrenador.objects.create(
            entrenador=self.e, fecha_inicio=HOY - timedelta(days=40),
            fecha_fin=HOY - timedelta(days=30), motivo=MOTIVO_CARGA)
        a_mano = VacacionesEntrenador.objects.create(
            entrenador=self.e, fecha_inicio=HOY, fecha_fin=HOY + timedelta(days=7),
            motivo="Vacaciones")

        self.assertEqual(volver_disponible(self.e), 2)

        empezada.refresh_from_db()
        self.assertEqual(empezada.fecha_fin, HOY - timedelta(days=1))
        self.assertEqual(
            set(self._suyas().values_list("pk", flat=True)), {empezada.pk, pasada.pk})
        a_mano.refresh_from_db()
        self.assertEqual(a_mano.fecha_fin, HOY + timedelta(days=7))

    def test_volver_disponible_una_semana_parte_la_que_sigue(self):
        marcar_no_disponible(self.e, LUNES - timedelta(days=7), LUNES + timedelta(days=12),
                             motivo=MOTIVO_SEMANA)
        volver_disponible(self.e, LUNES, LUNES + timedelta(days=5), motivo=MOTIVO_SEMANA)
        trozos = list(self._suyas(MOTIVO_SEMANA).order_by("fecha_inicio")
                      .values_list("fecha_inicio", "fecha_fin"))
        self.assertEqual(trozos, [
            (LUNES - timedelta(days=7), LUNES - timedelta(days=1)),
            (LUNES + timedelta(days=6), LUNES + timedelta(days=12)),
        ])

    def test_solo_disponible_por_la_manana(self):
        nuevas = solo_disponible(self.e, LUNES, time(8, 30), time(12, 30), "Solo mañana")
        self.assertEqual(
            sorted((v.hora_desde, v.hora_hasta) for v in nuevas),
            [(time(0, 0), time(8, 30)), (time(12, 30), time(23, 59))])
        m1, m2 = _turno("M1", time(8, 30), time(10, 0)), _turno("M2", time(10, 0), time(12, 30))
        t1 = _turno("T1", time(14, 15), time(15, 30))
        fuera = lambda t: any(v.afecta_turno(t, LUNES) for v in nuevas)  # noqa: E731
        self.assertFalse(fuera(m1))
        self.assertFalse(fuera(m2))
        self.assertTrue(fuera(t1))
        # Un rato no es «no está en todo el día».
        self.assertEqual(ausentes_todo_el_dia(LUNES, [self.e]), set())

    def test_ausente_todo_el_dia(self):
        marcar_no_disponible(self.e, LUNES, LUNES, motivo="Torneo")
        self.assertEqual(ausentes_todo_el_dia(LUNES, [self.e]), {self.e.id})
        self.assertEqual(ausentes_todo_el_dia(LUNES + timedelta(days=1), [self.e]), set())


class LunesDeLaCabeceraTests(SimpleTestCase):
    def test_cabeceras(self):
        self.assertEqual(lunes_de("AGOSTO 24 AL 30", 2026), date(2026, 8, 24))
        self.assertEqual(lunes_de("Septiembre 16 al 20", 2026), date(2026, 9, 14))
        self.assertIsNone(lunes_de("SEMANA 3", 2026))


class SyncSemanaExcelTests(TestCase):
    """Quien no sale en el roster, «No sale esta semana» solo de lunes a
    sábado de esa semana; si en otra pasada sale, se le quita."""

    def setUp(self):
        import openpyxl

        self.sale = Entrenador.objects.create(nombre="ZACARIAS TESTER", activo=True)
        self.no_sale = Entrenador.objects.create(nombre="YOLANDA TESTER", activo=True)
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = os.path.join(self.dir.name, "2026.xlsx")
        self.wb = openpyxl.Workbook()
        self.ws = self.wb.active
        self.ws.title = "AGOSTO"
        self.ws.cell(row=14, column=1, value="AGOSTO 24 AL 30")
        self.ws.cell(row=16, column=4, value="ZACARIAS TESTER")
        self.wb.save(self.ruta)

    def tearDown(self):
        self.dir.cleanup()

    def _sync(self, *extra):
        call_command("sync_semana_excel", "--file", self.ruta, "--semana", "AGOSTO 24 AL 30",
                     "--anio", "2026", *extra, stdout=StringIO())

    def _semana(self, e):
        return list(VacacionesEntrenador.objects.filter(entrenador=e, motivo=MOTIVO_SEMANA)
                    .values_list("fecha_inicio", "fecha_fin"))

    def test_solo_esa_semana_y_se_deshace(self):
        self._sync("--dry-run")
        self.assertEqual(self._semana(self.no_sale), [])

        self._sync()
        self._sync()
        self.assertEqual(self._semana(self.no_sale), [(date(2026, 8, 24), date(2026, 8, 29))])
        self.assertEqual(self._semana(self.sale), [])
        self.no_sale.refresh_from_db()
        self.assertTrue(self.no_sale.disponible_semana)

        self.ws.cell(row=17, column=4, value="YOLANDA TESTER")
        self.wb.save(self.ruta)
        self._sync()
        self.assertEqual(self._semana(self.no_sale), [])


class AplicarGruposCalendarioTests(TestCase):
    @staticmethod
    def _entrenador(nombre):
        e = Entrenador.objects.filter(nombre__iexact=nombre).order_by("id").last()
        return e or Entrenador.objects.create(nombre=nombre, activo=True)

    def test_fuera_de_servicio_va_al_calendario_sin_duplicar_y_se_puede_deshacer(self):
        # Los de la base de pruebas (si no estuvieran, se crean).
        jorge = self._entrenador("JORGE IBAÑEZ")
        mario = self._entrenador("MARIO MUNIESA")
        # Una carga anterior le dejó «no disponible»; a mano, unas vacaciones.
        marcar_no_disponible(mario, HOY + timedelta(days=3))
        VacacionesEntrenador.objects.create(
            entrenador=mario, fecha_inicio=HOY, fecha_fin=HOY + timedelta(days=5),
            motivo="Vacaciones")

        call_command("aplicar_grupos", "--dry-run", stdout=StringIO())
        self.assertFalse(VacacionesEntrenador.objects.filter(
            entrenador=jorge, motivo=MOTIVO_CARGA).exists())
        self.assertEqual(VacacionesEntrenador.objects.filter(entrenador=mario).count(), 2)

        call_command("aplicar_grupos", stdout=StringIO())
        call_command("aplicar_grupos", stdout=StringIO())

        jorge.refresh_from_db()
        self.assertTrue(jorge.disponible_semana)
        self.assertEqual(VacacionesEntrenador.objects.filter(
            entrenador=jorge, motivo=MOTIVO_CARGA).count(), 1)
        # Mario está en servicio: fuera lo de la carga, se quedan sus vacaciones.
        self.assertEqual(
            list(VacacionesEntrenador.objects.filter(entrenador=mario)
                 .values_list("motivo", flat=True)),
            ["Vacaciones"])


class CargarExcelDatosTests(TestCase):
    """Un caso mínimo de la plantilla del club y de la semana real."""

    def setUp(self):
        import openpyxl

        self.jug = Jugador.objects.create(nombre="Prueba Carga", activo=True)
        # Un nombre que no esté en la base de pruebas, para que no haya dudas.
        self.coach = Entrenador.objects.create(nombre="Zacarias Prueba", activo=True)
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = os.path.join(self.dir.name, "datos.xlsx")
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        ws = wb.create_sheet("JUGADORES")
        ws.cell(row=7, column=1, value="Prueba Carga")
        ws.cell(row=7, column=22, value="M1")          # lunes por la mañana
        self.ent = wb.create_sheet("ENTRENADORES")
        self.ent.cell(row=7, column=1, value="Zacarias Prueba")
        self.ent.cell(row=7, column=7, value="no")     # disponible: no
        cuadrante = wb.create_sheet("SEPTIEMBRE")
        cuadrante.cell(row=317, column=1, value="ZACARIAS PRUEBA")   # lunes, M1
        wb.save(self.ruta)
        self.wb = wb

    def tearDown(self):
        self.dir.cleanup()

    def _cargar(self, *extra):
        call_command("cargar_excel_datos", "--datos", self.ruta, *extra, stdout=StringIO())

    def test_disponible_no_va_a_su_calendario(self):
        self._cargar("--dry-run")
        self.assertFalse(VacacionesEntrenador.objects.filter(entrenador=self.coach).exists())

        self._cargar()
        self._cargar()
        self.coach.refresh_from_db()
        self.assertTrue(self.coach.disponible_semana)
        v = VacacionesEntrenador.objects.get(entrenador=self.coach, motivo=MOTIVO_CARGA)
        self.assertEqual((v.fecha_inicio, v.fecha_fin), (HOY, HOY + timedelta(days=365)))

        # Vuelve a estar disponible: se le quita lo de la carga.
        self.ent.cell(row=7, column=7, value="sí")
        self.wb.save(self.ruta)
        self._cargar()
        self.assertFalse(VacacionesEntrenador.objects.filter(
            entrenador=self.coach, motivo=MOTIVO_CARGA).exists())

    def test_semana_real_en_el_registro_nuevo_y_rehacible(self):
        self.ent.cell(row=7, column=7, value=None)
        self.wb.save(self.ruta)
        # Una falta apuntada en la app esa semana: la carga no la toca.
        a_mano = AusenciaJugador.objects.create(
            jugador=self.jug, fecha_inicio=LUNES + timedelta(days=2),
            fecha_fin=LUNES + timedelta(days=2), nota="Dentista")
        args = ("--cuadrante", self.ruta, "--semana", LUNES.isoformat())
        self._cargar(*args)
        self._cargar(*args)

        # No vino el lunes por la mañana: una falta ese día, en las de fechas.
        falta = AusenciaJugador.objects.get(jugador=self.jug, nota=NOTA_AUSENTE)
        self.assertEqual((falta.fecha_inicio, falta.fecha_fin, falta.ambito),
                         (LUNES, LUNES, "MANANA"))
        self.assertTrue(AusenciaJugador.objects.filter(pk=a_mano.pk).exists())
        self.assertFalse(Disponibilidad.objects.exclude(estado="EXTRA").exists())
        self.assertFalse(DisponibilidadEntrenador.objects.exists())

        # El entrenador: el lunes solo en M1 (fuera antes de las 8:30 y desde las
        # 10:00); de martes a sábado no aparece, el día entero.
        lunes = VacacionesEntrenador.objects.filter(entrenador=self.coach, fecha_inicio=LUNES)
        self.assertEqual(
            sorted(lunes.values_list("hora_desde", "hora_hasta")),
            [(time(0, 0), time(8, 30)), (time(10, 0), time(23, 59))])
        resto = VacacionesEntrenador.objects.filter(
            entrenador=self.coach, motivo=MOTIVO_NO_APARECE)
        self.assertEqual(
            sorted(resto.values_list("fecha_inicio", flat=True)),
            [LUNES + timedelta(days=i) for i in range(1, 6)])
        self.assertTrue(all(v.hora_desde is None for v in resto))
