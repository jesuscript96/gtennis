"""Pone la base de datos al día con la pestaña SEPTIEMBRE del Excel.

Hace tres cosas, todas leyendo del cuadrante que la dirección ya escribe:

  1. Da de baja a los jugadores y entrenadores que no aparecen en el mes. Lo
     que había cargado venía del campus de verano y la población ha cambiado
     casi entera.

  2. Carga la PRESENCIA POR DÍA. En las columnas laterales (JUGADORES, LUNES,
     MARTES, …) la dirección ya anota quién entrena cada jornada. Es justo el
     dato de ausencias que faltaba: no hay que pedirlo, hay que leerlo. Quien
     está en el roster de la semana pero no en la columna de un día concreto,
     ese día se marca ausente.

     Solo se marcan ausencias de los días cuya columna está rellena. Una
     columna vacía significa "aún sin montar", no "no entrena nadie".

     Y la ausencia se marca SOLO POR LA MAÑANA. Comprobado contra el lunes 7:
     los 24 de la lista están los 24 en pista, y la lista cubre las franjas de
     8:30 y 10:30 (12/12 y 12/13) pero no las de tarde (0 de los 19 que
     entrenan a las 17:30). Es la lista del grupo de mañana, no del club: dar
     por ausente el día entero dejaba fuera a 60 alumnos de la escuela de
     tarde que sí entrenan.

  3. Recoge las anotaciones de horario pegadas al nombre ("Ximo Minguez 8.30",
     "Rouham solo por la mañana") y las deja en las notas del jugador, que hoy
     es donde único caben.

Uso:
    python manage.py sync_septiembre --file ~/Downloads/2026.xlsx --dry-run
    python manage.py sync_septiembre --file ~/Downloads/2026.xlsx --semana "LUNES 7"
"""
import os
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from academy.models import Entrenador, Jugador
from scheduling.models import Ambito, Disponibilidad, Estado, Semana

DIAS_COL = [1, 4, 7, 10, 13, 16]
CAB_BANDA = {"PISTA", "JUNIOR PROGRAM", "STA. BARBARA", "ALTO RENDIMIENTO",
             "INTENSIVO", "ADULTOS"}
DIAS_NOMBRE = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES"]
RUIDO = re.compile(r"no entrena|no est|^torneo|alquiler|^otra$|^libre$|entrenadores"
                   r"|grupo adultos|cubos|controles|s/r", re.I)
FUERA = {"YU", "DE", "DEL", "LA", "EL", "CHICO", "CHICA", "ANOS", "MEDIO", "DIA",
         "PRUEBA", "SOLO", "POR", "MANANA", "TARDE", "FISICO", "CALIENTA", "MIN",
         "HORA", "SAQUE", "SAQUES", "RESTO", "RESTOS", "CUBO", "CUBOS", "Y"}
# Cómo escribe la dirección algunos nombres en el cuadrante, frente a la ficha.
# Sin esto se marcaba ausente a gente que sí estaba en la lista del día.
ALIAS_CAL = {
    "MARIA ANDRIENKO": "Maria Adrienko",
    "MANU MENDEZ": "Manuel Mendez Dominguez",
    "ROUHAM": "Ruohan Xu",
    "GAO": "Yuantian Gao",
    "NATALIA VOTEA": "Natalia Ioana Botea",
}

# Anotaciones de horario que la dirección pega al nombre.
ANOT = re.compile(r"\b(?:a\s+)?\d{1,2}[.:]\d{2}\b|solo por la ma[ñn]ana|solo por la tarde"
                  r"|solo fisico|medio d[ií]a", re.I)


def _t(v):
    return "" if v is None else str(v).strip()


def clave_semana(v):
    """Clave de cabecera de semana. CONSERVA los dígitos: "LUNES 7" y
    "LUNES 31" tienen que distinguirse."""
    s = "".join(c for c in unicodedata.normalize("NFD", _t(v))
                if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Za-z0-9]", " ", s).upper().split())


def clave(nombre):
    s = "".join(c for c in unicodedata.normalize("NFD", _t(nombre))
                if unicodedata.category(c) != "Mn")
    # El paréntesis se abre, no se borra: la dirección mete ahí el nombre de
    # verdad ("Kevin (zunwen wang)"), y borrarlo dejaba la clave en "KEVIN",
    # imposible de casar con "Zunwen Wang 11". Los marcadores tipo "(Yu)" caen
    # igual porque están en FUERA.
    s = re.sub(r"[^A-Za-z ]", " ", s)
    return " ".join(w.upper() for w in s.split()
                    if len(w) > 1 and w.upper() not in FUERA)


class Command(BaseCommand):
    help = "Alinea la BD con la pestaña SEPTIEMBRE: altas, bajas y presencia diaria."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument("--hoja", default="SEPTIEMBRE")
        parser.add_argument("--semana", default=None,
                            help='Cabecera de la semana, p. ej. "LUNES 7". '
                                 "Por defecto, la última del mes.")
        parser.add_argument("--lunes", default=None,
                            help="Fecha del lunes (YYYY-MM-DD) para crear la Semana.")
        parser.add_argument(
            "--altas", action="store_true",
            help="Dar de alta a los jugadores que salen en el cuadrante del mes "
                 "y no tienen ficha (sobre todo la escuela de tarde).",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        with transaction.atomic():
            self._run(**opts)

    # -- lectura -----------------------------------------------------------
    def _hoja(self, path, hoja):
        try:
            import openpyxl
        except ImportError as exc:  # pragma: no cover
            raise CommandError("Falta openpyxl.") from exc
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            raise CommandError(f"No existe {path}")
        wb = openpyxl.load_workbook(path, data_only=True)
        if hoja not in wb.sheetnames:
            raise CommandError(f"No hay pestaña {hoja!r}. Hay: {wb.sheetnames}")
        return wb[hoja]

    def _semanas(self, ws):
        out = []
        for f in range(1, ws.max_row + 1):
            if re.match(r"LUNES\s*\d+", _t(ws.cell(f, 1).value).upper()):
                out.append((f, _t(ws.cell(f, 1).value)))
        return out

    def _perfil(self, ws, ini, fin):
        """Para cada jugador del cuadrante: cómo se le escribe, en qué franjas
        sale, cuántas veces y con qué entrenadores. Es todo lo que el Excel
        dice de alguien que aún no tiene ficha."""
        from collections import Counter as _C
        perfil = defaultdict(lambda: {"nombres": _C(), "franjas": _C(),
                                      "coaches": _C(), "sesiones": 0})
        f = ini
        while f < fin:
            if _t(ws.cell(f, 1).value).upper() in CAB_BANDA:
                hora = _t(ws.cell(f, 2).value)
                for p in range(8):
                    b = f + 1 + p * 2
                    if b + 1 > ws.max_row:
                        break
                    for c0 in DIAS_COL:
                        celdas = []
                        for rr, cc in ((b, c0), (b, c0 + 1), (b, c0 + 2),
                                       (b + 1, c0), (b + 1, c0 + 1), (b + 1, c0 + 2)):
                            v = _t(ws.cell(rr, cc).value)
                            if (not v or re.fullmatch(r"\d+(\.0)?", v)
                                    or RUIDO.search(v) or not clave(v)):
                                continue
                            celdas.append(v)
                        coaches = [v for v in celdas if v.isupper()]
                        for v in celdas:
                            if v.isupper():
                                continue
                            d = perfil[clave(v)]
                            d["nombres"][v] += 1
                            d["franjas"][hora] += 1
                            d["sesiones"] += 1
                            for co in coaches:
                                d["coaches"][co] += 1
                f += 17
                continue
            f += 1
        return perfil

    @staticmethod
    def _edad(nombre):
        """La dirección pega la edad (o el año de nacimiento) al nombre:
        "Hanyu Lin (Yu) 9", "Julian Finol 2015", "Carla Chisvert Andujar10"."""
        m = re.search(r"(?:^|[^\d])((?:19|20)\d{2})(?!\d)", nombre)
        if m:
            return max(3, min(80, date.today().year - int(m.group(1))))
        m = re.search(r"(\d{1,2})\s*(?:a[ñn]os)?\s*$", nombre.strip())
        if m and 3 <= int(m.group(1)) <= 25:
            return int(m.group(1))
        return None

    def _cuadrante(self, ws, ini, fin):
        """Nombres que aparecen en las pistas de esa semana."""
        jug, ent = Counter(), Counter()
        f = ini
        while f < fin:
            if _t(ws.cell(f, 1).value).upper() in CAB_BANDA:
                for p in range(8):
                    b = f + 1 + p * 2
                    if b + 1 > ws.max_row:
                        break
                    for c0 in DIAS_COL:
                        for rr, cc in ((b, c0), (b, c0 + 1), (b, c0 + 2),
                                       (b + 1, c0), (b + 1, c0 + 1), (b + 1, c0 + 2)):
                            v = _t(ws.cell(rr, cc).value)
                            if (not v or re.fullmatch(r"\d+(\.0)?", v)
                                    or RUIDO.search(v) or not clave(v)):
                                continue
                            (ent if v.isupper() else jug)[clave(v)] += 1
                f += 17
                continue
            f += 1
        return jug, ent

    def _presencia(self, ws, cab_fila):
        """{día: {clave: anotación}} de las columnas laterales, y el roster."""
        fila = cab_fila + 1
        cols = {}
        for c in range(18, min(ws.max_column, 40) + 1):
            v = _t(ws.cell(fila, c).value).upper()
            if v in DIAS_NOMBRE or v == "JUGADORES":
                cols[v] = c
        pres, roster = {}, {}
        for et, c in cols.items():
            vals = {}
            for f in range(fila + 1, fila + 60):
                v = _t(ws.cell(f, c).value)
                if not v:
                    continue
                k = clave(v)
                if not k or RUIDO.search(v):
                    continue
                m = ANOT.search(v)
                vals[k] = (m.group(0).strip() if m else "")
            if et == "JUGADORES":
                roster = vals
            elif vals:
                pres[DIAS_NOMBRE.index(et)] = vals
        return roster, pres

    # -- ejecución ---------------------------------------------------------
    def _run(self, **opts):
        w = self.stdout.write
        seco = opts["dry_run"]
        ws = self._hoja(opts["file"], opts["hoja"])
        semanas = self._semanas(ws)
        if not semanas:
            raise CommandError("No encuentro ninguna cabecera 'LUNES nn'.")
        if opts["semana"]:
            sel = [s for s in semanas
                   if clave_semana(s[1]) == clave_semana(opts["semana"])]
            if not sel:
                raise CommandError(f"Semanas disponibles: {[s[1] for s in semanas]}")
            cab = sel[0]
        else:
            cab = semanas[-1]
        idx_cab = semanas.index(cab)
        fin = semanas[idx_cab + 1][0] if idx_cab + 1 < len(semanas) else ws.max_row

        # Todo el mes cuenta para decidir altas y bajas.
        jug_mes, ent_mes = self._cuadrante(ws, 1, ws.max_row)
        # Dar de baja a alguien que sigue viniendo es peor que mantener a
        # alguien que se fue, así que para las bajas se barre la pestaña
        # ENTERA, no solo la rejilla de pistas: hay bloques laterales
        # (torneo, Sta. Bárbara, listas sueltas) que el lector de pistas no
        # recorre y donde también salen nombres.
        nombres_mes = set()
        for f in range(1, ws.max_row + 1):
            for c in range(1, min(ws.max_column, 40) + 1):
                v = _t(ws.cell(f, c).value)
                if v and len(v) < 60 and not RUIDO.search(v) and clave(v):
                    nombres_mes.add(clave(v))
        roster, pres = self._presencia(ws, cab[0])

        jidx, eidx = {}, {}
        for j in Jugador.objects.all():
            jidx.setdefault(clave(j.nombre), j)
        for e in Entrenador.objects.all():
            eidx.setdefault(clave(e.nombre), e)

        from difflib import SequenceMatcher

        def loc(k, idx):
            k = clave(ALIAS_CAL.get(k, k))
            if k in idx:
                return idx[k]
            tk = set(k.split())
            for kk, o in idx.items():
                tv = set(kk.split())
                if tk and tv and (tk <= tv or tv <= tk) and len(tk & tv) >= 1:
                    return o
            # El cuadrante se escribe a mano y trae erratas: "Natalia Votea"
            # por Botea, "Ojas Malhorta" por Malhotra. Sin esto se crean
            # fichas duplicadas de gente que ya está.
            mejor, sc = None, 0.0
            for kk, o in idx.items():
                r = SequenceMatcher(None, k, kk).ratio()
                if r > sc:
                    mejor, sc = o, r
            return mejor if sc >= 0.86 else None

        # -- 1. Bajas ------------------------------------------------------
        vivos_j = {loc(k, jidx).pk for k in nombres_mes if loc(k, jidx)}
        vivos_j |= {loc(k, jidx).pk for k in roster if loc(k, jidx)}
        # Los del organigrama nunca son baja, aunque no hayan salido todavía
        # en una pista. Se leen de la propia definición de los grupos, no de
        # una heurística sobre las notas.
        from academy.management.commands.aplicar_grupos import ALIAS, BLOQUES
        for bl in BLOQUES:
            for _cols, _div, jugadores in bl["columnas"]:
                for nom in jugadores:
                    j = loc(clave(ALIAS.get(clave(nom), nom)), jidx)
                    if j:
                        vivos_j.add(j.pk)
        bajas_j = [j for j in Jugador.objects.filter(activo=True) if j.pk not in vivos_j]

        vivos_e = {loc(k, eidx).pk for k in ent_mes if loc(k, eidx)}
        vivos_e |= {loc(k, eidx).pk for k in nombres_mes if loc(k, eidx)}
        vivos_e |= set(
            Entrenador.objects.filter(divisiones_habilitadas__isnull=False)
            .values_list("pk", flat=True)
        )
        bajas_e = [e for e in Entrenador.objects.filter(activo=True)
                   if e.pk not in vivos_e and not e.gestiona_todos_jugadores]
        if not seco:
            Jugador.objects.filter(pk__in=[j.pk for j in bajas_j]).update(activo=False)
            Entrenador.objects.filter(pk__in=[e.pk for e in bajas_e]).update(
                activo=False, disponible_semana=False)

        # -- 2. Presencia por día -----------------------------------------
        lunes = (date.fromisoformat(opts["lunes"]) if opts["lunes"]
                 else self._lunes_de(cab[1]))
        sem = None
        creadas = 0
        activos = list(Jugador.objects.filter(activo=True)) if seco else None
        if not seco:
            sem, _ = Semana.objects.get_or_create(fecha_inicio=lunes)
            Disponibilidad.objects.filter(semana=sem).delete()
            activos = list(Jugador.objects.filter(activo=True))
        del_roster = {loc(k, jidx) for k in roster if loc(k, jidx)}
        for dia, gente in sorted(pres.items()):
            presentes = {loc(k, jidx) for k in gente if loc(k, jidx)}
            for j in activos:
                if j in presentes:
                    continue
                creadas += 1
                if not seco:
                    Disponibilidad.objects.create(
                        semana=sem, jugador=j, dia=dia, ambito=Ambito.MANANA,
                        estado=Estado.AUSENCIA_JUGADOR, subtipo="VACACIONES",
                        nota="no figura en la lista de la mañana",
                    )

        # -- 2bis. Altas de los que salen en pista y no tienen ficha --------
        altas = []
        if opts["altas"]:
            from academy.models import Escuela
            perfil = self._perfil(ws, cab[0], fin)
            esc_tarde, _ = Escuela.objects.get_or_create(
                nombre="Escuela", defaults={"solo_central": True}
            ) if not seco else (None, False)
            esc_ar = Escuela.objects.filter(nombre="Alto Rendimiento").first()
            semanas_mes = max(1, len(semanas))
            # El mismo alumno aparece escrito de varias formas dentro del mes
            # ("Selena Yunshi Q" / "…Qi", "Andres Vivancos" / "…Vivancos Vila").
            # Se fusionan antes de crear nada, quedándose con la variante más
            # completa; si no, se dan de alta dos fichas de la misma persona.
            canon = {}
            claves = sorted(perfil, key=lambda k: (-perfil[k]["sesiones"], k))
            for a in claves:
                if a in canon:
                    continue
                canon[a] = a
                for b in claves:
                    if b == a or b in canon:
                        continue
                    ta, tb = set(a.split()), set(b.split())
                    if ((ta <= tb or tb <= ta) and len(ta & tb) >= 1) or \
                            SequenceMatcher(None, a, b).ratio() >= 0.86:
                        canon[b] = a
            fusion = defaultdict(list)
            for k, dest in canon.items():
                fusion[dest].append(k)
            for dest, ks in fusion.items():
                if len(ks) > 1:
                    base = perfil[dest]
                    for k in ks:
                        if k == dest:
                            continue
                        base["nombres"].update(perfil[k]["nombres"])
                        base["franjas"].update(perfil[k]["franjas"])
                        base["coaches"].update(perfil[k]["coaches"])
                        base["sesiones"] += perfil[k]["sesiones"]

            for k in sorted(fusion):
                d = perfil[k]
                if loc(k, jidx):
                    continue
                # El nombre más completo que usa la dirección.
                nombre = max(d["nombres"], key=lambda n: (len(n), d["nombres"][n]))
                # "Marío Gallego 10.30" → el 10.30 es una nota de horario, no
                # parte del nombre; se guarda aparte en las notas.
                horario = ANOT.search(nombre)
                nombre = ANOT.sub("", nombre).strip(" .,-") or nombre
                franja = d["franjas"].most_common(1)[0][0]
                de_tarde = not franja.startswith(("8", "9", "10", "11", "12"))
                altas.append((nombre, franja, d["sesiones"],
                              ", ".join(c for c, _ in d["coaches"].most_common(2))))
                if not seco:
                    j = Jugador.objects.create(
                        nombre=nombre,
                        edad=self._edad(nombre),
                        escuela=esc_tarde if de_tarde else esc_ar,
                        activo=True,
                        sesiones_semana=max(1, round(d["sesiones"] / semanas_mes)),
                        notas=(f"alta del cuadrante de septiembre · {franja}"
                               + (f" · {horario.group(0).strip()}" if horario else ""))[:200],
                    )
                    jidx[clave(nombre)] = j

        # -- 3. Anotaciones de horario -------------------------------------
        notas = []
        for k, an in {**roster, **{k: v for g in pres.values() for k, v in g.items()}}.items():
            if not an:
                continue
            j = loc(k, jidx)
            if j:
                notas.append((j.nombre, an))
                if not seco and an.lower() not in (j.notas or "").lower():
                    j.notas = (f"{j.notas} · {an}" if j.notas else an)[:200]
                    j.save(update_fields=["notas"])

        # -- informe --------------------------------------------------------
        w(self.style.MIGRATE_HEADING(f"\nSemana {cab[1]} (lunes {lunes})"))
        w(f"  roster de la semana: {len(roster)} jugadores")
        for d in range(5):
            g = pres.get(d)
            w(f"    {DIAS_NOMBRE[d]:10s} " +
              (f"{len(g):>3} presentes" if g else "  — sin montar todavía"))
        w(self.style.MIGRATE_HEADING(f"\nBAJAS ({len(bajas_j)} jugadores, {len(bajas_e)} entrenadores)"))
        w("  jugadores: " + (", ".join(sorted(j.nombre for j in bajas_j)) or "—"))
        w("  entrenadores: " + (", ".join(sorted(e.nombre for e in bajas_e)) or "—"))
        con_login = [e for e in bajas_e if e.user_id]
        if con_login:
            w(self.style.WARNING(
                "  ⚠ con usuario para entrar en la app: "
                + ", ".join(f"{e.nombre} ({e.user.username})" for e in con_login)
                + " — se desactivan, pero el usuario sigue existiendo."))
        w(self.style.MIGRATE_HEADING(f"\nAUSENCIAS DE MAÑANA CARGADAS: {creadas}"))
        w(f"  sobre {len(pres)} días con lista escrita · "
          f"{len(activos or [])} jugadores activos")
        w("  la tarde no se toca: la lista lateral solo cubre el grupo de mañana.")
        sin_ficha = sorted({k for g in [roster] + list(pres.values())
                            for k in g if not loc(k, jidx)})
        if sin_ficha:
            w(self.style.WARNING(
                f"\nEN LA LISTA DE LA SEMANA PERO SIN FICHA ({len(sin_ficha)})"))
            w("  " + ", ".join(sin_ficha) + "  → hay que darlos de alta")
        if opts["altas"]:
            w(self.style.MIGRATE_HEADING(f"\nALTAS DESDE EL CUADRANTE ({len(altas)})"))
            w(f'  {"jugador":34s} {"franja":14s} {"ses.":>5}  entrenadores')
            for n, fr, ses, co in altas:
                w(f"  {n[:33]:34s} {fr:14s} {ses:>5}  {co}")
            w(self.style.WARNING(
                "  Se crean SIN división: no la tengo y estimarla ha demostrado "
                "no valer (0/6 y 2/8 aciertos contra la tabla real de septiembre)."))
        w(self.style.MIGRATE_HEADING(f"\nANOTACIONES DE HORARIO ({len(notas)})"))
        for n, a in sorted(set(notas)):
            w(f"  {n:34s} {a}")
        if seco:
            w(self.style.WARNING("\n(dry-run: no se ha escrito nada)"))
            transaction.set_rollback(True)

    @staticmethod
    def _lunes_de(cabecera):
        """'LUNES 7' → el lunes 7 del mes en curso."""
        m = re.search(r"\d+", cabecera)
        hoy = date.today()
        dia = int(m.group(0)) if m else hoy.day
        try:
            return date(hoy.year, hoy.month, dia)
        except ValueError:
            return hoy - timedelta(days=hoy.weekday())
