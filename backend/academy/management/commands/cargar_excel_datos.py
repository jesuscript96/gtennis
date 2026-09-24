"""Carga en la BBDD la plantilla rellenada por el club.

Dos fuentes, cada una con su papel:

* `GTennis_datos-1.xlsx` (hojas JUGADORES y ENTRENADORES) es la **ficha**: lo
  que vale todas las semanas — división, sexo, con quién entrena y en qué
  proporción, contratos, vetos, y el horario habitual de lunes a sábado.
* `2026 (4).xlsx`, hoja SEPTIEMBRE filas 315-382, es **una semana concreta**:
  quién vino de verdad. De ahí salen las ausencias (y los «viene además») de
  esa semana, tanto de jugadores como de entrenadores.

La ficha manda sobre el patrón; el cuadrante real manda sobre los días.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from academy.models import (
    Contrato, Division, Entrenador, Escuela, HorarioJugador, Jugador,
    PreferenciaEntrenadorFranja, PreferenciaSuperficie, ResponsableJugador,
    Turno, VetoEntrenador,
)
from scheduling.models import (
    Ambito, AusenciaJugador, Disponibilidad, DisponibilidadEntrenador, Estado,
    Semana, SubtipoAusencia,
)

# --- Hoja JUGADORES ---------------------------------------------------------
COL = {
    "nombre": 1, "codigo": 2, "escuela": 3, "division": 4, "sexo": 5,
    "nacim": 6, "responsable": 7, "principal": 8, "secundarios": 9,
    "vecindad": 10, "pareja_div": 11, "max_dia": 12, "alta": 13, "baja": 14,
    "veto": 15, "contrato": 16, "pareja": 17, "pareja_obl": 18,
    "superficie": 19, "superficie_obl": 20, "pistas": 21, "notas": 48,
}
# Semana habitual: (mañana, tarde) por día. El sábado solo tiene mañana.
HABITUAL = [(22, 23), (24, 25), (26, 27), (28, 29), (30, 31), (32, None)]

VECINDAD = {
    "±1 (la del club)": "CLUB",
    "solo su división": "SOLO",
    "su división y la de encima": "ARRIBA",
    "su división y la de debajo": "ABAJO",
    "su división y las dos vecinas": "AMBAS",
}
PAREJA_DIV = {"arriba (mejor)": "ARRIBA", "abajo (peor)": "ABAJO"}

# --- Hoja ENTRENADORES ------------------------------------------------------
COL_E = {
    "nombre": 1, "div_desde": 2, "div_hasta": 3, "franja_m": 4, "franja_t": 5,
    "banquillo": 6, "disponible": 7,
}

# --- Cuadrante real ---------------------------------------------------------
DIAS_COL = {0: (1, 3), 1: (4, 6), 2: (7, 9), 3: (10, 12), 4: (13, 15),
            5: (16, 18)}
# (franja, primera fila, última fila). El bloque TORNEO de las filas 334-348 no
# es un entrenamiento: es la lista de quién va al torneo del fin de semana.
BANDAS = [("M1", 317, 332), ("M2", 350, 365), ("T1", 367, 382), ("T2", 384, 388)]
BANDA_TORNEO = (334, 348)

# Cómo firma cada entrenador en el cuadrante.
ALIAS_COACH = {
    "blas g": "Blas Gallego", "dani g": "Daniel Gimeno",
    "javi g": "Javi Gimenez", "nacho c": "Nacho Calvo",
    "santi p": "Santi Panzarasa", "pablo g": "Pablo Gil",
    "ivan g": "Ivan Gallego", "victor r": "Victor Redondo",
    "emilio s": "Emilio Sorio", "salva b": "Salva Barcala",
    "mario m": "Mario Muniesa", "patricio r": "Patricio rodriguez",
    "alberto": "Alberto Sanz", "alvaro m": "Alvaro Mantoan",
    "mantuan": "Alvaro Mantoan", "jorge": "Jorge Garcia",
    # Abreviaturas de las columnas de la ficha.
    "nacho": "Nacho Calvo", "santi": "Santi Panzarasa",
    "mario": "Mario Muniesa", "salva": "Salva Barcala", "pablo": "Pablo Gil",
    "patricio": "Patricio rodriguez", "ivan": "Ivan Gallego",
    "javi": "Javi Gimenez", "victor": "Victor Redondo",
    "victori redondo": "Victor Redondo", "dani gimeno": "Daniel Gimeno",
    "emilio": "Emilio Sorio", "blas": "Blas Gallego",
}


# Lo que se lleva un entrenador citado sin porcentaje cuando lo declarado ya
# suma 100: aparece en la lista, luego algo entrena con él.
MINIMO_SECUNDARIO = 5


def limpio(v):
    return "" if v is None else str(v).strip()


def clave(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = re.sub(r"\(.*?\)", " ", s.lower())
    s = re.sub(r"[^a-z ]", " ", s)
    return " ".join(s.split())


def clave_num(s):
    """Como `clave` pero sin tirar los números: «la semana del 14 en resina»."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return " ".join(s.split())


def entero(v):
    """El número de una celda que Excel puede haber convertido en «3.0»."""
    s = limpio(v).replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", s)
    return int(float(m.group())) if m else None


def a_fecha(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = limpio(v)
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


class Command(BaseCommand):
    help = "Carga la plantilla del club y la asistencia real de una semana."

    def add_arguments(self, parser):
        parser.add_argument("--datos", required=True, help="GTennis_datos.xlsx")
        parser.add_argument("--cuadrante", help="2026.xlsx con la semana real")
        parser.add_argument("--hoja", default="SEPTIEMBRE")
        parser.add_argument("--semana", help="Lunes de la semana (YYYY-MM-DD)")
        parser.add_argument("--dry-run", action="store_true")

    # -- utilidades de resolución ------------------------------------------
    def coach(self, texto):
        """El entrenador que firma como `texto`, o None."""
        k = clave(re.sub(r"\d+\s*%?", " ", texto))
        if not k:
            return None
        if k in ALIAS_COACH:
            k = clave(ALIAS_COACH[k])
        if k in self._coach_por_clave:
            return self._coach_por_clave[k]
        tk = set(k.split())
        mejor, puntos = None, 0
        for ck, c in self._coach_por_clave.items():
            n = len(tk & set(ck.split()))
            if n > puntos:
                mejor, puntos = c, n
        return mejor if puntos else None

    def jugador(self, texto, solo_ficha=False):
        """El alumno que firma como `texto`.

        En el cuadrante los nombres vienen a mano y abreviados («Javi
        Ballester», «Valentina Andrea 13»), así que un apellido suelto coincide
        con varios: se exige que el mejor candidato gane solo, y `solo_ficha`
        limita la búsqueda a los alumnos de la plantilla — el resto del
        cuadrante es la escuela de tarde, que aquí no interesa.
        """
        k = clave(texto)
        if not k:
            return None
        candidatos = self._jug_por_clave
        if solo_ficha:
            candidatos = {jk: j for jk, j in candidatos.items()
                          if j.id in self.del_excel}
        if k in candidatos:
            return candidatos[k]
        tk = k.split()
        puntuadas = sorted(
            ((self._parecido(tk, jk.split()), j) for jk, j in candidatos.items()),
            key=lambda x: -x[0],
        )
        if not puntuadas or puntuadas[0][0] == 0:
            return None
        # Empate arriba = no se sabe de quién habla: mejor no adivinar.
        if len(puntuadas) > 1 and puntuadas[1][0] == puntuadas[0][0]:
            return None
        return puntuadas[0][1]

    @staticmethod
    def _parecido(a, b):
        """Nombres en común, admitiendo abreviaturas («Javi» ≈ «Javier»)."""
        n = 0
        for t in a:
            if any(t == u or (len(t) >= 4 and (t.startswith(u) or u.startswith(t)))
                   for u in b):
                n += 1
        return n

    # -- reparto de porcentajes --------------------------------------------
    def reparto(self, principal, secundarios):
        """[(entrenador, prioridad, porcentaje)] a partir de las dos columnas.

        El % declarado es el objetivo; lo que falte hasta 100 queda libre. A
        quien viene sin %, se le reparte a partes iguales lo que sobra, y
        «un poquito más» se lleva el doble.
        """
        filas, vistos = [], set()

        def trozos(texto):
            # «Pablo, mario, nacho y patricio (patricio un poquito mas)»: la
            # conjunción separa igual que la coma, y el paréntesis es un matiz
            # sobre el último, no un nombre nuevo.
            texto = re.sub(r"\(([^)]*)\)", r" \1", texto)
            partes = re.split(r"[;,]|\sy\s", texto)
            return [t for t in partes if t.strip()]

        def parsea(trozo):
            m = re.search(r"(\d+)\s*%?", trozo)
            pct = int(m.group(1)) if m else None
            resto = trozo[:m.start()] + trozo[m.end():] if m else trozo
            return resto, pct

        def añade(texto, prioridad):
            for trozo in trozos(texto):
                nombre, pct = parsea(trozo)
                c = self.coach(nombre)
                if c is None or c.id in vistos:
                    continue
                vistos.add(c.id)
                filas.append([c, prioridad, pct, "mas" in clave(trozo)])

        añade(principal, 1)
        añade(secundarios, 2)
        if not filas:
            return []
        declarado = sum(f[2] for f in filas if f[2] is not None)
        sin_pct = [f for f in filas if f[2] is None]
        if sin_pct:
            pesos = [2 if f[3] else 1 for f in sin_pct]
            total = sum(pesos)
            libre = max(0, 100 - declarado)
            # Si los % declarados ya suman 100, los que vienen sin número se
            # quedarían a cero y el motor no los usaría nunca. Se les reserva
            # un mínimo y se encoge lo declarado en la misma proporción.
            if libre < MINIMO_SECUNDARIO * total:
                libre = MINIMO_SECUNDARIO * total
                factor = (100 - libre) / declarado if declarado else 0
                for f in filas:
                    if f[2] is not None:
                        f[2] = round(f[2] * factor)
            for f, w in zip(sin_pct, pesos):
                f[2] = round(libre * w / total)
        return [(f[0], f[1], f[2]) for f in filas]

    # -- carga --------------------------------------------------------------
    def handle(self, *args, **o):
        import openpyxl

        self.dry = o["dry_run"]
        wb = openpyxl.load_workbook(o["datos"], data_only=True)
        self._coach_por_clave = {clave(e.nombre): e for e in Entrenador.objects.all()}
        self._jug_por_clave = {clave(j.nombre): j for j in Jugador.objects.all()}
        self.turnos = {t.codigo: t for t in Turno.objects.all()}
        self.divisiones = {d.nivel: d for d in Division.objects.all()}
        self.escuelas = {clave(e.nombre): e for e in Escuela.objects.all()}

        with transaction.atomic():
            self.fichas(wb["JUGADORES"])
            self.entrenadores(wb["ENTRENADORES"])
            if o["cuadrante"]:
                if not o["semana"]:
                    raise CommandError("--cuadrante necesita --semana")
                wb2 = openpyxl.load_workbook(o["cuadrante"], data_only=True)
                self.semana_real(wb2[o["hoja"]], a_fecha(o["semana"]))
            if self.dry:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("dry-run: nada guardado"))

    # ---------------------------------------------------------------- fichas
    def fichas(self, ws):
        hoy = date.today()
        self.del_excel = set()
        n_alta = n_baja = n_resp = n_veto = n_con = n_hor = 0
        for r in range(7, ws.max_row + 1):          # la 6 es el ejemplo
            nombre = limpio(ws.cell(row=r, column=COL["nombre"]).value)
            if not nombre or nombre.startswith("("):
                continue
            j = self.jugador(nombre)
            if j is None:
                self.stdout.write(self.style.WARNING(f"sin ficha en BBDD: {nombre}"))
                continue
            self.del_excel.add(j.id)
            g = lambda c: limpio(ws.cell(row=r, column=COL[c]).value)

            div = entero(g("division"))
            if div in self.divisiones:
                j.division = self.divisiones[div]
            sexo = clave(g("sexo"))
            if sexo in ("chico", "chica"):
                j.sexo = sexo.upper()
            nac = a_fecha(ws.cell(row=r, column=COL["nacim"]).value)
            if nac and nac < hoy:
                j.fecha_nacimiento = nac
            esc = self.escuelas.get(clave(g("escuela")))
            if esc:
                j.escuela = esc
            for etiqueta, valor in VECINDAD.items():
                if clave(etiqueta) in clave(g("vecindad")):
                    j.vecindad = valor
                    break
            j.pareja_division = PAREJA_DIV.get(g("pareja_div").lower())
            j.sesiones_dia_max = entero(g("max_dia"))
            alta = a_fecha(ws.cell(row=r, column=COL["alta"]).value)
            baja = a_fecha(ws.cell(row=r, column=COL["baja"]).value)
            if alta:
                j.fecha_alta = alta
                n_alta += 1
            if baja:
                j.fecha_baja = baja
            j.entrenador_responsable = self.coach(g("responsable"))

            k = clave_num(g("notas"))
            j.sin_prioridad = "despriorizar" in k
            if "no esta" in k:
                j.activo = False
                n_baja += 1
            j.save()

            # --- reparto de entrenadores ---------------------------------
            ResponsableJugador.objects.filter(jugador=j).delete()
            for c, prioridad, pct in self.reparto(g("principal"), g("secundarios")):
                ResponsableJugador.objects.create(
                    jugador=j, entrenador=c, prioridad=prioridad,
                    porcentaje_objetivo=pct,
                )
                n_resp += 1

            # --- «no debe entrenar con» -----------------------------------
            VetoEntrenador.objects.filter(jugador=j).delete()
            for trozo in re.split(r"[;,]", g("veto")):
                texto = re.sub(r"(?i)entrenador\s*:?", "", trozo)
                c = self.coach(texto)
                if c:
                    VetoEntrenador.objects.create(
                        jugador=j, entrenador=c, nota=trozo.strip()[:200])
                    n_veto += 1

            # --- contratos -------------------------------------------------
            Contrato.objects.filter(jugador=j).delete()
            for trozo in re.split(r"[;]", g("contrato")):
                c = self.coach(trozo)
                if not c:
                    continue
                kk = clave(trozo)
                tipo = "BLANDO" if ("soft" in kk or "si puede" in kk) else "DURO"
                Contrato.objects.create(jugador=j, entrenador=c, tipo=tipo)
                n_con += 1

            # --- lesión larga y superficie de una semana -------------------
            AusenciaJugador.objects.filter(
                jugador=j, nota__startswith="Excel").delete()
            if "lesionado" in k:
                AusenciaJugador.objects.create(
                    jugador=j, fecha_inicio=date(2026, 9, 14),
                    fecha_fin=date(2026, 11, 23), ambito=Ambito.DIA,
                    estado=Estado.AUSENCIA_JUGADOR,
                    subtipo=SubtipoAusencia.LESION,
                    nota="Excel: lesionado, alta prevista en dos meses",
                )
            PreferenciaSuperficie.objects.filter(jugador=j).delete()
            sup = clave(g("superficie"))
            if sup in ("tierra", "resina"):
                PreferenciaSuperficie.objects.create(
                    jugador=j, superficie=sup.upper(),
                    estricta=clave(g("superficie_obl")) in ("si", "sí"),
                )
            m = re.search(r"semana del (\d+).*?(tierra|resina)", k)
            if m:
                inicio = date(2026, 9, int(m.group(1)))
                PreferenciaSuperficie.objects.create(
                    jugador=j, superficie=m.group(2).upper(), estricta=True,
                    fecha_desde=inicio, fecha_hasta=inicio + timedelta(days=5),
                )

            # --- entrenador atado a una franja ----------------------------
            PreferenciaEntrenadorFranja.objects.filter(jugador=j).delete()
            m = re.search(r"si entrena en (m\d|t\d).*?con (\w+)", k)
            if m:
                turno = self.turnos.get(m.group(1).upper())
                c = self.coach(m.group(2))
                if turno and c:
                    PreferenciaEntrenadorFranja.objects.create(
                        jugador=j, turno=turno, entrenador=c, tipo="DURO")

            # --- horario habitual -----------------------------------------
            HorarioJugador.objects.filter(jugador=j).delete()
            for dia, (cm, ct) in enumerate(HABITUAL):
                vm = limpio(ws.cell(row=r, column=cm).value)
                vt = limpio(ws.cell(row=r, column=ct).value) if ct else ""
                # Siempre se escribe la fila, también en blanco: sin ella el
                # motor tira de la ficha y da por hecho que el alumno viene.
                HorarioJugador.objects.create(
                    jugador=j, dia=dia,
                    entrena_manana=bool(vm) and clave(vm) != "no",
                    entrena_tarde=bool(vt) and clave(vt) != "no",
                    turno_manana=self.turnos.get(vm.upper()),
                    turno_tarde=self.turnos.get(vt.upper()),
                )
                n_hor += 1
        self.stdout.write(
            f"fichas: {n_alta} altas, {n_baja} bajas («no está»), {n_resp} "
            f"repartos, {n_veto} vetos, {n_con} contratos, {n_hor} días de horario")

    # --------------------------------------------------------- entrenadores
    def entrenadores(self, ws):
        n = 0
        for r in range(7, ws.max_row + 1):
            nombre = limpio(ws.cell(row=r, column=COL_E["nombre"]).value)
            if not nombre or nombre.startswith("("):
                continue
            c = self.coach(nombre)
            if c is None:
                continue
            g = lambda k: limpio(ws.cell(row=r, column=COL_E[k]).value)
            c.division_desde = entero(g("div_desde"))
            c.division_hasta = entero(g("div_hasta"))
            c.turno_manana = self.turnos.get(g("franja_m").upper())
            c.turno_tarde = self.turnos.get(g("franja_t").upper())
            c.reserva = clave(g("banquillo")) in ("si", "sí")
            c.disponible_semana = clave(g("disponible")) not in ("no",)
            c.save()
            n += 1
        self.stdout.write(f"entrenadores actualizados: {n}")

    # ------------------------------------------------------- la semana real
    def semana_real(self, ws, lunes):
        """Ausencias y presencias de una semana, leídas del cuadrante real."""
        semana, _ = Semana.objects.get_or_create(fecha_inicio=lunes)
        vistos_j = defaultdict(set)     # jugador_id -> {(dia, franja)}
        vistos_c = defaultdict(set)     # entrenador_id -> {(dia, franja)}
        torneo = set()
        for dia, (c0, c1) in DIAS_COL.items():
            for franja, r0, r1 in BANDAS:
                for r in range(r0, r1 + 1):
                    for col in range(c0, c1 + 1):
                        s = limpio(ws.cell(row=r, column=col).value)
                        if not s or re.fullmatch(r"[\d.,]+", s):
                            continue
                        if s.upper() in ("PISTA", "ENTRENADORES", "TORNEO"):
                            continue
                        if s.isupper() or clave(s) in ALIAS_COACH:
                            c = self.coach(s)
                            if c:
                                vistos_c[c.id].add((dia, franja))
                            continue
                        j = self.jugador(s, solo_ficha=True)
                        if j:
                            vistos_j[j.id].add((dia, franja))
            if dia == 0:                 # la lista del torneo está bajo el lunes
                for r in range(*BANDA_TORNEO):
                    for col in range(c0, c1 + 1):
                        j = self.jugador(limpio(ws.cell(row=r, column=col).value),
                                         solo_ficha=True)
                        if j:
                            torneo.add(j.id)

        domingo = lunes + timedelta(days=6)
        # Quien está marcado «no está» pero aparece en el cuadrante sí estuvo
        # esa semana: se le deja activo y se le pone la baja al final de ella.
        for jid in list(vistos_j):
            j = Jugador.objects.get(pk=jid)
            if not j.activo:
                j.activo = True
                j.fecha_baja = lunes + timedelta(days=5)
                j.save(update_fields=["activo", "fecha_baja"])
                self.stdout.write(
                    f"{j.nombre}: «no está» pero vino — activo hasta {j.fecha_baja}")
        # Ausencias largas de pruebas anteriores que pisan esta semana: si no,
        # se suman a lo que dice el cuadrante y sacan a gente que sí vino.
        viejas = AusenciaJugador.objects.filter(
            fecha_inicio__lte=domingo, fecha_fin__gte=lunes,
        ).exclude(nota__startswith="Excel")
        if viejas:
            self.stdout.write(f"ausencias antiguas borradas: {viejas.count()}")
            viejas.delete()

        Disponibilidad.objects.filter(semana=semana).delete()
        DisponibilidadEntrenador.objects.filter(semana=semana).delete()
        horario = {(h.jugador_id, h.dia): h for h in HorarioJugador.objects.all()}
        n_aus = n_extra = 0
        for j in Jugador.objects.filter(activo=True):
            for dia in range(6):
                h = horario.get((j.id, dia))
                franjas = {f for d, f in vistos_j[j.id] if d == dia}
                for bloque, propias, toca in (
                    (Ambito.MANANA, {"M1", "M2"}, h.entrena_manana if h else False),
                    (Ambito.TARDE, {"T1", "T2"}, h.entrena_tarde if h else False),
                ):
                    vino = bool(franjas & propias)
                    if toca and not vino:
                        Disponibilidad.objects.create(
                            semana=semana, jugador=j, dia=dia, ambito=bloque,
                            # El torneo es el fin de semana: entre semana el
                            # que no aparece en el cuadrante, sencillamente no
                            # está. EN_TORNEO solo baja la prioridad y le
                            # dejaría colarse a llenar huecos.
                            estado=Estado.AUSENCIA_JUGADOR,
                            nota=("Torneo del fin de semana"
                                  if j.id in torneo
                                  else "Cuadrante real de la semana"),
                        )
                        n_aus += 1
                    elif vino and not toca:
                        Disponibilidad.objects.create(
                            semana=semana, jugador=j, dia=dia, ambito=bloque,
                            estado=Estado.EXTRA,
                            nota="Cuadrante real de la semana",
                        )
                        n_extra += 1

        # Entrenadores: el día que no aparecen, no están; y si solo dan clase
        # por la mañana, la ventana horaria lo dice.
        horas = {"M1": (time(8, 30), time(10, 0)), "M2": (time(10, 0), time(12, 30)),
                 "T1": (time(14, 15), time(15, 30)), "T2": (time(15, 30), time(17, 30))}
        n_c = 0
        for c in Entrenador.objects.filter(activo=True):
            for dia in range(6):
                franjas = {f for d, f in vistos_c[c.id] if d == dia}
                if not franjas:
                    # Al de banquillo no se le marca ausente por no salir en el
                    # cuadrante: está en el club justo para eso, para no estar
                    # en ninguna pista hasta que hace falta.
                    if c.reserva:
                        continue
                    DisponibilidadEntrenador.objects.create(
                        semana=semana, entrenador=c, dia=dia,
                        estado=DisponibilidadEntrenador.EstadoCoach.AUSENTE,
                        nota="No aparece en el cuadrante real")
                    n_c += 1
                    continue
                if c.reserva:
                    continue
                ini = min(horas[f][0] for f in franjas)
                fin = max(horas[f][1] for f in franjas)
                if (ini, fin) != (time(8, 30), time(17, 30)):
                    DisponibilidadEntrenador.objects.create(
                        semana=semana, entrenador=c, dia=dia,
                        estado=DisponibilidadEntrenador.EstadoCoach.DISPONIBLE,
                        hora_desde=ini, hora_hasta=fin,
                        nota="Franjas del cuadrante real")
                    n_c += 1
        self.stdout.write(
            f"semana {lunes}: {n_aus} ausencias, {n_extra} «viene además», "
            f"{n_c} partes de entrenador, {len(torneo)} en el torneo")
