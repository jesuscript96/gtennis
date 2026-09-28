import datetime as dt
from collections import defaultdict, Counter
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle,
                                PageBreak, KeepTogether, NextPageTemplate, CondPageBreak)
from common import *

OUT = "/Users/jvch/Desktop/GTennis/docs/GTenis - Calendario de torneos 2026 semana a semana.pdf"
FD = "/System/Library/Fonts/Supplemental/"
pdfmetrics.registerFont(TTFont("A", FD + "Arial.ttf"))
pdfmetrics.registerFont(TTFont("A-B", FD + "Arial Bold.ttf"))
pdfmetrics.registerFont(TTFont("A-I", FD + "Arial Italic.ttf"))
pdfmetrics.registerFont(TTFont("A-BI", FD + "Arial Bold Italic.ttf"))
addMapping("A", 0, 0, "A"); addMapping("A", 1, 0, "A-B"); addMapping("A", 0, 1, "A-I"); addMapping("A", 1, 1, "A-BI")

INK = colors.HexColor("#1d2a24"); MUTED = colors.HexColor("#5d6b64"); ACCENT = colors.HexColor("#1f6f4a")
SOFT = colors.HexColor("#e7f2ec"); RULE = colors.HexColor("#d5ddd8"); WARN = colors.HexColor("#a2611a")
WARN_SOFT = colors.HexColor("#fbf1e2"); GREY = colors.HexColor("#f4f6f5")
W, H = A4
M = 16 * mm
CW = W - 2 * M


def st(name, **kw):
    base = dict(fontName="A", fontSize=9.4, leading=12.6, textColor=INK)
    base.update(kw)
    return ParagraphStyle(name, **base)


sBody = st("b", spaceAfter=5)
sSmall = st("s", fontSize=8, leading=10.4, textColor=MUTED)
sCell = st("c", fontSize=8.2, leading=10.6)
sCellS = st("cs", fontSize=7.3, leading=9.4, textColor=MUTED)
sCellB = st("cb", fontSize=8.4, leading=10.8, fontName="A-B")
sH1 = st("h1", fontName="A-B", fontSize=17, leading=21, spaceBefore=4, spaceAfter=8)
sH2 = st("h2", fontName="A-B", fontSize=11.5, leading=15, textColor=ACCENT, spaceBefore=8, spaceAfter=4)
sKick = st("k", fontName="A-B", fontSize=8, leading=10, textColor=ACCENT, spaceAfter=1)
sWeek = st("wk", fontName="A-B", fontSize=12.5, leading=16, textColor=INK, spaceBefore=10, spaceAfter=1)
sWeekSub = st("wks", fontSize=8.3, leading=11, textColor=MUTED, spaceAfter=4)
sBul = st("bl", leftIndent=11, bulletIndent=2, spaceAfter=2)
sTitle = st("t", fontName="A-B", fontSize=30, leading=35)
sSub = st("sub", fontSize=13, leading=18, textColor=MUTED)


def P(t, s=sBody):
    return Paragraph(t, s)


def e(t):
    return escape(t or "")


def bullets(xs):
    return [Paragraph(x, sBul, bulletText="•") for x in xs]


def grid(rows, widths, header=True, style=sCell, hstyle=None, zebra=False):
    hstyle = hstyle or st("hh", fontName="A-B", fontSize=8.2, leading=10.4)
    data = []
    for i, r in enumerate(rows):
        data.append([c if not isinstance(c, str) else Paragraph(c, hstyle if (header and i == 0) else style) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    ts = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        ts += [("BACKGROUND", (0, 0), (-1, 0), SOFT), ("LINEBELOW", (0, 0), (-1, 0), 0.9, ACCENT)]
    if zebra:
        for i in range(1 if header else 0, len(rows)):
            if i % 2 == 0:
                ts.append(("BACKGROUND", (0, i), (-1, i), GREY))
    t.setStyle(TableStyle(ts))
    return t


def box(fl, bg=SOFT, border=ACCENT):
    t = Table([[fl]], colWidths=[CW])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 2.5, border),
                           ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def section(n, title):
    return [P(f"{n:02d}", sKick), P(title, sH1)]


conv = [t for t in T if t["kind"] == "convocatoria"]
cal = [t for t in T if t["kind"] == "calendario"]
byweek = defaultdict(list)
for t in T:
    byweek[t["week"]].append(t)
activ_w = defaultdict(list)
for a in F["activ"]:
    activ_w[a["week"]].append(a)

players_all = Counter()
pweeks = defaultdict(set)
for t in conv:
    for p in t["players"]:
        players_all[p["nombre"]] += 1
        pweeks[p["nombre"]].add(t["week"])
real_players = [p for p in players_all if not p.startswith("Sin identificar")]

GENERIC = {"Sin acompañante", "Sí, con coach (sin nombre)", "No va coach", "Por decidir", "Sin asignar (S/A)"}
trips = [t for t in conv if [a for a in t["acompanan"] if a not in GENERIC]]
solos = [t for t in conv if "Sin acompañante" in t["acompanan"]]

story = []
# ---------------------------------------------------------------- portada
story += [Spacer(1, 45 * mm), P("G TENIS · CALENDARIO DE COMPETICIÓN", sKick), Spacer(1, 4),
          P("Torneos 2026, semana a semana", sTitle), Spacer(1, 8),
          P("Qué torneos hay, qué jugadores van a cada uno y qué coach les acompaña. Reconstruido a partir del "
            "Excel de calendarios del club, cruzando la hoja maestra con las doce hojas de grupo.", sSub),
          Spacer(1, 22 * mm)]
story.append(grid([
    ["Para", "Sergio · Dirección deportiva G Tenis"],
    ["Preparado por", "Automato"],
    ["Fecha", "28 de septiembre de 2026"],
    ["Fuente", "CALENDARIO 2026 (2).xlsx: 13 hojas con calendario, más «GRUPOS TODOS» y «App Jugadores»"],
    ["Periodo", "53 semanas, del 29 de diciembre de 2025 al 3 de enero de 2027"],
    ["Acompaña a", "GTenis - Calendario de torneos 2026 (datos limpios).xlsx: los mismos datos, filtrables"],
], [32 * mm, CW - 32 * mm], header=False))
story += [NextPageTemplate("normal"), PageBreak()]

# ---------------------------------------------------------------- 01 cómo está hecho
story += section(1, "Cómo está hecho y cómo leerlo")
story.append(P("El calendario del club no vive en un solo sitio. Hay una hoja maestra y una hoja por grupo, y cada "
               "grupo usa su propio formato. Hemos leído todas, identificado a cada jugador y juntado el mismo torneo "
               "cuando aparece en varias hojas. Así se ve en una sola lista quién va a cada torneo cada semana."))
story.append(grid([
    ["Hoja", "Qué contiene", "Formato"],
    ["DISTRIBUCION CALENDARIO TODO (maestra)", "Todos los grupos: torneo, cierre, coach y jugadores", "Una fila por torneo"],
    ["GRUPO PABLO", "ITF junior, MARCA, nacionales, Futures del grupo de Pablo", "Una fila por torneo"],
    ["GRUPO SANTI", "Torneos del grupo de Santi y una columna por jugador", "Fila por torneo + columna por jugador"],
    ["GRUPO SALVA", "Enero–febrero 2026 (el resto de la hoja es de 2025)", "Una fila por torneo"],
    ["GRUPO VICTOR M.", "Abril–julio: ITF junior de su grupo", "Fila por torneo + columna por jugador"],
    ["ALVARO", "Escuela y Junior Program: circuitos provinciales, Champions, Faulcombridge…", "Filas con fechas sueltas"],
    ["Grupo ATPChgFutures", "Profesionales: ATP, Challenger, Futures, y dónde juega cada uno", "Columna por jugador"],
    ["Grupo Futures", "Futures e ITF junior del grupo Futures", "Columna por jugador"],
    ["GRUPO SALVA 2 · GRUPO JORGE · Grupo Mario", "Calendarios de referencia y pocos jugadores asignados", "Columna por jugador"],
    ["NACHO CALVO", "Planificación de Bonnie (Jinxuan Liao) por circuito", "Columna por circuito"],
], [52 * mm, 78 * mm, CW - 130 * mm], zebra=True))
story.append(P("Convenciones", sH2))
story += bullets([
    "<b>Semana</b>: de lunes a domingo. Un torneo que empieza en sábado puede aparecer en semanas distintas según la hoja; "
    "lo dejamos donde lo pone cada hoja y lo señalamos en «Lo que conviene revisar».",
    "<b>Coach que acompaña</b>: lo que pone la columna COACH de las hojas de lista. «Va solo» y «SOLAS» se muestran como "
    "<i>sin acompañante</i>. En la hoja de Santi la columna COACH dice SI/NO sin nombre: se muestra como <i>con coach (sin nombre)</i>.",
    "<b>Entrenador de referencia</b> (en gris): en las hojas de profesionales y Futures cada columna de jugador lleva el nombre de "
    "su entrenador. Eso <u>no</u> significa que viaje con él.",
    "<i>Nombre en cursiva</i> = <b>deducido</b>. El Excel pone un nombre de pila que comparten dos personas («ERIC», «DIEGO», "
    "«CARLA»…) y lo asignamos por la hoja en la que aparece. Los criterios están en el Anexo A.",
    "<b>(?)</b> = en el Excel aparece con interrogación, pendiente de confirmar.",
    "<b>Fuente</b>: la hoja o las hojas del Excel donde aparece. El Excel de datos limpios da además la celda exacta.",
])
story.append(Spacer(1, 4))
story.append(box([P("<b>Importante:</b> este documento refleja lo que está <i>escrito</i> en el Excel, no lo que se ha "
                    "jugado. Varias hojas son de planificación y mezclan opciones: en la de Pablo un jugador puede tener "
                    "tres ITF la misma semana; la de Bonnie lista un torneo por circuito. Donde el Excel ofrece "
                    "alternativas, lo indicamos.", sBody)], WARN_SOFT, WARN))

# ---------------------------------------------------------------- 02 cifras
story += [PageBreak()] + section(2, "El año en cifras")
n_weeks_with = len({t["week"] for t in conv})
story.append(grid([
    ["", ""],
    ["Semanas cubiertas", f"53 (29/12/2025 – 03/01/2027) · {n_weeks_with} con al menos un jugador en torneo"],
    ["Torneos con jugadores apuntados", f"{len(conv)} entradas torneo-semana (un torneo de 3 semanas cuenta 3)"],
    ["Torneos solo en calendario", f"{len(cal)}: figuran en alguna hoja pero nadie los tiene asignados"],
    ["Jugadores distintos", f"{len(real_players)}, más {len(players_all) - len(real_players)} columnas sin nombre en la hoja de Mario"],
    ["Plazas jugador-torneo", f"{sum(len(t['players']) for t in conv)}"],
    ["Con coach acompañante con nombre", f"{len(trips)} convocatorias"],
    ["Sin acompañante («va solo/a»)", f"{len(solos)} convocatorias"],
], [62 * mm, CW - 62 * mm], header=False, zebra=True))

story.append(P("Mes a mes", sH2))
rows = [["Mes", "Torneos con jugadores", "Jugadores distintos", "Plazas jugador-torneo", "Con coach con nombre"]]
bym = defaultdict(list)
for t in conv:
    d = dt.date.fromisoformat(t["week"])
    key = (d + dt.timedelta(days=3))  # jueves de la semana decide el mes
    bym[(key.year, key.month)].append(t)
for (y, mth), ts in sorted(bym.items()):
    rows.append([f"{MESES[mth - 1].capitalize()} {y}", str(len(ts)),
                 str(len({p['nombre'] for t in ts for p in t['players'] if not p['nombre'].startswith('Sin id')})),
                 str(sum(len(t['players']) for t in ts)),
                 str(len([t for t in ts if [a for a in t['acompanan'] if a not in GENERIC]]))])
story.append(grid(rows, [40 * mm, 34 * mm, 34 * mm, 36 * mm, CW - 144 * mm], zebra=True))
story.append(P("El mes se asigna por el jueves de cada semana.", sSmall))

story.append(P("Jugadores con más semanas de competición", sH2))
top = sorted([(len(v), k) for k, v in pweeks.items() if not k.startswith("Sin id")], reverse=True)[:24]
half = (len(top) + 1) // 2
rows = [["Jugador", "Semanas", "Jugador", "Semanas"]]
for i in range(half):
    a = top[i]; b = top[i + half] if i + half < len(top) else None
    rows.append([e(a[1]), str(a[0]), e(b[1]) if b else "", str(b[0]) if b else ""])
story.append(grid(rows, [60 * mm, 25 * mm, 60 * mm, CW - 145 * mm], zebra=True))

# ---------------------------------------------------------------- 03 revisar
story += [PageBreak()] + section(3, "Lo que conviene revisar")
story.append(P("Al cruzar las hojas salen cosas que no cuadran. Ninguna impide leer el calendario, pero conviene "
               "corregirlas en el Excel, o tenerlas en cuenta al pasar a la aplicación. El detalle completo, fila a fila, está en el "
               "Anexo B y en la pestaña «Incidencias» del Excel."))
cnt = Counter(i["tipo"] for i in F["incid"])
EXPL = {
    "Cierre con año anterior": "La fecha de cierre lleva año 2025 en un torneo de 2026. Casi seguro que se copió de la plantilla del año pasado.",
    "La hoja maestra no recoge a todos": "Una hoja de grupo apunta a jugadores en un torneo que la maestra también tiene, pero sin ellos.",
    "Jugador en dos torneos la misma semana": "Mismo jugador en dos torneos de semana completa. A veces son opciones y no es un error.",
    "Jugador sin identificar": "Columnas sin nombre (hoja de Mario) o «DAVID» sin apellido cuando nada aclara si es Mas o Castillo.",
    "Jugador pendiente de confirmar": "El Excel lo marca con «?».",
    "Mismo torneo en semanas distintas": "Una hoja lo pone una semana y otra la siguiente. Suele ser un torneo que empieza en sábado.",
    "Cierre posterior al torneo": "La fecha de cierre cae después del torneo.",
    "Cierre distinto según la hoja": "Dos hojas dan cierres distintos para el mismo torneo.",
    "Nivel distinto según la hoja": "M15 frente a M25, J200 frente a J300… según la hoja.",
    "Fecha de semana corregida": "Fecha de semana mal escrita que hemos interpretado.",
    "Fuera de 2026": "Fila que corresponde a 2027.",
    "Cierre ilegible": "El cierre no es una fecha válida.",
}
rows = [["Qué pasa", "Casos", "Qué significa"]]
for k, v in cnt.most_common():
    rows.append([f"<b>{e(k)}</b>", str(v), e(EXPL.get(k, ""))])
story.append(grid(rows, [58 * mm, 14 * mm, CW - 72 * mm], zebra=True))
story.append(P("Lo más urgente", sH2))
urg = [i for i in F["incid"] if i["tipo"] in ("Cierre posterior al torneo", "Nivel distinto según la hoja",
                                               "Cierre ilegible", "Jugador sin identificar", "Cierre distinto según la hoja")]
rows = [["Semana", "Torneo", "Qué pasa"]]
for i in sorted(urg, key=lambda i: i["semana"]):
    if i["tipo"] == "Jugador sin identificar" and "Mario" in i["detalle"]:
        continue
    rows.append([wshort(i["semana"]) if i["semana"] else "", e(short(i["torneo"], 40)), e(i["detalle"])])
rows.append(["", "<i>Hoja de Mario</i>",
             "Las columnas E, F, G y H tienen torneos asignados (J200 Hammamet, J200 Marsa, Champions Cup Valencia, "
             "MARCA Equelite, Carlet y Valencia) pero no tienen el nombre del jugador en la cabecera."])
story.append(grid(rows, [16 * mm, 50 * mm, CW - 66 * mm], zebra=True))
by_sheet = Counter()
for i in F["incid"]:
    if i["tipo"] == "Cierre con año anterior":
        for f in i["fuente"].split(", "):
            by_sheet[f.split(" ")[0]] += 1
story.append(Spacer(1, 4))
story.append(box([P("<b>Cierres con año 2025:</b> " + ", ".join(f"{v} en la hoja {k}" for k, v in by_sheet.most_common())
                    + ". Si esos cierres se usan para avisar de inscripciones, primero hay que corregirlos.", sBody)],
                 WARN_SOFT, WARN))

# ---------------------------------------------------------------- 04 semana a semana
story += [PageBreak()] + section(4, "Semana a semana")
story.append(P("Para cada semana: primero los torneos con jugadores apuntados, con el coach que acompaña; después, "
               "en gris, el resto de torneos que figuran en el calendario de algún grupo esa semana sin nadie asignado."))

DET_SHORT = [("No jugó", "no jugó"), ("Opción 1", "opción 1"), ("Opción 2", "opción 2"), ("Planificación de Bonnie", "plan")]


def pl_html(t):
    out = []
    for p in t["players"]:
        nm = e(p["nombre"])
        if p["certeza"].startswith("deducido"):
            nm = f"<i>{nm}</i>"
        if p["certeza"].startswith("sin identificar"):
            nm = f"<font color='#5d6b64'>{nm}</font>"
        tags = []
        if "pendiente" in p["certeza"]:
            tags.append("?")
        for k, v in DET_SHORT:
            if k in p["detalle"]:
                tags.append(v)
        if tags:
            nm += f" <font size=6.8 color='#a2611a'>({', '.join(tags)})</font>"
        out.append(nm)
    return ", ".join(out) if out else "<font color='#5d6b64'>—</font>"


def coach_html(t):
    parts = []
    ac = t["acompanan"]
    if ac:
        txt = ", ".join(("<i>sin acompañante</i>" if a == "Sin acompañante" else
                         "<i>con coach (sin nombre)</i>" if a.startswith("Sí, con coach") else
                         "<i>no va coach</i>" if a == "No va coach" else
                         "<i>por decidir</i>" if a == "Por decidir" else
                         "<i>sin asignar (S/A)</i>" if a.startswith("Sin asignar") else e(a)) for a in ac)
        parts.append(txt)
    by = defaultdict(list)
    for p in t["players"]:
        for c in p["entrenador_ref"]:
            by[c].append("sin nombre" if p["nombre"].startswith("Sin identificar") else p["nombre"].split(" (")[0].split(" ")[0])
    if by:
        parts.append("<font size=7 color='#5d6b64'>Ref.: " + "; ".join(
            f"{e(c)} ({', '.join(e(x) for x in v)})" for c, v in by.items()) + "</font>")
    return "<br/>".join(parts) if parts else "<font color='#5d6b64'>—</font>"


def tor_html(t):
    s = f"<b>{e(pretty(t['name']))}</b><br/><font size=7 color='#5d6b64'>{e(t['cat'])}"
    ci = [fdate(k) for k in t["cierre_ok"]] if t.get("cierre_ok") else []
    if t["cierres"]:
        cs = [fdate(k) for k in t["cierres"]]
        s += " · cierre " + " / ".join(e(c) for c in cs)
    s += "</font>"
    return s


for w in ALLWEEKS:
    ts = byweek.get(w, [])
    cv = sorted([t for t in ts if t["kind"] == "convocatoria"], key=lambda t: (catkey(t["cat"]), -len(t["players"]), t["name"]))
    cl = sorted([t for t in ts if t["kind"] == "calendario"], key=lambda t: (catkey(t["cat"]), t["name"]))
    n = weekno(w)
    npl = len({p["nombre"] for t in cv for p in t["players"]})
    coaches = sorted({a for t in cv for a in t["acompanan"] if a not in GENERIC})
    head = [P((f"Semana {n}" if n else "Semana previa") + f" · {wrange(w)}", sWeek),
            P(f"{len(cv)} torneo{'s' if len(cv) != 1 else ''} con jugadores · {npl} jugador{'es' if npl != 1 else ''}"
              + (f" · viajan: {', '.join(coaches)}" if coaches else ""), sWeekSub)]
    block = []
    if cv:
        rows = [["Torneo", "Coach", "Jugadores", "Hojas"]]
        for t in cv:
            rows.append([tor_html(t), coach_html(t), pl_html(t), "<font size=7>" + e(", ".join(t["sheets"])) + "</font>"])
        block.append(grid(rows, [52 * mm, 33 * mm, CW - 52 * mm - 33 * mm - 24 * mm, 24 * mm]))
    else:
        block.append(P("Ningún jugador apuntado a torneos esta semana.", sSmall))
    if cl:
        bycat = defaultdict(list)
        for t in cl:
            bycat[t["cat"]].append(short(t["name"], 40))
        txt = " · ".join(f"<b>{e(c)}</b>: {e(', '.join(sorted(set(v))))}" for c, v in sorted(bycat.items(), key=lambda x: catkey(x[0])))
        block.append(Spacer(1, 3))
        block.append(P(f"<b>También en el calendario, sin jugadores:</b> {txt}", sCellS))
    if activ_w.get(w):
        items = defaultdict(list)
        for a in activ_w[w]:
            items[a["texto"]].append(a["jugador"])
        txt = "; ".join(f"{e(k)}: {e(', '.join(sorted(set(v))))}" for k, v in items.items())
        block.append(P(f"<b>Otras anotaciones:</b> {txt}", sCellS))
    story.append(CondPageBreak(45 * mm))
    story.append(KeepTogether(head + block[:1]))
    story += block[1:]

# ---------------------------------------------------------------- 05 por jugador
story += [PageBreak()] + section(5, "Por jugador")
story.append(P("Todos los torneos de cada jugador en el año, por orden de fecha. La fecha es el lunes de la semana. "
               "En cursiva, cuando el nombre es deducido."))
per = defaultdict(list)
for t in conv:
    for p in t["players"]:
        per[p["nombre"]].append((t, p))
rows = [["Jugador", "Sem.", "Torneos"]]
for nm in sorted(per, key=lambda x: (x.startswith("Sin id"), x)):
    lst = sorted(per[nm], key=lambda x: x[0]["week"])
    txt = " · ".join(("<i>" if p["certeza"].startswith("deducido") else "") + f"<b>{wshort(t['week'])}</b> {e(short(t['name'], 38))}"
                     + ("</i>" if p["certeza"].startswith("deducido") else "") + (" (?)" if "pendiente" in p["certeza"] else "")
                     for t, p in lst)
    rows.append([f"<b>{e(nm)}</b>", str(len(pweeks[nm])), txt])
story.append(grid(rows, [38 * mm, 10 * mm, CW - 48 * mm], zebra=True))

# ---------------------------------------------------------------- 06 por coach
story += [PageBreak()] + section(6, "Por coach")
story.append(P("Viajes con coach acompañante según la columna COACH de las hojas de lista. Al final, las convocatorias "
               "en las que el Excel dice que el jugador va sin acompañante."))
perc = defaultdict(list)
for t in conv:
    for a in t["acompanan"]:
        perc[a].append(t)
order = sorted([c for c in perc if c not in GENERIC], key=lambda c: (-len(perc[c]), c)) + \
        [c for c in ["Sí, con coach (sin nombre)", "Sin acompañante", "No va coach", "Por decidir", "Sin asignar (S/A)"] if c in perc]
for c in order:
    ts = sorted(perc[c], key=lambda t: t["week"])
    rows = [["Semana", "Torneo", "Jugadores"]]
    for t in ts:
        rows.append([wshort(t["week"]), e(short(t["name"], 50)), pl_html(t)])
    story.append(CondPageBreak(45 * mm))
    story.append(P(f"{e(c)} · {len(ts)}", sH2))
    story.append(grid(rows, [16 * mm, 62 * mm, CW - 78 * mm]))

# ---------------------------------------------------------------- anexos
story += [PageBreak()] + [P("ANEXO A", sKick), P("Cómo se ha decidido quién es quién", sH1)]
story.append(P("Solo se deduce cuando el Excel pone un nombre de pila que comparten dos personas. Todo lo deducido va "
               "en cursiva en este documento y marcado «deducido» en el Excel de datos."))
from excel import crit  # noqa  (misma tabla que la pestaña del Excel)
rows = [["Escrito en el Excel", "Se interpreta como", "Regla / excepciones"]] + [[e(a), e(b), e(c)] for a, b, c in crit]
story.append(grid(rows, [34 * mm, 40 * mm, CW - 74 * mm], zebra=True))

story += [PageBreak()] + [P("ANEXO B", sKick), P("Incidencias, una a una", sH1)]
GORD = {"alta": 0, "media": 1, "baja": 2}
byt = defaultdict(list)
for i in F["incid"]:
    byt[i["tipo"]].append(i)
for tipo in sorted(byt, key=lambda k: (min(GORD[i["gravedad"]] for i in byt[k]), -len(byt[k]))):
    rows = [["Semana", "Torneo", "Detalle", "Fuente"]]
    for i in sorted(byt[tipo], key=lambda i: i["semana"]):
        rows.append([wshort(i["semana"]) if i["semana"] else "", e(short(i["torneo"], 36)) if i["torneo"] else "",
                     e(i["detalle"]), "<font size=6.8>" + e(i["fuente"]) + "</font>"])
    story.append(CondPageBreak(30 * mm))
    story.append(P(f"{e(tipo)} · {len(byt[tipo])}", sH2))
    story.append(grid(rows, [14 * mm, 40 * mm, CW - 54 * mm - 26 * mm, 26 * mm], style=st("ci", fontSize=7.6, leading=9.8)))

story += [PageBreak()] + [P("ANEXO C", sKick), P("Restos de 2025", sH1)]
y = Counter(x["hoja"] for x in F["y25"])
story.append(P(f"El Excel conserva {len(F['y25'])} filas de 2025 que no forman parte del calendario 2026: "
               + ", ".join(f"{v} en la hoja de {k}" for k, v in y.items()) + ". "
               "En la de Salva son de junio a octubre de 2025 y aparecen detrás de febrero de 2026, lo que puede confundir; "
               "en la de Álvaro son de septiembre a diciembre de 2025 y van al final de la hoja. No las hemos mezclado con 2026. "
               "Están completas en la pestaña «Restos 2025» del Excel."))


def on_page(c, doc):
    c.saveState()
    c.setFont("A", 7.5); c.setFillColor(MUTED)
    c.drawString(M, 10 * mm, "G Tenis · Torneos 2026 semana a semana")
    c.drawRightString(W - M, 10 * mm, f"Página {doc.page}")
    c.setStrokeColor(RULE); c.line(M, 13 * mm, W - M, 13 * mm)
    c.restoreState()


def on_cover(c, doc):
    c.saveState(); c.setFillColor(ACCENT); c.rect(0, H - 9 * mm, W, 9 * mm, stroke=0, fill=1); c.restoreState()


doc = BaseDocTemplate(OUT, pagesize=A4, leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=18 * mm,
                      title="G Tenis · Torneos 2026 semana a semana", author="Automato")
fr = Frame(M, 18 * mm, CW, H - M - 18 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
doc.addPageTemplates([PageTemplate("cover", [fr], onPage=on_cover), PageTemplate("normal", [fr], onPage=on_page)])
doc.build(story)
print(OUT)
