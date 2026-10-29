"""21/10/2026: nadie se queda en el banquillo por la mañana. Primero el relleno
forzado en las pistas abiertas del Resort; lo que quede abre pista en los
satélites (Sta. Bárbara, luego Bétera y Mas Camarena), sin entrenador y con
aviso. Por la tarde nunca."""
from datetime import date

from django.test import TestCase

from academy.models import (
    Division, Entrenador, HorarioJugador, Jugador, Pista, Rencilla, Sede, Turno,
)
from engine.service import generate
from scheduling.models import Asignacion, AvisoBanquillo, ConfiguracionMotor, Semana

LUNES = date(2026, 9, 14)


class SatelitesDeRescateTests(TestCase):
    def setUp(self):
        self.cfg = ConfiguracionMotor.objects.first() or ConfiguracionMotor.objects.create()
        self.cfg.time_limit_s = 2
        self.cfg.modo_satelites = ConfiguracionMotor.ModoSatelites.RESCATE
        self.cfg.save()
        Jugador.objects.update(activo=False)
        Entrenador.objects.update(activo=False)
        Pista.objects.update(activa=False)
        Sede.objects.update(activa=False)
        self.m1 = Turno.objects.get(codigo="M1")
        self.t1 = Turno.objects.get(codigo="T1")
        resort = Sede.objects.create(nombre="Resort prueba", densidad_default=2, densidad_max=2)
        self.resort = Pista.objects.create(sede=resort, numero=1, superficie="TIERRA")
        sb = self.satelite("Sta. Bárbara", 1)
        self.sb = [self.pista(sb, n, "TIERRA") for n in (1, 2)]
        self.betera = self.pista(self.satelite("Poli Bétera", 2), 1, "RESINA")
        self.pablo = Entrenador.objects.create(nombre="Pablo")
        self.semana, _ = Semana.objects.get_or_create(fecha_inicio=LUNES)

    def satelite(self, nombre, orden):
        sede, _ = Sede.objects.update_or_create(nombre=nombre, defaults=dict(
            es_satelite=True, orden_desbordamiento=orden, activa=True,
            densidad_default=2, densidad_max=4))
        return sede

    def pista(self, sede, numero, superficie):
        p, _ = Pista.objects.update_or_create(
            sede=sede, numero=numero, defaults=dict(superficie=superficie, activa=True))
        return p

    def jugador(self, nombre, nivel, sexo="CHICO", edad=20, tarde=False):
        d, _ = Division.objects.get_or_create(nivel=nivel)
        j = Jugador.objects.create(nombre=nombre, activo=True, division=d, sexo=sexo, edad=edad)
        HorarioJugador.objects.create(
            jugador=j, dia=0, entrena_manana=not tarde, entrena_tarde=tarde,
            turno_manana=None if tarde else self.m1, turno_tarde=self.t1 if tarde else None)
        return j

    def resort_lleno(self, turno=None):
        """La pista del Resort con dos puestos a mano: no queda hueco."""
        turno = turno or self.m1
        for n in ("A", "B"):
            Asignacion.objects.create(
                semana=self.semana, dia=0, turno=turno, pista=self.resort,
                jugador=self.jugador(f"Fijo {n} {turno.codigo}", 4,
                                     tarde=turno != self.m1),
                entrenador=self.pablo, manual=True)

    def de(self, j):
        return Asignacion.objects.filter(semana=self.semana, dia=0, jugador=j).first()

    def test_quien_no_cabe_va_a_santa_barbara_sin_entrenador_y_con_aviso(self):
        self.resort_lleno()
        nik = self.jugador("Nik", 9)
        rep = generate(self.semana, dias=[0], bloques=["MANANA"])
        a = self.de(nik)
        self.assertEqual((a.pista, a.entrenador, a.forzada), (self.sb[0], None, True))
        self.assertIn("Sta. Bárbara sin entrenador", a.motivo_forzado)
        self.assertEqual(len(rep["satelites"]), 1)
        self.assertFalse(AvisoBanquillo.objects.filter(jugador=nik).exists())

    def test_primero_se_fuerza_en_el_resort(self):
        chimo = self.jugador("Chimo", 3)
        Asignacion.objects.create(semana=self.semana, dia=0, turno=self.m1,
                                  pista=self.resort, jugador=chimo,
                                  entrenador=self.pablo, manual=True)
        nik = self.jugador("Nik", 9)
        rep = generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertEqual(self.de(nik).pista, self.resort)
        self.assertFalse(rep.get("satelites"))

    def test_se_juntan_los_compatibles_y_el_otro_abre_pista(self):
        self.resort_lleno()
        a, b = self.jugador("Uno", 8), self.jugador("Dos", 8)
        c = self.jugador("Tres", 2)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertEqual(self.de(a).pista, self.de(b).pista)
        self.assertNotEqual(self.de(c).pista, self.de(a).pista)
        self.assertEqual({self.de(x).pista for x in (a, b, c)}, set(self.sb))
        self.assertNotIn(":", self.de(a).motivo_forzado)  # no rompe nada

    def test_una_rencilla_no_se_junta_ni_en_el_satelite(self):
        self.resort_lleno()
        a, b = self.jugador("Uno", 8), self.jugador("Dos", 8)
        Rencilla.objects.create(jugador_a=a, jugador_b=b)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertNotEqual(self.de(a).pista, self.de(b).pista)

    def test_el_de_resina_salta_a_betera(self):
        from academy.models import PreferenciaSuperficie

        self.resort_lleno()
        javi = self.jugador("Javi", 2)
        PreferenciaSuperficie.objects.create(jugador=javi, superficie="RESINA")
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertEqual(self.de(javi).pista, self.betera)

    def test_por_la_tarde_nunca(self):
        self.resort_lleno(turno=self.t1)
        self.resort_lleno(turno=Turno.objects.get(codigo="T2"))
        nik = self.jugador("Nik", 9, tarde=True)
        generate(self.semana, dias=[0], bloques=["TARDE"])
        self.assertIsNone(self.de(nik))

    def test_en_modo_nunca_se_queda_en_el_banquillo(self):
        self.cfg.modo_satelites = ConfiguracionMotor.ModoSatelites.NUNCA
        self.cfg.save()
        self.resort_lleno()
        nik = self.jugador("Nik", 9)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertIsNone(self.de(nik))


class ResortPrimeroYBanquilloTests(SatelitesDeRescateTests):
    """22/10/2026: el Resort tiene preferencia hasta llenarse, y Sta. Bárbara
    abre con entrenador: el primero libre del banquillo por su orden."""

    def banquillo(self, nombre, orden):
        return Entrenador.objects.create(nombre=nombre, reserva=True, orden_banquillo=orden)

    def test_antes_una_pista_libre_del_resort_que_sta_barbara(self):
        self.resort_lleno()
        p3 = Pista.objects.create(sede=self.resort.sede, numero=3, superficie="TIERRA")
        sergio = self.banquillo("Sergio", 2)
        nik = self.jugador("Nik", 9)
        rep = generate(self.semana, dias=[0], bloques=["MANANA"])
        a = self.de(nik)
        self.assertEqual((a.pista, a.entrenador), (p3, sergio))
        self.assertFalse(rep.get("satelites"))

    def test_sta_barbara_con_el_primero_del_banquillo(self):
        self.resort_lleno()
        self.banquillo("Ivan", 3)
        sergio = self.banquillo("Sergio", 2)
        nik = self.jugador("Nik", 9)
        rep = generate(self.semana, dias=[0], bloques=["MANANA"])
        a = self.de(nik)
        self.assertEqual((a.pista, a.entrenador), (self.sb[0], sergio))
        self.assertIn("Sta. Bárbara con Sergio", a.motivo_forzado)
        self.assertEqual(rep["satelites"][0]["entrenador"], sergio.id)

    def test_el_segundo_va_vigilado_al_lado(self):
        self.resort_lleno()
        sergio = self.banquillo("Sergio", 2)
        self.banquillo("Ivan", 3)
        a, b = self.jugador("Uno", 2), self.jugador("Dos", 9)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        pistas = {self.de(a).pista, self.de(b).pista}
        self.assertEqual(pistas, set(self.sb))
        self.assertEqual({self.de(a).entrenador, self.de(b).entrenador}, {sergio, None})


class DirectivaNoVaASantaBarbaraTests(SatelitesDeRescateTests):
    """22/10/2026: si para abrir Sta. Bárbara solo queda libre alguien de la
    directiva, se queda arriba en el Resort y baja otro."""

    def test_sube_la_directiva_y_baja_el_otro(self):
        sergio = Entrenador.objects.create(nombre="Sergio", reserva=True, orden_banquillo=2)
        a, b = self.jugador("Alto A", 2), self.jugador("Alto B", 2)
        nik = self.jugador("Nik", 9)
        rep = generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertEqual({self.de(a).entrenador, self.de(b).entrenador}, {sergio})
        self.assertEqual((self.de(nik).pista, self.de(nik).entrenador),
                         (self.sb[0], self.pablo))
        self.assertTrue(rep["directiva_arriba"])


class EdadComoPreferenciaTests(SatelitesDeRescateTests):
    """29/10/2026: «las diferencias de edad no son tan relevantes». Con
    `edad_obligatoria` apagado (lo normal), la edad no impide una pareja ni
    la marca como forzada; encendido, vuelven las bandas de edad."""

    def test_un_adulto_y_uno_de_quince_van_juntos_sin_marca(self):
        a, b = self.jugador("Adulta", 5, edad=21), self.jugador("Cadete", 5, edad=15)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertEqual(self.de(a).pista, self.de(b).pista)
        self.assertFalse(self.de(a).forzada or self.de(b).forzada)

    def test_con_la_regla_encendida_se_marca_como_forzada(self):
        self.cfg.edad_obligatoria = True
        self.cfg.save()
        a, b = self.jugador("Adulta", 5, edad=21), self.jugador("Cadete", 5, edad=15)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        # Una sola pista en el Resort: quien no cabe se mete forzado, con aviso.
        self.assertEqual(self.de(a).pista, self.de(b).pista)
        marcada = self.de(a) if self.de(a).forzada else self.de(b)
        self.assertTrue(marcada.forzada)
        self.assertIn("edad", marcada.motivo_forzado)
