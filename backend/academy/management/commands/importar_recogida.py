"""Lee el Excel de recogida y lo interpreta contra la base de datos.

La premisa es que el cliente escribe como quiera —`M1+T2`, `mañana`, `8:30`,
`solo lunes`, `-`— y el trabajo de entender está aquí, no en él. Todo lo que no
se entiende no se inventa: sale en un informe con la fila, la columna y el
texto literal, para preguntar.

Escribe cuatro cosas:
  · `HorarioJugador`  — qué turnos hace cada jugador cada día (el dato que hoy
    falta y por el que el motor reparte a cuatro días en vez de a dos).
  · `Jugador.turno_manana` / `turno_tarde` / `sesiones_semana`.
  · `Entrenador.divisiones_habilitadas` y `HorarioEntrenador`.
  · `AusenciaJugador` / `VacacionesEntrenador` para lo ya conocido.

Uso:
    python manage.py importar_recogida docs/Recogida_GTennis.xlsx --dry-run
    python manage.py importar_recogida docs/Recogida_GTennis.xlsx
"""
import datetime as dt
import re
import unicodedata
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from academy.models import (
    Contrato, Division, Entrenador, HorarioEntrenador, HorarioJugador, Jugador,
    Pista, PreferenciaPareja, PreferenciaSuperficie, Rencilla, ResponsableJugador,
    Turno, VacacionesEntrenador,
)
from scheduling.models import Ambito, AusenciaJugador, Estado

DIAS_COL = [0, 1, 2, 3, 4]          # columnas L..V de la plantilla
NO_ENTRENA = {"-", "--", "no", "nada", "libre", "descansa", "descanso", "off",
              "fiesta", "ninguno", "ninguna", "0"}
VIENE_SIN_MAS = {"x", "si", "ok", "v", "vale", "viene", "*", "1"}
NUMEROS = {"un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
           "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
           "once": 11, "doce": 12}
MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7,
         "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}


def numero_de(texto):
    """'4', 'cuatro', '4 sesiones', 'dos al dia' -> el primer número que salga."""
    m = re.search(r"\d+", texto)
    if m:
        return int(m.group())
    for palabra, n in NUMEROS.items():
        if re.search(rf"\b{palabra}\b", texto):
            return n
    return None


def norm(v):
    """Minúsculas, sin acentos, sin dobles espacios. None y '' dan ''."""
    if v is None:
        return ""
    s = str(v).strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).lower()


class Interprete:
    """Traduce texto libre a turnos, apoyándose en el horario real del curso."""

    def __init__(self, turnos):
        self.turnos = {t.codigo.lower(): t for t in turnos}
        self.manana = [t for t in turnos if t.bloque == Turno.Bloque.MANANA]
        self.tarde = [t for t in turnos if t.bloque != Turno.Bloque.MANANA]
        # Orden dentro del bloque: "la primera de la tarde" = la más temprana.
        self.orden = {}
        for lista in (self.manana, self.tarde):
            for i, t in enumerate(sorted(lista, key=lambda x: x.hora_inicio)):
                self.orden[(t.bloque, i + 1)] = t

    def _por_hora(self, texto):
        """Turnos citados por su hora. '8:30', '8.30', '830', '15h', '15'."""
        hallados = []
        for h, m in re.findall(r"(\d{1,2})[:.h]?(\d{2})?\b", texto):
            hora = int(h)
            minuto = int(m) if m else None
            if hora > 23:
                continue
            for t in self.turnos.values():
                if t.hora_inicio.hour != hora:
                    continue
                if minuto is not None and abs(t.hora_inicio.minute - minuto) > 20:
                    continue
                hallados.append(t)
        return hallados

    def turnos_de(self, celda):
        """(turno_mañana, turno_tarde, marca). marca explica qué ha pasado."""
        s = norm(celda)
        if not s:
            return None, None, "vacio"
        if s in NO_ENTRENA:
            return None, None, "no_entrena"
        if s in VIENE_SIN_MAS:
            return None, None, "viene_sin_turno"

        man = tar = None
        # 1) Códigos explícitos: lo más fiable, manda sobre todo lo demás.
        for cod, t in self.turnos.items():
            if re.search(rf"\b{cod}\b", s):
                if t.bloque == Turno.Bloque.MANANA:
                    man = man or t
                else:
                    tar = tar or t
        # 2) Horas.
        for t in self._por_hora(s):
            if t.bloque == Turno.Bloque.MANANA:
                man = man or t
            else:
                tar = tar or t
        # 3) Ordinales atados a un bloque: "segunda de la tarde".
        ordinales = {1: r"\b(1a?|1ª|primer[ao]|primera)\b",
                     2: r"\b(2a?|2ª|segund[ao]|segunda)\b",
                     3: r"\b(3a?|3ª|tercer[ao]|tercera)\b"}
        dice_man = bool(re.search(r"\bmanana|\bmananas|\bam\b", s))
        dice_tar = bool(re.search(r"\btarde|\btardes|\bpm\b", s))
        for n, patron in ordinales.items():
            if not re.search(patron, s):
                continue
            if dice_man and man is None:
                man = self.orden.get((Turno.Bloque.MANANA, n))
            elif dice_tar and tar is None:
                tar = self.orden.get((Turno.Bloque.TARDE, n))
            elif not dice_man and not dice_tar:
                return man, tar, "ordinal_sin_bloque"
        # 4) Solo el bloque, sin turno: se resuelve luego con el resto de días.
        marca = "ok"
        if dice_man and man is None:
            marca = "manana_sin_turno"
        if dice_tar and tar is None:
            marca = "tarde_sin_turno" if marca == "ok" else "ambos_sin_turno"
        if man is None and tar is None and marca == "ok":
            return None, None, "no_entendido"
        return man, tar, marca

    def jornada(self, celda):
        """Para entrenadores: (mañana, tarde) o None si no dice nada."""
        s = norm(celda)
        if not s:
            return None
        if s in NO_ENTRENA:
            return (False, False)
        if s in VIENE_SIN_MAS or "ambas" in s or "ambos" in s or "completa" in s:
            return (True, True)
        man = bool(re.search(r"\bmanana|\bam\b|\bm[12]\b", s))
        tar = bool(re.search(r"\btarde|\bpm\b|\bt[12]\b", s))
        if not man and not tar:
            return None
        return (man, tar)


def divisiones_de(celda):
    """'1,2,3' · '1-4' · '1 a 4' · 'todas' · '2 y 3'  ->  {1,2,3,4}"""
    s = norm(celda)
    if not s or s.startswith("—") or "sin asignar" in s:
        return None
    if "todas" in s or "todo" in s:
        return set(Division.objects.values_list("nivel", flat=True))
    niveles = set()
    for a, b in re.findall(r"(\d+)\s*(?:-|a|hasta)\s*(\d+)", s):
        niveles.update(range(int(a), int(b) + 1))
    if not niveles:
        niveles = {int(n) for n in re.findall(r"\d+", s)}
    return niveles or None


def fecha_de(valor, anio_ref):
    """Acepta la fecha de Excel, '12/10/2026', '12-10-26' y '12 de octubre'."""
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    s = norm(valor)
    if not s:
        return None
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", s)
    if m:
        d, mes, a = int(m.group(1)), int(m.group(2)), m.group(3)
        anio = anio_ref if a is None else (int(a) + 2000 if len(a) == 2 else int(a))
        try:
            return dt.date(anio, mes, d)
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})\s*(?:de\s+)?([a-z]{3,})", s)
    if m and m.group(2)[:3] in MESES:
        try:
            return dt.date(anio_ref, MESES[m.group(2)[:3]], int(m.group(1)))
        except ValueError:
            return None
    return None


class Command(BaseCommand):
    help = "Importa el Excel de recogida (texto libre) y explica lo que no entiende."

    def add_arguments(self, parser):
        parser.add_argument("archivo")
        parser.add_argument("--dry-run", action="store_true",
                            help="Interpreta y da el informe, sin tocar la base.")
        parser.add_argument("--anio", type=int, default=dt.date.today().year,
                            help="Año que se asume en las fechas sin año.")

    # ------------------------------------------------------------------ #
    def handle(self, *args, **opts):
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise CommandError("Falta openpyxl (pip install openpyxl).")

        wb = load_workbook(opts["archivo"], data_only=True)
        self.dudas = []          # (hoja, fila, columna, texto, motivo)
        self.anio = opts["anio"]
        turnos = list(Turno.objects.filter(activo=True).order_by("orden"))
        if not turnos:
            raise CommandError("No hay turnos activos: revisa el curso cargado.")
        self.interprete = Interprete(turnos)
        self._jugadores_idx = {norm(j.nombre): j
                               for j in Jugador.objects.filter(activo=True)}
        self._entrenadores_idx = {norm(e.nombre): e
                                  for e in Entrenador.objects.filter(activo=True)}

        with transaction.atomic():
            r_j = self._jugadores(wb)
            r_e = self._entrenadores(wb)
            r_a = self._ausencias(wb)
            if opts["dry_run"]:
                transaction.set_rollback(True)

        self._informe(r_j, r_e, r_a, opts["dry_run"])

    def _duda(self, hoja, fila, col, texto, motivo):
        self.dudas.append((hoja, fila, col, str(texto), motivo))

    # ------------------------------------------------------------------ #
    def _jugadores(self, wb):
        if "Jugadores" not in wb.sheetnames:
            return {}
        ws = wb["Jugadores"]
        res = Counter()
        nombres = self._jugadores_idx

        for fila in ws.iter_rows(min_row=5, values_only=False):
            nombre = fila[0].value
            if not nombre:
                continue
            jug = nombres.get(norm(nombre))
            if jug is None:
                self._duda("Jugadores", fila[0].row, "A", nombre, "jugador no encontrado")
                res["sin_jugador"] += 1
                continue

            # 1) Leer los cinco días.
            lecturas = {}
            for d in DIAS_COL:
                celda = fila[6 + d]
                man, tar, marca = self.interprete.turnos_de(celda.value)
                lecturas[d] = (man, tar, marca)
                if marca == "no_entendido":
                    self._duda("Jugadores", celda.row, celda.column_letter,
                               celda.value, "no sé qué turno es")
                elif marca == "ordinal_sin_bloque":
                    self._duda("Jugadores", celda.row, celda.column_letter,
                               celda.value, "¿primera de la mañana o de la tarde?")

            # 2) Resolver los «mañana» sueltos con lo que hace el resto de días.
            habitual_m = Counter(m.id for m, _, _ in lecturas.values() if m)
            habitual_t = Counter(t.id for _, t, _ in lecturas.values() if t)
            def preferido(cont, bloque):
                if cont:
                    return Turno.objects.get(pk=cont.most_common(1)[0][0])
                candidatos = (self.interprete.manana if bloque == Turno.Bloque.MANANA
                              else self.interprete.tarde)
                return sorted(candidatos, key=lambda t: t.hora_inicio)[0]

            for d, (man, tar, marca) in lecturas.items():
                if marca in ("manana_sin_turno", "ambos_sin_turno") and man is None:
                    man = preferido(habitual_m, Turno.Bloque.MANANA)
                    res["deducido"] += 1
                if marca in ("tarde_sin_turno", "ambos_sin_turno") and tar is None:
                    tar = preferido(habitual_t, Turno.Bloque.TARDE)
                    res["deducido"] += 1
                lecturas[d] = (man, tar, marca)

            # 3) Escribir. Solo los días con respuesta: sin fila, el motor elige.
            for d, (man, tar, marca) in lecturas.items():
                if marca in ("vacio", "viene_sin_turno", "no_entendido",
                             "ordinal_sin_bloque"):
                    HorarioJugador.objects.filter(jugador=jug, dia=d).delete()
                    continue
                HorarioJugador.objects.update_or_create(
                    jugador=jug, dia=d,
                    defaults={"turno_manana": man, "turno_tarde": tar},
                )
                res["dias"] += 1
                if marca == "no_entrena":
                    res["dias_libres"] += 1

            # 4) Turno habitual en la ficha, para los días sin declarar.
            if habitual_m:
                jug.turno_manana = preferido(habitual_m, Turno.Bloque.MANANA)
            if habitual_t:
                jug.turno_tarde = preferido(habitual_t, Turno.Bloque.TARDE)

            # 5) Sesiones por semana + control contra los días declarados.
            celda_ses = fila[11]
            ses = norm(celda_ses.value)
            declaradas = sum(bool(m) + bool(t) for m, t, _ in lecturas.values())
            if ses:
                num = numero_de(ses)
                if num is not None:
                    jug.sesiones_semana = num
                    if declaradas and abs(num - declaradas) > 1:
                        self._duda("Jugadores", celda_ses.row, celda_ses.column_letter, celda_ses.value,
                                   f"dice {num} pero los días suman {declaradas}")
                else:
                    self._duda("Jugadores", celda_ses.row, celda_ses.column_letter, celda_ses.value,
                               "no es un número")
            jug.save(update_fields=["turno_manana", "turno_tarde", "sesiones_semana"])
            res["jugadores"] += 1

            self._extras(fila, jug, res)
        return res

    # ------------------------------------------------------------------ #
    def _extras(self, fila, jug, res):
        """Las columnas de la derecha: solo si aplica, casi siempre vacías."""
        # División corregida.
        div = norm(fila[3].value)
        if div:
            n = numero_de(div)
            d = Division.objects.filter(nivel=n).first() if n else None
            if d is None:
                self._duda("Jugadores", fila[3].row, "D", fila[3].value,
                           "no reconozco esa división")
            elif d != jug.division:
                jug.division = d
                jug.save(update_fields=["division"])
                res["division"] += 1

        # Responsable corregido.
        nombre = norm(fila[5].value)
        if nombre and not nombre.startswith("—"):
            ent = self._entrenador(nombre)
            if ent is None:
                self._duda("Jugadores", fila[5].row, "F", fila[5].value,
                           "ese entrenador no existe")
            else:
                ResponsableJugador.objects.filter(jugador=jug).update(activo=False)
                ResponsableJugador.objects.update_or_create(
                    jugador=jug, entrenador=ent,
                    defaults={"activo": True, "prioridad": 1},
                )
                res["responsable"] += 1

        # Pareja preferida. «a poder ser» / «si puede» lo baja a preferente.
        for nom in self._nombres(fila[12].value):
            otro = self._jugador(nom)
            if otro is None or otro.id == jug.id:
                self._duda("Jugadores", fila[12].row, "M", nom, "no encuentro a ese jugador")
                continue
            blando = re.search(r"a poder ser|si puede|preferib|mejor si", norm(fila[12].value))
            PreferenciaPareja.objects.update_or_create(
                jugador=jug, jugador_objetivo=otro,
                defaults={"tipo": PreferenciaPareja.Tipo.SOFT if blando
                          else PreferenciaPareja.Tipo.HARD, "activa": True},
            )
            res["parejas"] += 1

        # Veto.
        for nom in self._nombres(fila[13].value):
            otro = self._jugador(nom)
            if otro is None or otro.id == jug.id:
                self._duda("Jugadores", fila[13].row, "N", nom, "no encuentro a ese jugador")
                continue
            a, b = sorted([jug, otro], key=lambda x: x.id)
            Rencilla.objects.update_or_create(
                jugador_a=a, jugador_b=b,
                defaults={"activa": True, "motivo": str(fila[16].value or "")[:200]},
            )
            res["vetos"] += 1

        # Contrato de patrocinio.
        for nom in self._nombres(fila[14].value):
            ent = self._entrenador(norm(nom))
            if ent is None:
                self._duda("Jugadores", fila[14].row, "O", nom, "ese entrenador no existe")
                continue
            Contrato.objects.update_or_create(
                jugador=jug, entrenador=ent, defaults={"activo": True})
            res["contratos"] += 1

        # Superficie.
        sup = norm(fila[15].value)
        if sup:
            if "tierra" in sup or "batida" in sup:
                elegida = Pista.Superficie.TIERRA
            elif "resina" in sup or "rapid" in sup or "dura" in sup:
                elegida = Pista.Superficie.RESINA
            else:
                elegida = None
                self._duda("Jugadores", fila[15].row, "P", fila[15].value,
                           "¿tierra o resina?")
            if elegida:
                PreferenciaSuperficie.objects.update_or_create(
                    jugador=jug, superficie=elegida,
                    defaults={"estricta": "estricta" in sup or "solo" in sup})
                res["superficie"] += 1

        nota = fila[16].value
        if nota and str(nota).strip():
            self._duda("Jugadores", fila[16].row, "Q", nota, "nota para leer a mano")

    # ------------------------------------------------------------------ #
    def _nombres(self, celda):
        """'Pepe y Juan' / 'Pepe, Juan' -> ['pepe', 'juan']. Vacío -> []."""
        s = norm(celda)
        if not s or s in NO_ENTRENA:
            return []
        s = re.sub(r"\b(a poder ser|si puede|preferiblemente|mejor si|con)\b", " ", s)
        return [t.strip() for t in re.split(r",|;|\by\b|\+|/", s) if t.strip()]

    def _jugador(self, nombre):
        return self._buscar(nombre, self._jugadores_idx)

    def _entrenador(self, nombre):
        return self._buscar(nombre, self._entrenadores_idx)

    @staticmethod
    def _buscar(nombre, indice):
        """Exacto primero; si no, el único que contenga todas las palabras."""
        clave = norm(nombre)
        if clave in indice:
            return indice[clave]
        palabras = clave.split()
        if not palabras:
            return None
        candidatos = [v for k, v in indice.items()
                      if all(p in k.split() for p in palabras)]
        return candidatos[0] if len(candidatos) == 1 else None

    # ------------------------------------------------------------------ #
    def _entrenadores(self, wb):
        if "Entrenadores" not in wb.sheetnames:
            return {}
        ws = wb["Entrenadores"]
        res = Counter()
        nombres = self._entrenadores_idx

        for fila in ws.iter_rows(min_row=5, values_only=False):
            nombre = fila[0].value
            if not nombre:
                continue
            ent = nombres.get(norm(nombre))
            if ent is None:
                self._duda("Entrenadores", fila[0].row, "A", nombre, "entrenador no encontrado")
                continue

            niveles = divisiones_de(fila[2].value)
            if niveles:
                divs = list(Division.objects.filter(nivel__in=niveles))
                faltan = niveles - {d.nivel for d in divs}
                if faltan:
                    self._duda("Entrenadores", fila[2].row, "C", fila[2].value,
                               f"divisiones que no existen: {sorted(faltan)}")
                ent.divisiones_habilitadas.set(divs)
                res["divisiones"] += 1

            for d in DIAS_COL:
                celda = fila[3 + d]
                jor = self.interprete.jornada(celda.value)
                if jor is None:
                    HorarioEntrenador.objects.filter(entrenador=ent, dia=d).delete()
                    continue
                HorarioEntrenador.objects.update_or_create(
                    entrenador=ent, dia=d,
                    defaults={"manana": jor[0], "tarde": jor[1]},
                )
                res["jornada"] += 1
            nota = fila[8].value
            if nota and str(nota).strip():
                self._duda("Entrenadores", fila[8].row, "I", nota, "nota para leer a mano")
            res["entrenadores"] += 1
        return res

    # ------------------------------------------------------------------ #
    def _ausencias(self, wb):
        if "Ausencias" not in wb.sheetnames:
            return {}
        ws = wb["Ausencias"]
        res = Counter()
        jug, ent = self._jugadores_idx, self._entrenadores_idx

        for fila in ws.iter_rows(min_row=5, values_only=False):
            quien = fila[0].value
            if not quien:
                continue
            desde = fecha_de(fila[1].value, self.anio)
            hasta = fecha_de(fila[2].value, self.anio) or desde
            if desde is None:
                self._duda("Ausencias", fila[1].row, "B", fila[1].value, "no es una fecha")
                continue
            if hasta < desde:
                self._duda("Ausencias", fila[2].row, "C", fila[2].value,
                           "el «hasta» va antes que el «desde»")
                continue
            motivo = str(fila[3].value or "").strip()
            clave = norm(quien)

            if clave in jug:
                ambito = self._ambito(fila[4])
                AusenciaJugador.objects.update_or_create(
                    jugador=jug[clave], fecha_inicio=desde, fecha_fin=hasta,
                    ambito=ambito,
                    defaults={"estado": Estado.AUSENCIA_JUGADOR, "nota": motivo},
                )
                res["jugadores"] += 1
            elif clave in ent:
                VacacionesEntrenador.objects.update_or_create(
                    entrenador=ent[clave], fecha_inicio=desde, fecha_fin=hasta,
                    defaults={"motivo": motivo},
                )
                res["entrenadores"] += 1
            else:
                self._duda("Ausencias", fila[0].row, "A", quien, "no está en jugadores ni entrenadores")
        return res

    def _ambito(self, celda):
        s = norm(celda.value)
        if not s:
            return Ambito.DIA
        for cod in ("m1", "m2", "jp", "t1", "t2"):
            if re.search(rf"\b{cod}\b", s):
                return getattr(Ambito, cod.upper())
        if "manana" in s:
            return Ambito.MANANA
        if "tarde" in s:
            return Ambito.TARDE
        self._duda("Ausencias", celda.row, "E", celda.value, "no sé qué turnos afecta")
        return Ambito.DIA

    # ------------------------------------------------------------------ #
    def _informe(self, r_j, r_e, r_a, dry):
        w = self.stdout.write
        w(self.style.MIGRATE_HEADING(
            "\nLo que he entendido" + ("  (ENSAYO: nada guardado)" if dry else "")))
        w(f"  Jugadores leídos ........ {r_j.get('jugadores', 0)}")
        w(f"    días con turno ........ {r_j.get('dias', 0)}"
          f"   (de los cuales {r_j.get('dias_libres', 0)} son «no viene»)")
        w(f"    turnos deducidos ...... {r_j.get('deducido', 0)}"
          "   (decía solo «mañana»/«tarde»)")
        w(f"    divisiones corregidas . {r_j.get('division', 0)}")
        w(f"    responsables fijados .. {r_j.get('responsable', 0)}")
        w(f"    parejas / vetos ....... {r_j.get('parejas', 0)} / {r_j.get('vetos', 0)}")
        w(f"    contratos ............. {r_j.get('contratos', 0)}")
        w(f"    superficie ............ {r_j.get('superficie', 0)}")
        w(f"  Entrenadores leídos ..... {r_e.get('entrenadores', 0)}")
        w(f"    divisiones fijadas .... {r_e.get('divisiones', 0)}")
        w(f"    días de jornada ....... {r_e.get('jornada', 0)}")
        w(f"  Ausencias de jugador .... {r_a.get('jugadores', 0)}")
        w(f"  Ausencias de entrenador . {r_a.get('entrenadores', 0)}")

        if not self.dudas:
            w(self.style.SUCCESS("\nSin dudas: se entendió todo.\n"))
            return
        por_motivo = defaultdict(list)
        for hoja, f, c, texto, motivo in self.dudas:
            por_motivo[motivo].append((hoja, f, c, texto))
        w(self.style.WARNING(f"\nPara preguntar  ({len(self.dudas)} celdas)"))
        for motivo, casos in sorted(por_motivo.items(), key=lambda x: -len(x[1])):
            w(f"\n  {motivo}  ({len(casos)})")
            for hoja, f, c, texto in casos[:12]:
                w(f"    {hoja}!{c}{f}   «{texto[:60]}»")
            if len(casos) > 12:
                w(f"    … y {len(casos) - 12} más")
        w("")
