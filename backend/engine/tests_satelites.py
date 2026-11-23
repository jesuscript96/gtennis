"""Nadie se queda en el banquillo por la mañana (21/10/2026). Primero el
relleno forzado en las pistas abiertas del Resort; lo que quede abre pista,
primero en el Resort y luego en Satélites. Por la tarde nunca.

23/11/2026: solo Resort y Satélites. En Satélites se montan las pistas que
hagan falta, de tierra y, si la resina del Resort está ocupada, de resina; un
entrenador por cada dos pistas (el segundo a partir de la tercera); los
invitados no van nunca."""
from collections import Counter
from datetime import date

from django.test import TestCase

from academy.models import (
    Division, Entrenador, HorarioJugador, Invitado, Jugador, Pista, Rencilla, Sede, Turno,
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
        self.satelites = self.satelite("Satélites", 1)
        # Dos de tierra y una de resina encendidas; el resto, apagadas.
        self.sat = [self.pista(self.satelites, n, "TIERRA") for n in (1, 2)]
        self.sat_resina = self.pista(self.satelites, 5, "RESINA")
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

    def resort_lleno(self, turno=None, pista=None):
        """Una pista del Resort con dos puestos a mano: no queda hueco."""
        turno = turno or self.m1
        pista = pista or self.resort
        for n in ("A", "B"):
            Asignacion.objects.create(
                semana=self.semana, dia=0, turno=turno, pista=pista,
                jugador=self.jugador(f"Fijo {n} {turno.codigo} {pista.numero}", 4,
                                     tarde=turno != self.m1),
                entrenador=self.pablo, manual=True)

    def de(self, j):
        return Asignacion.objects.filter(semana=self.semana, dia=0, jugador=j).first()

    def sueltos(self, n):
        """`n` jugadores que no pueden ir juntos (rencillas entre todos): cada
        uno abre su pista."""
        js = [self.jugador(f"Suelto {i}", 5) for i in range(n)]
        for i, a in enumerate(js):
            for b in js[i + 1:]:
                Rencilla.objects.create(jugador_a=a, jugador_b=b)
        return js

    def test_quien_no_cabe_va_a_satelites_sin_entrenador_y_con_aviso(self):
        self.resort_lleno()
        nik = self.jugador("Nik", 9)
        rep = generate(self.semana, dias=[0], bloques=["MANANA"])
        a = self.de(nik)
        self.assertEqual((a.pista, a.entrenador, a.forzada), (self.sat[0], None, True))
        self.assertIn("Satélites sin entrenador", a.motivo_forzado)
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
        self.assertEqual({self.de(x).pista for x in (a, b, c)}, set(self.sat))
        self.assertNotIn(":", self.de(a).motivo_forzado)  # no rompe nada

    def test_una_rencilla_no_se_junta_ni_en_satelites(self):
        self.resort_lleno()
        a, b = self.jugador("Uno", 8), self.jugador("Dos", 8)
        Rencilla.objects.create(jugador_a=a, jugador_b=b)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertNotEqual(self.de(a).pista, self.de(b).pista)

    def test_se_montan_las_pistas_que_hagan_falta(self):
        self.resort_lleno()
        antes = Pista.objects.filter(sede=self.satelites).count()
        jugadores = self.sueltos(5)
        rep = generate(self.semana, dias=[0], bloques=["MANANA"])
        pistas = {self.de(j).pista for j in jugadores}
        self.assertEqual(len(pistas), 5)
        self.assertTrue(all(p.sede == self.satelites and p.superficie == "TIERRA"
                            for p in pistas))
        # Las dos encendidas, las dos de tierra apagadas (3 y 4) y una nueva.
        self.assertEqual(Pista.objects.filter(sede=self.satelites).count(), antes + 1)
        self.assertEqual(len(rep["pistas_montadas"]), 3)

    def test_sin_preferencia_no_se_abre_resina(self):
        self.resort_lleno()
        jugadores = self.sueltos(3)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertNotIn(self.sat_resina, {self.de(j).pista for j in jugadores})

    def test_el_de_resina_va_a_satelites_si_la_resina_del_resort_esta_ocupada(self):
        from academy.models import PreferenciaSuperficie

        resina = self.pista(self.resort.sede, 7, "RESINA")
        self.resort_lleno()
        self.resort_lleno(pista=resina)
        javi = self.jugador("Javi", 2)
        PreferenciaSuperficie.objects.create(jugador=javi, superficie="RESINA")
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertEqual(self.de(javi).pista, self.sat_resina)

    def test_si_la_resina_del_resort_esta_libre_va_alli(self):
        from academy.models import PreferenciaSuperficie

        resina = self.pista(self.resort.sede, 7, "RESINA")
        self.resort_lleno()
        javi = self.jugador("Javi", 2)
        PreferenciaSuperficie.objects.create(jugador=javi, superficie="RESINA")
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertEqual(self.de(javi).pista, resina)

    def test_los_invitados_no_van_a_satelites(self):
        self.resort_lleno()
        yulan = self.jugador("Yulan (invitado)", 9)
        Invitado.objects.create(nombre="Yulan", entrenador_solicitante=self.pablo,
                                estado=Invitado.Estado.APROBADO, jugador_creado=yulan)
        rep = generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertIsNone(self.de(yulan))
        self.assertFalse(rep.get("satelites"))
        aviso = AvisoBanquillo.objects.get(jugador=yulan)
        self.assertIn("invitado", aviso.motivo)

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
    """22/10/2026: el Resort tiene preferencia hasta llenarse, y Satélites
    abre con entrenador: el primero libre del banquillo por su orden. Desde el
    23/11/2026, uno por cada dos pistas."""

    def banquillo(self, nombre, orden):
        return Entrenador.objects.create(nombre=nombre, reserva=True, orden_banquillo=orden)

    def test_antes_una_pista_libre_del_resort_que_satelites(self):
        self.resort_lleno()
        p3 = Pista.objects.create(sede=self.resort.sede, numero=3, superficie="TIERRA")
        sergio = self.banquillo("Sergio", 2)
        nik = self.jugador("Nik", 9)
        rep = generate(self.semana, dias=[0], bloques=["MANANA"])
        a = self.de(nik)
        self.assertEqual((a.pista, a.entrenador), (p3, sergio))
        self.assertFalse(rep.get("satelites"))

    def test_satelites_con_el_primero_del_banquillo_y_sin_aviso(self):
        self.resort_lleno()
        self.banquillo("Ivan", 3)
        sergio = self.banquillo("Sergio", 2)
        nik = self.jugador("Nik", 9)
        rep = generate(self.semana, dias=[0], bloques=["MANANA"])
        a = self.de(nik)
        self.assertEqual((a.pista, a.entrenador, a.forzada), (self.sat[0], sergio, False))
        self.assertEqual(rep["satelites"][0]["entrenador"], sergio.id)

    def test_la_segunda_pista_va_con_el_mismo_entrenador(self):
        self.resort_lleno()
        sergio = self.banquillo("Sergio", 2)
        self.banquillo("Ivan", 3)
        a, b = self.jugador("Uno", 2), self.jugador("Dos", 9)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertEqual({self.de(a).pista, self.de(b).pista}, set(self.sat))
        self.assertEqual((self.de(a).entrenador, self.de(b).entrenador), (sergio, sergio))

    def test_un_entrenador_por_cada_dos_pistas(self):
        self.resort_lleno()
        sergio = self.banquillo("Sergio", 2)
        ivan = self.banquillo("Ivan", 3)
        jorge = self.banquillo("Jorge", 4)
        jugadores = self.sueltos(5)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        por_pista = {self.de(j).pista_id: self.de(j).entrenador for j in jugadores}
        self.assertEqual(len(por_pista), 5)
        self.assertEqual(Counter(por_pista.values()), {sergio: 2, ivan: 2, jorge: 1})

    def test_la_tercera_saca_otro_y_si_no_hay_va_sin_entrenador(self):
        self.resort_lleno()
        sergio = self.banquillo("Sergio", 2)
        jugadores = self.sueltos(3)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        entrenadores = Counter(self.de(j).entrenador for j in jugadores)
        self.assertEqual(entrenadores, {sergio: 2, None: 1})
        sin = next(self.de(j) for j in jugadores if self.de(j).entrenador is None)
        self.assertTrue(sin.forzada)


class DirectivaNoVaASatelitesTests(SatelitesDeRescateTests):
    """22/10/2026: si para abrir Satélites solo queda libre alguien de la
    directiva, se queda arriba en el Resort y baja otro."""

    def test_sube_la_directiva_y_baja_el_otro(self):
        sergio = Entrenador.objects.create(nombre="Sergio", reserva=True, orden_banquillo=2)
        a, b = self.jugador("Alto A", 2), self.jugador("Alto B", 2)
        nik = self.jugador("Nik", 9)
        rep = generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertEqual({self.de(a).entrenador, self.de(b).entrenador}, {sergio})
        self.assertEqual((self.de(nik).pista, self.de(nik).entrenador),
                         (self.sat[0], self.pablo))
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


class InvitadoYSuParejaEnElResortTests(SatelitesDeRescateTests):
    """23/11/2026: Yulan (invitada, D9, solo M1) se quedó fuera porque el
    reparto dejó fuera a su pareja obligatoria (Nik) y ella no puede ir a
    Satélites. Ahora, si alguien tiene que salir del Resort, sale quien puede
    entrenar fuera: ella y Nik se quedan y la pista de los otros va a
    Satélites."""

    def test_el_invitado_y_su_pareja_se_quedan_y_sale_otra_pista(self):
        from academy.models import PreferenciaPareja

        a, b = self.jugador("Ocho A", 8), self.jugador("Ocho B", 8)
        nik = self.jugador("Nik", 9)
        yulan = self.jugador("Yulan (invitada)", 9, sexo="CHICA", edad=12)
        Invitado.objects.create(nombre="Yulan", entrenador_solicitante=self.pablo,
                                estado=Invitado.Estado.APROBADO, jugador_creado=yulan)
        PreferenciaPareja.objects.create(jugador=yulan, jugador_objetivo=nik,
                                         tipo=PreferenciaPareja.Tipo.HARD)
        generate(self.semana, dias=[0], bloques=["MANANA"])
        self.assertEqual(self.de(yulan).pista, self.resort)
        self.assertEqual(self.de(nik).pista, self.resort)
        self.assertEqual({self.de(a).pista.sede, self.de(b).pista.sede}, {self.satelites})
        self.assertFalse(AvisoBanquillo.objects.filter(jugador=yulan).exists())

    def test_por_la_tarde_sin_satelites_no_se_adelanta(self):
        # Sin Satélites por la tarde, salir del Resort es quedarse en el
        # banquillo: el invitado no pasa por delante.
        from engine.service import PRIORIDAD_SOLO_RESORT

        self.assertGreater(PRIORIDAD_SOLO_RESORT, 2 * 9)


class MismoEntrenadorEnLasDosFranjasTests(SatelitesDeRescateTests):
    """23/11/2026: el entrenador que va a Satélites se queda allí en M1 y M2
    (y por la tarde, si se usan, primero el de la mañana)."""

    def setUp(self):
        super().setUp()
        self.m2 = Turno.objects.get(codigo="M2")
        # Inactivo: el motor no lo usa en las pruebas heredadas; aquí da igual.
        self.ivan = Entrenador.objects.create(nombre="Ivan", activo=False)
        self.libres = set()
        self.soltados = []

    def fila(self, turno, pista, coach, nombre, manual=False):
        return Asignacion.objects.create(
            semana=self.semana, dia=0, turno=turno, pista=pista,
            jugador=self.jugador(nombre, 9), entrenador=coach, manual=manual)

    def pasar(self, grupo=None):
        from engine.service import _mismos_en_satelites

        return _mismos_en_satelites(
            self.semana, 0, grupo or [self.m1, self.m2],
            libre=lambda cid, t: (cid, t.codigo) in self.libres,
            tomar=lambda cid, t: None,
            soltar=lambda cid, t: self.soltados.append((cid, t.codigo)),
            vetos_coach={}, atados_de=lambda t: {}, no_vigilan=set())

    def coach_en(self, turno, pista):
        return Asignacion.objects.filter(semana=self.semana, dia=0, turno=turno,
                                         pista=pista).first().entrenador

    def test_si_esta_en_el_resort_se_cambia_con_el_de_satelites(self):
        self.fila(self.m1, self.sat[0], self.pablo, "X")
        self.fila(self.m2, self.resort, self.pablo, "A")
        self.fila(self.m2, self.sat[0], self.ivan, "Y")
        self.assertEqual(self.pasar(), 1)
        self.assertEqual(self.coach_en(self.m2, self.sat[0]), self.pablo)
        self.assertEqual(self.coach_en(self.m2, self.resort), self.ivan)

    def test_si_esta_libre_va_el_y_el_otro_queda_libre(self):
        self.fila(self.m1, self.sat[0], self.pablo, "X")
        self.fila(self.m2, self.sat[0], self.ivan, "Y")
        self.fila(self.m2, self.sat[1], self.ivan, "Z")
        self.libres = {(self.pablo.id, "M2")}
        self.pasar()
        self.assertEqual(self.coach_en(self.m2, self.sat[0]), self.pablo)
        self.assertEqual(self.coach_en(self.m2, self.sat[1]), self.pablo)
        self.assertEqual(self.soltados, [(self.ivan.id, "M2")])

    def test_lo_puesto_a_mano_no_se_toca(self):
        self.fila(self.m1, self.sat[0], self.pablo, "X")
        self.fila(self.m2, self.resort, self.pablo, "A", manual=True)
        self.fila(self.m2, self.sat[0], self.ivan, "Y")
        self.assertEqual(self.pasar(), 0)
        self.assertEqual(self.coach_en(self.m2, self.sat[0]), self.ivan)

    def test_una_pista_sin_entrenador_la_coge_el_de_la_otra_franja(self):
        self.fila(self.m1, self.sat[0], self.pablo, "X")
        a = self.fila(self.m2, self.sat[0], None, "Y")
        Asignacion.objects.filter(pk=a.pk).update(
            forzada=True, motivo_forzado="Satélites sin entrenador, para que no se quede en el banquillo")
        self.libres = {(self.pablo.id, "M2")}
        self.pasar()
        a.refresh_from_db()
        self.assertEqual((a.entrenador, a.forzada), (self.pablo, False))

    def test_por_la_tarde_primero_el_de_la_manana(self):
        t1, t2 = self.t1, Turno.objects.get(codigo="T2")
        self.fila(self.m1, self.sat[0], self.pablo, "X")
        self.fila(t1, self.resort, self.pablo, "A")
        self.fila(t1, self.sat[0], self.ivan, "Y")
        self.pasar(grupo=[t1, t2])
        self.assertEqual(self.coach_en(t1, self.sat[0]), self.pablo)
        self.assertEqual(self.coach_en(t1, self.resort), self.ivan)


class SatelitesPorLaTardeTests(SatelitesDeRescateTests):
    """23/11/2026: en el modo «también por la tarde», quien no cabe en T1 ni
    T2 del Resort va a Satélites, siempre con entrenador."""

    def tarde_llena(self):
        self.resort_lleno(turno=self.t1)
        self.resort_lleno(turno=Turno.objects.get(codigo="T2"))

    def test_va_a_satelites_con_entrenador(self):
        self.cfg.modo_satelites = ConfiguracionMotor.ModoSatelites.SIEMPRE
        self.cfg.save()
        self.tarde_llena()
        sergio = Entrenador.objects.create(nombre="Sergio", reserva=True, orden_banquillo=2)
        nik = self.jugador("Nik", 9, tarde=True)
        generate(self.semana, dias=[0], bloques=["TARDE"])
        self.assertEqual((self.de(nik).pista.sede, self.de(nik).entrenador),
                         (self.satelites, sergio))

    def test_sin_entrenador_por_la_tarde_no_se_abre(self):
        self.cfg.modo_satelites = ConfiguracionMotor.ModoSatelites.SIEMPRE
        self.cfg.save()
        self.tarde_llena()
        nik = self.jugador("Nik", 9, tarde=True)
        generate(self.semana, dias=[0], bloques=["TARDE"])
        self.assertIsNone(self.de(nik))
