"""Carga el calendario de torneos desde el Excel «datos limpios».

    python manage.py cargar_calendario_torneos [ruta.xlsx] [--reset]

Lee las pestañas «Calendario completo» (todos los torneos, también los que no
tienen jugadores), «Semana a semana» (coach que acompaña, notas) y «Jugador ×
torneo» (quién va, con qué certeza). Un torneo que aparece varias semanas
seguidas con el mismo nombre se funde en una sola fila con el tramo completo.
Los nombres se cruzan con las fichas de la academia cuando coinciden.
"""
import datetime as dt
import re
import unicodedata
from collections import defaultdict

import openpyxl
from django.core.management.base import BaseCommand
from django.db import transaction

from academy.models import Entrenador, Jugador
from torneos.models import Participante, Torneo

DEFAULT = "/Users/jvch/Desktop/GTennis/docs/GTenis - Calendario de torneos 2026 (datos limpios).xlsx"
MESES = {m: i + 1 for i, m in enumerate(
    ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"])}
MESES["sept"] = 9
ALIAS_JUGADOR = {
    "Jennie Zhang": "Jennie Zhangyi Ji (Yu)", "Han Yu Lin": "Hanyu Lin (Yu) 9", "Ia Teporoca": "Ia Teporaca",
    "María Andrienko": "Maria Adrienko", "Ximo Mínguez": "Chimo Minguez Ribera",
    "Zunwen Wang (Kevin)": "Kevin (zunwen wang)", "Edgar Rouge": "Edgar Rouget Luchaire 15",
}
NOTAS_COACH = {"sin acompañante", "sí con coach (sin nombre)", "si con coach (sin nombre)", "no va coach"}


def fold(t):
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 ]", " ", t)).strip().upper()


def tokens(nombre):
    """Tokens del nombre sin paréntesis, números ni muletillas («medio día»)."""
    base = re.sub(r"\(.*?\)", " ", str(nombre or ""))
    base = re.sub(r"\d+\s*(años|anos)?", " ", base, flags=re.I)
    return [t for t in fold(base).split() if len(t) > 1 and t not in {"DE", "DEL", "LA", "Y"}]


def d(v):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v.strip()):
        return dt.date.fromisoformat(v.strip())
    return None


def parse_cierre(txt, semana):
    """«21/12/2025 / 26/12/2025» → la fecha más cercana al torneo (la primera).
    Corrige el año copiado de la plantilla (2025 para un torneo de 2026)."""
    if not txt:
        return None
    fechas = []
    for m in re.finditer(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(txt)):
        try:
            f = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            continue
        if semana and f < semana - dt.timedelta(days=300):
            f = f.replace(year=f.year + 1)
        fechas.append(f)
    return min(fechas) if fechas else None


def _mes(tok):
    tok = fold(tok).lower()[:4]
    return MESES.get(tok[:3]) if tok[:3] in MESES else None


def parse_fechas_nombre(nombre, lunes, domingo):
    """Intenta sacar «del X al Y» del propio nombre («Warriors Madrid 2 - 9 Enero»,
    «14 Feb - 9 Mar», «del 16 al 24 de mayo», «28-03 al 05-04», «28 29 30»).
    Devuelve (inicio, fin) solo si cuadra con las semanas en que aparece."""
    n = fold(nombre)
    anio = lunes.year
    cand = []
    # 2 - 9 ENERO | 22 - 29 JUNIO | 6 - 8 FEBRERO | 20 - 28 ABRIL
    for m in re.finditer(r"\b(\d{1,2})\s+(\d{1,2})\s+([A-Z]{3,10})\b", n):
        mes = _mes(m.group(3))
        if mes:
            cand.append((int(m.group(1)), mes, int(m.group(2)), mes))
    # 14 FEB - 9 MAR | 30 MAY - 21 JUN | 31 AGO - 6 SEP | 16 ENE - 8 FEB
    for m in re.finditer(r"\b(\d{1,2})\s+([A-Z]{3,10})\s+(\d{1,2})\s+([A-Z]{3,10})\b", n):
        m1, m2 = _mes(m.group(2)), _mes(m.group(4))
        if m1 and m2:
            cand.append((int(m.group(1)), m1, int(m.group(3)), m2))
    # DEL 16 AL 24 DE MAYO
    for m in re.finditer(r"\bDEL\s+(\d{1,2})\s+AL\s+(\d{1,2})\s+DE\s+([A-Z]{3,10})\b", n):
        mes = _mes(m.group(3))
        if mes:
            cand.append((int(m.group(1)), mes, int(m.group(2)), mes))
    # 07 MAR AL 22 03 | 28 03 AL 05 04 (los guiones ya son espacios tras fold)
    for m in re.finditer(r"\b(\d{1,2})\s+([A-Z]{3,10}|\d{1,2})\s+AL\s+(\d{1,2})\s+(\d{1,2})\b", n):
        m1 = _mes(m.group(2)) if not m.group(2).isdigit() else int(m.group(2))
        if m1:
            cand.append((int(m.group(1)), m1, int(m.group(3)), int(m.group(4))))
    # 28 29 30 | 30 31 1 | 4 5 6 | 13 - 15 | 30 - 3 (sin mes: el de la semana)
    for m in re.finditer(r"\b(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\b", n):
        a, c = int(m.group(1)), int(m.group(3))
        cand.append((a, lunes.month, c, lunes.month if c >= a else lunes.month + 1))
    for m in re.finditer(r"\b(\d{1,2})\s+(\d{1,2})\b(?!\s+[A-Z]{3})(?!\s+\d)", n):
        a, c = int(m.group(1)), int(m.group(2))
        if 1 <= a <= 31 and 1 <= c <= 31:
            cand.append((a, lunes.month, c, lunes.month if c >= a else lunes.month + 1))
    for da, ma, db, mb in cand:
        try:
            ya = anio if ma >= lunes.month - 1 else anio + 1
            if ma == 12 and lunes.month == 1:
                ya = anio - 1
            ini = dt.date(ya, ma, da)
            yb = ini.year + (1 if mb < ma else 0)
            fin = dt.date(yb, mb if 1 <= mb <= 12 else 1, db)
        except ValueError:
            continue
        if fin < ini or (fin - ini).days > 60:
            continue
        # Tiene que solapar con las semanas en que lo apunta el Excel.
        if ini <= domingo + dt.timedelta(days=2) and fin >= lunes - dt.timedelta(days=2):
            return ini, fin
    return None


class Command(BaseCommand):
    help = "Carga los torneos del Excel limpio en el módulo de torneos."

    def add_arguments(self, parser):
        parser.add_argument("ruta", nargs="?", default=DEFAULT)
        parser.add_argument("--reset", action="store_true",
                            help="Borra antes los torneos cargados del Excel (no los dados de alta en la app).")

    def handle(self, ruta, reset, **kw):
        wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)

        def filas(hoja, saltar=0):
            rows = list(wb[hoja].iter_rows(values_only=True))[saltar:]
            head = [str(h or "").strip() for h in rows[0]]
            return [dict(zip(head, r)) for r in rows[1:] if any(v is not None for v in r)]

        completo = filas("Calendario completo")
        semanas = {(d(r["Lunes"]), r["Torneo"]): r for r in filas("Semana a semana")}
        jug = defaultdict(list)
        for r in filas("Jugador × torneo"):
            jug[(d(r["Lunes"]), r["Torneo"])].append(r)

        # --- índices de la academia ------------------------------------
        jugadores = list(Jugador.objects.all())
        idx_j = [(set(tokens(j.nombre)), j) for j in jugadores]
        entrenadores = list(Entrenador.objects.all())
        idx_e = [(set(tokens(e.nombre)), e) for e in entrenadores]
        cache_j, cache_e = {}, {}

        def match(nombre, idx, cache):
            if nombre in cache:
                return cache[nombre]
            toks = set(tokens(nombre))
            if nombre in ALIAS_JUGADOR:
                toks = set(fold(ALIAS_JUGADOR[nombre]).split())
                exactos = [o for t, o in idx if set(fold(o.nombre).split()) == toks]
                cache[nombre] = exactos[0] if exactos else None
                return cache[nombre]
            if not toks:
                cache[nombre] = None
                return None
            exactos = [o for t, o in idx if t == toks]
            if len(exactos) == 1:
                cache[nombre] = exactos[0]
                return exactos[0]
            # Todos los tokens del Excel están en la ficha («Amparo Gil» ⊂ «Amparo Gil Pitarque»)
            sub = [o for t, o in idx if toks <= t]
            if len(sub) == 1:
                cache[nombre] = sub[0]
                return sub[0]
            # Ficha más corta dentro del nombre del Excel («Eugenia Álvarez Santiago» vs «Eugenia Alvarez»)
            sup = [o for t, o in idx if t and t <= toks]
            if len(sup) == 1:
                cache[nombre] = sup[0]
                return sup[0]
            # Activos primero si hay empate
            if len(sub) > 1:
                act = [o for o in sub if getattr(o, "activo", True)]
                if len(act) == 1:
                    cache[nombre] = act[0]
                    return act[0]
            cache[nombre] = None
            return None

        # --- agrupar semanas consecutivas del mismo torneo ----------------
        por_nombre = defaultdict(list)
        for r in completo:
            por_nombre[r["Torneo"]].append(r)
        grupos = []
        for nombre, rs in por_nombre.items():
            rs.sort(key=lambda r: d(r["Lunes"]))
            actual = [rs[0]]
            for r in rs[1:]:
                if (d(r["Lunes"]) - d(actual[-1]["Lunes"])).days <= 7:
                    actual.append(r)
                else:
                    grupos.append((nombre, actual))
                    actual = [r]
            grupos.append((nombre, actual))

        if reset:
            n, _ = Torneo.objects.exclude(fuente="Dado de alta en la app").delete()
            self.stdout.write(f"Borrados {n} registros anteriores.")

        creados = 0
        sin_jugador, sin_coach = defaultdict(int), defaultdict(int)
        fechas_del_nombre = 0
        with transaction.atomic():
            for nombre, rs in grupos:
                lunes = d(rs[0]["Lunes"])
                domingo = d(rs[-1]["Lunes"]) + dt.timedelta(days=6)
                rango = parse_fechas_nombre(nombre, lunes, domingo)
                if rango:
                    ini, fin = rango
                    fechas_del_nombre += 1
                else:
                    ini, fin = lunes, domingo
                cierres = [parse_cierre(r.get("Cierre inscripción"), d(r["Lunes"])) for r in rs]
                cierres = [c for c in cierres if c]
                fuentes, alias, notas, coaches_txt = [], [], [], []
                for r in rs:
                    if r.get("Fuente"):
                        fuentes.append(str(r["Fuente"]))
                    if r.get("También escrito como"):
                        alias.append(str(r["También escrito como"]))
                    s = semanas.get((d(r["Lunes"]), nombre))
                    if s:
                        if s.get("Notas del Excel"):
                            notas.append(str(s["Notas del Excel"]))
                        if s.get("Coach que acompaña"):
                            txt = str(s["Coach que acompaña"]).replace("Sí, con coach", "Sí con coach")
                            coaches_txt += [c.strip() for c in txt.split(",") if c.strip()]
                acomp, notas_coach = [], []
                for c in dict.fromkeys(coaches_txt):
                    if c.lower() in NOTAS_COACH:
                        notas_coach.append(c)
                        continue
                    e = match(c, idx_e, cache_e)
                    if e:
                        acomp.append(e)
                    else:
                        sin_coach[c] += 1
                        notas_coach.append(c)
                t = Torneo.objects.create(
                    nombre=str(nombre).strip(), circuito=str(rs[0].get("Circuito") or "").strip(),
                    solo_fines_semana=bool(re.search(r"fin(es)? de semana|\bfinde\b", str(nombre), re.I)),
                    fecha_inicio=ini, fecha_fin=fin, cierre_inscripcion=min(cierres) if cierres else None,
                    acompanante_nota=", ".join(dict.fromkeys(notas_coach))[:120],
                    notas=" · ".join(dict.fromkeys(notas)),
                    fuente=", ".join(dict.fromkeys(fuentes))[:300],
                    alias=" | ".join(dict.fromkeys(alias))[:300],
                )
                if acomp:
                    t.acompanantes.set(acomp)
                vistos = {}
                for r in rs:
                    for p in jug.get((d(r["Lunes"]), nombre), []):
                        nom = str(p["Jugador"]).strip()
                        cert = str(p.get("Certeza") or "confirmado").lower()
                        if cert.startswith("deducido"):
                            certeza = Participante.Certeza.DEDUCIDO
                        elif "pendiente" in cert or "sin identificar" in cert:
                            certeza = Participante.Certeza.PENDIENTE
                        else:
                            certeza = Participante.Certeza.CONFIRMADO
                        prev = vistos.get(nom)
                        if prev:
                            # Confirmado gana a deducido/pendiente si aparece varias semanas.
                            if certeza == Participante.Certeza.CONFIRMADO:
                                prev.certeza = certeza
                            continue
                        j = match(nom, idx_j, cache_j)
                        if j is None:
                            sin_jugador[nom] += 1
                        vistos[nom] = Participante(
                            torneo=t, jugador=j, nombre=nom, certeza=certeza,
                            entrenador_ref=str(p.get("Entrenador de referencia") or "")[:120],
                            detalle=str(p.get("Detalle") or "")[:200],
                        )
                Participante.objects.bulk_create(vistos.values())
                creados += 1

        self.stdout.write(self.style.SUCCESS(
            f"{creados} torneos creados ({fechas_del_nombre} con fechas leídas del nombre), "
            f"{Participante.objects.count()} participaciones; "
            f"{Participante.objects.filter(jugador__isnull=False).count()} enlazadas a fichas."))
        if sin_jugador:
            self.stdout.write(f"Jugadores sin ficha en la academia ({len(sin_jugador)}): "
                              + ", ".join(sorted(sin_jugador)))
        if sin_coach:
            self.stdout.write("Coaches sin ficha: " + ", ".join(sorted(sin_coach)))
