"""Paso 1: extraer del Excel de calendario todas las entradas crudas, con semana, fuente y fila.

Tipos de registro:
  conv   = torneo con jugadores (o con coach) asignados en esa semana
  opcion = torneo que figura en el calendario de un grupo sin jugadores asignados
  activ  = no es torneo (entreno, lesión, equipos, exámenes, vacaciones...)
"""
import datetime as dt
import json
import re
import openpyxl
from openpyxl.utils import get_column_letter as L

SRC = "/Users/jvch/Downloads/CALENDARIO 2026 (2).xlsx"
OUT = "/private/tmp/claude-501/-Users-jvch-Desktop-AutomatoWebs-GTennis/a7ac7fa3-9e9e-4f68-b12b-3599a6ea7cc8/scratchpad/tor/raw.json"

wb = openpyxl.load_workbook(SRC, data_only=True)
records = []
notes = []  # incidencias detectadas al extraer


def monday(d):
    return (d - dt.timedelta(days=d.weekday())).date() if isinstance(d, dt.datetime) else d - dt.timedelta(days=d.weekday())


def s(v):
    if v is None:
        return ""
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d")
    return re.sub(r"\s+", " ", str(v).replace("\n", " / ")).strip()


ACTIV = re.compile(r"^(-\s*)?(ENTRENAMIENTO|ENTRENO|EQUIPOS|LESION|LESIÓN|DESCANSO|VACACIONES|EXAMENES|EXÁMENES|NADA|"
                   r"NO VA A ESTAR|SALIDA DE GTENNIS|ALEMANIA FAMILIA|EMPEZO|EMPEZÓ|DANI HIJOS)", re.I)


def is_activ(t):
    return bool(ACTIV.match(t.strip()))


def add(kind, sheet, row, col, week, torneo, **kw):
    r = dict(kind=kind, sheet=sheet, row=row, col=col, week=str(week) if week else None, torneo=torneo)
    r.update(kw)
    records.append(r)


def week_map_list(ws, col="B"):
    """Semana de cada fila en hojas-lista: celda de fecha en `col`, extendida por su rango combinado."""
    wk = {}
    for rng in ws.merged_cells.ranges:
        if L(rng.min_col) == col:
            v = ws[f"{col}{rng.min_row}"].value
            if isinstance(v, dt.datetime):
                for r in range(rng.min_row, rng.max_row + 1):
                    wk[r] = v
    last = None
    out = {}
    for r in range(1, ws.max_row + 1):
        v = ws[f"{col}{r}"].value
        if isinstance(v, dt.datetime):
            last = v
        elif r in wk:
            last = wk[r]
        out[r] = last
    return out


def fix_week(sheet, row, d, prev):
    """Corrige fechas de semana imposibles (día/mes invertido) y devuelve lunes."""
    if d is None:
        return None
    m = monday(d)
    if prev and m < prev and d.day <= 12:
        swapped = dt.date(d.year, d.day, d.month)
        if swapped >= prev:
            notes.append(dict(tipo="Fecha de semana corregida", sheet=sheet, row=row,
                              detalle=f"«{d:%d/%m/%Y}» está fuera de orden; se interpreta como {swapped:%d/%m/%Y} (día y mes invertidos)."))
            return monday(swapped)
    return m


# ---------------------------------------------------------------- hojas-lista (torneo / cierre / coach / jugadores)
def parse_list(sheet, c_tor="C", c_cie="D", c_coach="E", c_pl="F", first=3, last=None, player_cols=None):
    ws = wb[sheet]
    wm = week_map_list(ws)
    prev = None
    fixed = {}
    for r in range(first, (last or ws.max_row) + 1):
        d = wm.get(r)
        if d is None:
            continue
        if d not in fixed:
            fixed[d] = fix_week(sheet, r, d, prev)
        m = fixed[d]
        prev = m if (prev is None or m > prev) else prev
        tor = s(ws[f"{c_tor}{r}"].value)
        cie = ws[f"{c_cie}{r}"].value
        coach = s(ws[f"{c_coach}{r}"].value)
        pl = s(ws[f"{c_pl}{r}"].value)
        extra = []
        if player_cols:
            for c, name in player_cols.items():
                v = s(ws[f"{c}{r}"].value)
                if v:
                    extra.append((c, name, v))
        if not tor and not pl and not coach and not extra:
            continue
        if not tor and pl:
            # jugadores en una fila sin torneo: pertenecen al torneo de la fila anterior
            add("cont", sheet, r, c_pl, m.isoformat(), None, players_raw=pl)
            continue
        kind = "activ" if is_activ(tor) else ("conv" if (pl or coach) else "opcion")
        add(kind, sheet, r, c_tor, m.isoformat(), tor, cierre=s(cie), coach_raw=coach, players_raw=pl,
            coach_role="acompaña")
        for c, name, v in extra:
            add("activ" if is_activ(v) else "cell", sheet, r, c, m.isoformat(), v, player_col=name,
                row_torneo=tor, coach_raw=coach, coach_role="acompaña")


parse_list("DISTRIBUCION CALENDARIO TODO")
parse_list("GRUPO PABLO")
# Salva: filas 3-30 son 2026 (ene-feb); de la 31 en adelante son restos de 2025 → se separan
parse_list("GRUPO SALVA", first=5, last=30)
SANTI_P = {"F": "HUAQUI LI", "G": "NIK", "H": "EUGENIA", "I": "VICTORIA", "J": "DANIEL", "K": "YASHVARDHAN",
           "L": "MARIA RUIZ", "M": "AARISH", "N": "VIRAJ", "O": "NATALIA BOTEA", "P": "ELENE CHURRUCA",
           "Q": "VALERIA BOKOVA", "R": "JINXUAN LIAO", "S": "RUTH MOSCARDO", "T": "BERNARDO"}
parse_list("GRUPO SANTI", c_pl="ZZ", player_cols=SANTI_P)

# restos de 2025 en la hoja de Salva (para anexo)
ws = wb["GRUPO SALVA"]
wm = week_map_list(ws)
for r in [3, 4] + list(range(31, ws.max_row + 1)):
    d = wm.get(r)
    tor = s(ws[f"C{r}"].value)
    if d and tor:
        add("y2025", "GRUPO SALVA", r, "C", monday(d).isoformat(), tor, cierre=s(ws[f"D{r}"].value),
            coach_raw=s(ws[f"E{r}"].value), players_raw=s(ws[f"F{r}"].value))

# ---------------------------------------------------------------- Víctor M. (semanas en texto)
MES = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
       "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12}
ws = wb["GRUPO VICTOR M."]
VM_P = {"C": "MARCOS ROMERO", "D": "VICENT BAIXAULI", "E": "DAVID CASTILLO", "F": "ERIC BADENES",
        "G": "MARTA CRESPO", "H": "VALERIA BOKOVA"}
cur = None
for r in range(3, ws.max_row + 1):
    a = s(ws[f"A{r}"].value)
    m = re.match(r"(\d{1,2})\s+([A-ZÁÉÍÓÚ]+)\s*-", a.upper())
    if m:
        cur = monday(dt.date(2026, MES[m.group(2)], int(m.group(1))))
    tor = s(ws[f"B{r}"].value)
    if not tor or cur is None:
        continue
    pls = [(c, n) for c, n in VM_P.items() if s(ws[f"{c}{r}"].value)]
    add("conv" if pls else "opcion", "GRUPO VICTOR M.", r, "B", cur.isoformat(), tor,
        players_raw=" - ".join(n for _, n in pls), coach_raw="VICTOR M.", coach_role="responsable")

# ---------------------------------------------------------------- Álvaro (fechas sueltas y en texto)
ALV_DATE = {  # fila -> fecha de referencia (se lleva al lunes de su semana)
    5: "2026-01-02", 13: "2026-02-14", 17: "2026-03-02", 21: "2026-03-16", 27: "2026-03-30", 30: "2026-04-04",
    37: "2026-05-01", 40: "2026-05-02", 45: "2026-05-09", 52: "2026-05-23", 58: "2026-06-06", 59: "2026-06-13",
    66: "2026-06-22", 73: "2026-07-04", 75: "2026-07-06", 77: "2026-07-14", 78: "2026-07-13", 81: "2026-07-20",
    83: "2026-07-27", 84: "2026-07-27", 85: "2026-08-01", 94: "2026-08-31", 95: "2026-09-05", 100: "2026-09-23",
    102: "2026-10-03", 111: "2026-10-31", 112: "2026-11-01", 117: "2026-11-21", 118: "2026-11-28", 119: "2026-12-05",
    10: "2026-02-02",  # «2002-02-02»: año mal escrito
}
# filas compuestas: el nombre del torneo está repartido en varias filas
ALV_OVR = {22: ("MARCA SLAM CARLET (SUB 16 Y 18)", "2026-03-16"),
           28: ("MARCA CHALLENGE VALENCIA TENNIS CENTER (SUB 12-18)", "2026-03-30"),
           38: ("MARCA SLAM ALICANTE FERRERO TENNIS ACADEMY (SUB 16 Y 18)", "2026-05-11"),
           53: ("AS YOUNG TOUR CLUB DE CAMP BIXQUERT XATIVA 25-31 MAYO", "2026-05-25")}
ALV_SKIP = {21, 27, 29, 37, 39, 54, 72}  # rótulos de fechas o filas de detalle
ws = wb["ALVARO"]
cur = None
for r in range(5, 124):
    a = ws[f"A{r}"].value
    if r in ALV_DATE:
        cur = monday(dt.date.fromisoformat(ALV_DATE[r]))
        if r == 10:
            notes.append(dict(tipo="Fecha de semana corregida", sheet="ALVARO", row=10,
                              detalle="«02/02/2002»: año mal escrito; se toma 02/02/2026."))
    elif isinstance(a, dt.datetime):
        cur = monday(a)
    tor = s(ws[f"B{r}"].value)
    if r in ALV_SKIP or not tor or cur is None:
        continue
    wk = cur
    if r in ALV_OVR:
        tor, w = ALV_OVR[r]
        wk = dt.date.fromisoformat(w)
    coach = s(ws[f"D{r}"].value)
    if re.search(r"\d{2}\.\d{2}\.\d{4}|semana|TODAS", coach, re.I):
        coach = ""  # en esta hoja la columna D a veces lleva fechas o categorías, no coach
    pl = s(ws[f"E{r}"].value)
    if re.fullmatch(r"(SUB-\d+,?\s*)+", pl.replace(" ", ""), re.I) or pl.upper().startswith("SUB-"):
        pl = ""  # son categorías, no jugadores
    add("conv" if (pl or coach) else "opcion", "ALVARO", r, "B", wk.isoformat(), tor,
        cierre=s(ws[f"C{r}"].value), coach_raw=coach, players_raw=pl, coach_role="acompaña")
notes.append(dict(tipo="Fuera de 2026", sheet="ALVARO", row=124,
                  detalle="«WARRIOR CIUDAD DE LA RAQUETA 1-9» aparece tras la fila del 01/01/2027: se entiende enero de 2027 y no se incluye."))
for r in range(320, ws.max_row + 1):
    tor = s(ws[f"B{r}"].value)
    if tor:
        add("y2025", "ALVARO", r, "B", None, tor, cierre=s(ws[f"C{r}"].value), coach_raw=s(ws[f"D{r}"].value),
            players_raw=s(ws[f"E{r}"].value))


# ---------------------------------------------------------------- hojas-rejilla (una columna por jugador)
def grid_week(v):
    if isinstance(v, dt.datetime):
        return monday(v)
    t = s(v)
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", t)
    if m:
        d = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if d.year == 2025 and d.month == 1:  # «ENERO 1/01/2025»: rótulo de plantilla, la semana es la de 2026
            return None
        return monday(d)
    m = re.match(r"MARZO 02-03", t)
    if m:
        return dt.date(2026, 3, 2)
    return None


def parse_grid(sheet, menu, players, coach_by_col, cat_by_col=None, prefix_by_col=None, default_coach=None):
    ws = wb[sheet]
    for r in range(3, 56):
        w = grid_week(ws[f"A{r}"].value)
        if w is None or w.year != 2026:
            continue
        for c, cat in menu.items():
            for part in re.split(r"\s/\s", s(ws[f"{c}{r}"].value)):
                part = part.strip(" -/")
                if part and not is_activ(part):
                    add("opcion", sheet, r, c, w.isoformat(), part, categoria_col=cat)
        for c, pname in players.items():
            v = s(ws[f"{c}{r}"].value)
            if not v:
                continue
            coach = coach_by_col.get(c, default_coach) or ""
            if re.search(r"vuelta|vuelo|salir |a jerez|sudamerica|^carla$", v, re.I):
                add("activ", sheet, r, c, w.isoformat(), "Nota: " + v.strip('" '), player_col=pname,
                    coach_raw=coach, coach_role="responsable")
                continue
            parts = [p.strip(" -/") for p in re.split(r"\s/\s", v) if p.strip(" -/")]
            for p in parts:
                tor = (prefix_by_col[c] + " " + p) if prefix_by_col and c in prefix_by_col else p
                add("activ" if is_activ(p) else "cell", sheet, r, c, w.isoformat(), tor, player_col=pname,
                    coach_raw=coach, coach_role="responsable", categoria_col=(cat_by_col or {}).get(c))


parse_grid("Grupo ATPChgFutures",
           menu={"B": "ATP", "C": "CHALLENGER", "D": "FUTURE", "E": "FUTURE CHICAS"},
           players={"F": "CARLOS TABERNER", "G": "CARLOS SANCHEZ", "H": "RAUL BRANCACCIO", "I": "CARLOS LOPEZ",
                    "J": "YANAKI MILEV", "K": "NACHO PARISCA", "L": "CARLES CORDOBA", "M": "TOPRAK",
                    "N": "ALEX GARCIA", "O": "MARC MARTIN", "P": "FERMIN BARCALA", "Q": "SERGIO PLANELLA",
                    "R": "MATEO ALVAREZ", "S": "MARIA ANDRIENKO", "T": "LUCCA HELGUERA", "U": "ANDRES SANTAMARTA",
                    "V": "PABLO LLAMAS"},
           coach_by_col={"F": "DANI G.", "G": "MARCOS E.", "H": "VICTOR R.", "I": "EMILIO S.", "J": "MARIO",
                         "K": "EMILIO", "L": "IVAN G.", "M": "BLAS", "N": "JAVI G.", "V": "SERGIO G."})
parse_grid("Grupo Futures",
           menu={"B": "FUTURE", "C": "ITF JUNIOR", "D": "CHALLENGER"},
           players={"E": "ANDRES SANTAMARTA", "F": "NACHO PARISCA", "G": "CARLES CORDOBA", "H": "LUCCA HELGUERA",
                    "I": "SERGIO PLANELLA", "J": "MATEO ALVAREZ", "K": "BARRY"},
           coach_by_col={"E": "DANI G.", "F": "IVAN", "G": "SERGIO", "H": "JAVI", "I": "MARIO", "J": "EMILIO",
                         "K": "VICTOR R."})
parse_grid("GRUPO SALVA 2",
           menu={"B": "ITF J30 Y J60", "C": "MARCAS", "D": "YOUNG TENNIS TOUR", "E": "CHAMPIONS CUP",
                 "F": "OTROS TORNEOS", "G": "CHALLENGER"},
           players={"H": "NACHO MARTINEZ", "I": "ANTONIO CAMPOY", "J": "ANDY LIU", "K": "OMAR",
                    "L": "TOMAS LAZARO", "M": "RODRIGO LOPEZ", "N": "ROHIN"},
           coach_by_col={}, default_coach="SALVA")
parse_grid("GRUPO JORGE", menu={"B": "RAFA NADAL", "C": "ITF JUNIOR", "D": "OTROS"},
           players={"E": "VICTORIA SCHNEIDER"}, coach_by_col={"E": "JORGE IBAÑEZ"})
parse_grid("Grupo Mario", menu={"B": "ITF JUNIOR", "C": "NACIONALES", "D": "FUTURES"},
           players={"E": "?COL_E", "F": "?COL_F", "G": "?COL_G", "H": "?COL_H", "I": "CHRISTIAN BORRIELLO"},
           coach_by_col={}, default_coach="MARIO")
NC = {"B": "COPA FAULCOMBRIDGE", "C": "MARCA", "D": "CHAMPIONS CUP", "E": "RAFA NADAL TOUR", "F": "TTK WARRIORS",
      "G": "YOUNG TENNIS", "H": "OTROS"}
parse_grid("NACHO CALVO", menu={}, players={c: "BONNIE" for c in NC}, coach_by_col={}, default_coach="NACHO CALVO",
           prefix_by_col={c: v for c, v in NC.items() if c != "H"}, cat_by_col=NC)

json.dump(dict(records=records, notes=notes), open(OUT, "w"), ensure_ascii=False, indent=1)
from collections import Counter
print(len(records), Counter(r["kind"] for r in records), len(notes))
