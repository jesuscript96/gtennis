"""Genera el Excel de recogida de datos para la dirección deportiva.

La app ya sabe quién es cada jugador, en qué escuela está y quién lo lleva. Lo
que no sabe —y sin lo cual el motor reparte a ciegas— es **cuándo viene cada
uno**: en qué franja entrena de normal, qué días se sale de eso, cuántas
sesiones le tocan, desde cuándo está de alta y qué días ya se sabe que falta.

Las celdas grises son de la app (no se tocan). Las amarillas son suyas y
admiten texto libre: `M1+T2`, `mañana`, `8:30`, `primera y tercera`, `-`…
Luego `importar_recogida` interpreta lo que hayan escrito y saca un informe de
lo que no ha entendido, en vez de exigirles un formato.

Se puede generar contra esta base o contra una instalación en marcha, que es lo
normal cuando quien rellena trabaja sobre producción:

    python manage.py plantilla_recogida
    python manage.py plantilla_recogida --salida /ruta/archivo.xlsx
    python manage.py plantilla_recogida --desde https://…/api --token <token>
"""
import json
import urllib.request

from django.core.management.base import BaseCommand, CommandError

GRIS = "FFF2F2F2"
AMARILLO = "FFFFF6D8"
EJEMPLO = "FFEFF6EE"
CABECERA = "FF1F3A5F"
FUENTE = "Arial"

DIAS = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES"]

# (cabecera, ancho). Las primeras `N_GRIS_JUG` las rellena la app.
COLS_JUGADOR = [
    ("Jugador", 30), ("Cód.", 9), ("Escuela", 17), ("División", 10),
    ("Responsable hoy", 22),
    # --- a partir de aquí, amarillo ---
    ("Escuela correcta", 17), ("División correcta", 13), ("Responsable correcto", 22),
    ("De normal · MAÑANA", 17), ("De normal · TARDE", 17),
] + [(d, 12) for d in DIAS] + [
    ("Ses./semana", 12), ("Máx. al día", 11),
    ("Entra el día", 13), ("Último día", 13),
    ("Entrena SIEMPRE con", 22), ("NO ponerlo con", 22), ("Contrato con", 20),
    ("Superficie", 13), ("Notas", 42),
]
N_GRIS_JUG = 5

COLS_ENTRENADOR = [
    ("Entrenador", 28), ("Divisiones en la app", 20), ("Franjas en la app", 16),
    # --- amarillo ---
    ("Divisiones correctas", 20),
    ("De normal · MAÑANA", 17), ("De normal · TARDE", 17),
] + [(d, 12) for d in DIAS] + [("Notas", 46)]
N_GRIS_ENT = 3

COLS_AUSENCIA = [
    ("Jugador o entrenador", 30), ("Desde", 14), ("Hasta", 14),
    ("Motivo", 26), ("Qué se pierde", 22), ("Notas", 40),
]

# Una fila de ejemplo con valores realistas: sin ella, «escribe como quieras»
# se lee como «no sé qué esperas de mí».
EJEMPLO_JUGADOR = [
    "(ejemplo) Juan Pérez", "", "", "", "",
    "", "", "Mario Muniesa", "M2", "T1",
    "", "M1", "-", "", "solo mañana",
    "4", "2", "16/09", "", "", "", "", "tierra",
    "los miércoles llega tarde, entra a las 11",
]
EJEMPLO_ENTRENADOR = [
    "(ejemplo) Mario Muniesa", "", "",
    "4, 5", "M2", "", "", "", "-", "", "tarde",
    "los viernes solo por la mañana",
]
EJEMPLO_AUSENCIA = [
    "(ejemplo) Juan Pérez", "2/10", "9/10", "torneo en Alicante",
    "todo el día", "vuelve el lunes 12",
]


class Command(BaseCommand):
    help = "Genera el Excel de recogida de datos de jugadores y entrenadores."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salida", default="docs/Recogida_GTennis.xlsx",
            help="Ruta del .xlsx a escribir.",
        )
        parser.add_argument(
            "--desde",
            help="API de una instalación en marcha (p. ej. la de producción). "
                 "Sin esto, se usa esta base de datos.",
        )
        parser.add_argument("--token", help="Token DRF para --desde.")

    # -- de dónde salen los datos ---------------------------------------- #
    def _de_la_api(self, url, token):
        def trae(ruta):
            pet = urllib.request.Request(
                f"{url.rstrip('/')}{ruta}", headers={"Authorization": f"Token {token}"}
            )
            with urllib.request.urlopen(pet, timeout=60) as r:
                d = json.loads(r.read().decode())
            return d["results"] if isinstance(d, dict) and "results" in d else d

        turnos = [
            (t["codigo"], t["hora_inicio"][:5], t["hora_fin"][:5])
            for t in sorted(trae("/turnos/?limit=50"), key=lambda t: t["orden"])
        ]
        jugadores = [
            {
                "nombre": j["nombre"], "codigo": j.get("codigo_cliente") or "",
                "escuela": j.get("escuela_nombre") or "",
                "division": j.get("division_nivel") or "SIN DIVISIÓN",
                "responsable": j.get("entrenador_nombre") or "— falta —",
            }
            for j in sorted(
                trae("/jugadores/?limit=500"),
                key=lambda j: ((j.get("escuela_nombre") or "~"),
                               j.get("division_nivel") or 99, j["nombre"]),
            )
        ]
        entrenadores = [
            {
                "nombre": e["nombre"],
                "divisiones": e.get("divisiones_habilitadas_display") or "— sin asignar —",
                "franjas": e.get("turnos_display") or "Cualquiera",
            }
            for e in sorted(trae("/entrenadores/?limit=200"), key=lambda e: e["nombre"])
        ]
        return turnos, jugadores, entrenadores

    def _de_la_base(self):
        from academy.models import Entrenador, Jugador, Turno

        turnos = [
            (t.codigo, f"{t.hora_inicio:%H:%M}", f"{t.hora_fin:%H:%M}")
            for t in Turno.objects.filter(activo=True).order_by("orden")
        ]
        jugadores = [
            {
                "nombre": j.nombre, "codigo": j.codigo_cliente or "",
                "escuela": j.escuela.nombre if j.escuela_id else "",
                "division": j.division.nivel if j.division_id else "SIN DIVISIÓN",
                "responsable": (j.entrenador_responsable.nombre
                                if j.entrenador_responsable_id else "— falta —"),
            }
            for j in Jugador.objects.filter(activo=True)
            .select_related("escuela", "division", "entrenador_responsable")
            .order_by("escuela__nombre", "division__nivel", "nombre")
        ]
        entrenadores = []
        for e in (Entrenador.objects.filter(activo=True)
                  .prefetch_related("divisiones_habilitadas")
                  .select_related("turno_manana", "turno_tarde").order_by("nombre")):
            niveles = sorted(e.divisiones_habilitadas.values_list("nivel", flat=True))
            franjas = [t.codigo for t in (e.turno_manana, e.turno_tarde) if t]
            entrenadores.append({
                "nombre": e.nombre,
                "divisiones": ", ".join(f"D{n}" for n in niveles) or "— sin asignar —",
                "franjas": " + ".join(franjas) or "Cualquiera",
            })
        return turnos, jugadores, entrenadores

    # -------------------------------------------------------------------- #
    def handle(self, *args, **opts):
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        if opts["desde"]:
            if not opts["token"]:
                raise CommandError("--desde necesita --token.")
            turnos, jugadores, entrenadores = self._de_la_api(opts["desde"], opts["token"])
            origen = opts["desde"]
        else:
            turnos, jugadores, entrenadores = self._de_la_base()
            origen = "esta base de datos"

        leyenda_turnos = "   ·   ".join(f"{c} = {i}-{f}" for c, i, f in turnos)
        wb = Workbook()

        base = Font(name=FUENTE, size=11)
        neg = Font(name=FUENTE, size=11, bold=True)
        blanco = Font(name=FUENTE, size=11, bold=True, color="FFFFFFFF")
        gris_txt = Font(name=FUENTE, size=10, italic=True, color="FF808080")
        fondo_cab = PatternFill("solid", fgColor=CABECERA)
        fondo_gris = PatternFill("solid", fgColor=GRIS)
        fondo_ama = PatternFill("solid", fgColor=AMARILLO)
        fondo_ej = PatternFill("solid", fgColor=EJEMPLO)
        borde = Border(*[Side(style="thin", color="FFD0D0D0")] * 4)
        centro = Alignment(horizontal="center", vertical="center", wrap_text=True)

        def cabecera(ws, fila, cols, n_grises):
            for i, (texto, ancho) in enumerate(cols, start=1):
                c = ws.cell(row=fila, column=i, value=texto)
                c.font = blanco
                c.fill = fondo_cab
                c.alignment = centro
                c.border = borde
                ws.column_dimensions[get_column_letter(i)].width = ancho
            ws.row_dimensions[fila].height = 30
            ws.freeze_panes = ws.cell(row=fila + 1, column=min(n_grises, 2) + 1)

        def pinta(ws, fila, n_grises, n_total, ejemplo=False):
            for i in range(1, n_total + 1):
                c = ws.cell(row=fila, column=i)
                c.border = borde
                c.font = gris_txt if ejemplo else base
                if ejemplo:
                    c.fill = fondo_ej
                else:
                    c.fill = fondo_gris if i <= n_grises else fondo_ama
                if i > n_grises:
                    c.alignment = centro

        def escribe(ws, fila, valores):
            for i, v in enumerate(valores, start=1):
                if v != "":
                    ws.cell(row=fila, column=i, value=v)

        # ------------------------------------------------------------------ #
        # 1) Cómo rellenar
        # ------------------------------------------------------------------ #
        ws = wb.active
        ws.title = "Cómo rellenar"
        ws.column_dimensions["A"].width = 112
        lineas = [
            ("G Tennis · Recogida de datos del curso", 14),
            ("", 0),
            ("Rellena solo lo AMARILLO. Lo gris lo pone la app y está para que te sitúes.", 0),
            ("Escribe como te salga: lo interpretamos nosotros y te preguntamos lo que no", 0),
            ("entendamos. No hay formato que respetar.", 0),
            ("La primera fila de cada hoja es un EJEMPLO en verde: bórrala o déjala, no se importa.", 0),
            ("", 0),
            ("JUGADORES", 12),
            (f"   Franjas:  {leyenda_turnos}", 0),
            ("   DE NORMAL · MAÑANA / TARDE → la franja de siempre. Con esto suele bastar.", 0),
            ("       M2        entra a las 10:30        mañana    da igual cuál de las dos", 0),
            ("       -         no entrena ese bloque    (vacío)   que elija el programa", 0),
            ("   LUNES…VIERNES → SOLO si ese día se sale de lo normal. Si todos los días son", 0),
            ("   iguales, déjalos en blanco.", 0),
            ("       M1+T2     los dos          8:30      por la hora", 0),
            ("       -         ese día no viene           solo mañana", 0),
            ("   SES./SEMANA → cuántas sesiones le tocan a la semana (4 es lo normal).", 0),
            ("   MÁX. AL DÍA → cuántas puede hacer el mismo día (2 = una de mañana y otra de tarde).", 0),
            ("   ENTRA EL DÍA → si empieza a mitad de mes. Hasta esa fecha no se le mete en nada.", 0),
            ("   ÚLTIMO DÍA → si ya se sabe que lo deja.", 0),
            ("   RESPONSABLE → el entrenador que responde por él; solo uno. Que le entrenen", 0),
            ("   otros del bloque no cambia, eso va por división.", 0),
            ("   El resto (parejas, vetos, contrato, superficie): solo si aplica.", 0),
            ("", 0),
            ("ENTRENADORES", 12),
            ("   DIVISIONES → a qué divisiones puede dar clase. En blanco = a todas.", 0),
            ("   DE NORMAL · MAÑANA / TARDE → su franja fija. En blanco = entra donde haga", 0),
            ("   falta, siempre que haya jugadores suyos.", 0),
            ("   LUNES…VIERNES → mañana / tarde / ambas / -    En blanco = jornada completa.", 0),
            ("", 0),
            ("AUSENCIAS", 12),
            ("   Solo lo que YA se sabe: torneos, lesiones largas, viajes, exámenes.", 0),
            ("   Un día suelto: repite la fecha en «Desde» y «Hasta».", 0),
            ("   QUÉ SE PIERDE → todo el día / la mañana / la tarde / M1 / hasta las 10:30…", 0),
            ("   Lo de «hoy no viene» va en la app, que eso cambia cada semana.", 0),
            ("", 0),
            (f"Generado desde: {origen}", 0),
        ]
        for i, (texto, tam) in enumerate(lineas, start=1):
            c = ws.cell(row=i, column=1, value=texto)
            c.font = (Font(name=FUENTE, size=tam, bold=True, color=CABECERA)
                      if tam else base)

        # ------------------------------------------------------------------ #
        # 2) Jugadores
        # ------------------------------------------------------------------ #
        ws = wb.create_sheet("Jugadores")
        ws.cell(row=1, column=1,
                value="Jugadores · gris = la app · amarillo = tú").font = neg
        ws.cell(row=2, column=1, value=f"Franjas:  {leyenda_turnos}").font = base
        ws.cell(row=3, column=1, value=(
            "Con «De normal» suele bastar. Los días solo si ese día cambia."
        )).font = base
        cabecera(ws, 4, COLS_JUGADOR, N_GRIS_JUG)

        pinta(ws, 5, N_GRIS_JUG, len(COLS_JUGADOR), ejemplo=True)
        escribe(ws, 5, EJEMPLO_JUGADOR)

        fila = 6
        for j in jugadores:
            escribe(ws, fila, [j["nombre"], j["codigo"], j["escuela"],
                               j["division"], j["responsable"]])
            pinta(ws, fila, N_GRIS_JUG, len(COLS_JUGADOR))
            fila += 1

        # ------------------------------------------------------------------ #
        # 3) Entrenadores
        # ------------------------------------------------------------------ #
        ws = wb.create_sheet("Entrenadores")
        ws.cell(row=1, column=1,
                value="Entrenadores · a qué divisiones da clase y cuándo").font = neg
        ws.cell(row=2, column=1, value=(
            "Días: mañana / tarde / ambas / -   ·   En blanco = jornada completa"
        )).font = base
        ws.cell(row=3, column=1, value=(
            "«De normal» en blanco = entra donde haga falta, siempre que haya jugadores suyos."
        )).font = base
        cabecera(ws, 4, COLS_ENTRENADOR, N_GRIS_ENT)

        pinta(ws, 5, N_GRIS_ENT, len(COLS_ENTRENADOR), ejemplo=True)
        escribe(ws, 5, EJEMPLO_ENTRENADOR)

        fila = 6
        for e in entrenadores:
            escribe(ws, fila, [e["nombre"], e["divisiones"], e["franjas"]])
            pinta(ws, fila, N_GRIS_ENT, len(COLS_ENTRENADOR))
            fila += 1

        # ------------------------------------------------------------------ #
        # 4) Ausencias
        # ------------------------------------------------------------------ #
        ws = wb.create_sheet("Ausencias")
        ws.cell(row=1, column=1, value="Ausencias que ya se saben").font = neg
        ws.cell(row=2, column=1, value=(
            "Torneos, lesiones largas, viajes, exámenes. Un solo día: repite la fecha."
        )).font = base
        ws.cell(row=3, column=1, value=(
            "«Qué se pierde» solo si no falta el día entero: la mañana, M1, hasta las 10:30…"
        )).font = base
        cabecera(ws, 4, COLS_AUSENCIA, 0)
        pinta(ws, 5, 0, len(COLS_AUSENCIA), ejemplo=True)
        escribe(ws, 5, EJEMPLO_AUSENCIA)
        for f in range(6, 120):
            pinta(ws, f, 0, len(COLS_AUSENCIA))

        wb.save(opts["salida"])
        self.stdout.write(self.style.SUCCESS(
            f"Escrito {opts['salida']} · {len(jugadores)} jugadores, "
            f"{len(entrenadores)} entrenadores (origen: {origen})"
        ))
