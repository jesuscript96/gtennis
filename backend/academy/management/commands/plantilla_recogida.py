"""Genera el Excel de recogida de datos para Iván / Sergio.

La app ya sabe quién es cada jugador, en qué grupo está y quién lo lleva. Lo
que no sabe —y sin lo cual el motor reparte a ciegas— es **cuándo viene cada
uno**. Este comando vuelca lo conocido en un libro con una fila por jugador y
una columna por día, para que lo rellenen en Excel y no a mano en la app.

Las celdas grises son de la app (no se tocan). Las amarillas son las suyas y
admiten texto libre: `M1+T2`, `mañana`, `8:30`, `primera y tercera`, `-`...
Luego `importar_recogida` interpreta lo que hayan escrito y avisa de lo que no
ha entendido, en vez de exigirles un formato.

Uso:
    python manage.py plantilla_recogida
    python manage.py plantilla_recogida --salida /ruta/archivo.xlsx
"""
from django.core.management.base import BaseCommand

from academy.models import Entrenador, Jugador, ResponsableJugador, Turno

GRIS = "FFF2F2F2"
AMARILLO = "FFFFF6D8"
CABECERA = "FF1F3A5F"

DIAS = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES"]


class Command(BaseCommand):
    help = "Genera el Excel de recogida de datos de jugadores y entrenadores."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salida",
            default="docs/Recogida_GTennis.xlsx",
            help="Ruta del .xlsx a escribir.",
        )

    def handle(self, *args, **opts):
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        ruta = opts["salida"]
        wb = Workbook()

        turnos = list(Turno.objects.filter(activo=True).order_by("orden"))
        leyenda_turnos = "   ·   ".join(
            f"{t.codigo} = {t.hora_inicio:%H:%M}-{t.hora_fin:%H:%M}" for t in turnos
        )

        neg = Font(bold=True)
        blanco = Font(bold=True, color="FFFFFFFF")
        fondo_cab = PatternFill("solid", fgColor=CABECERA)
        fondo_gris = PatternFill("solid", fgColor=GRIS)
        fondo_ama = PatternFill("solid", fgColor=AMARILLO)
        borde = Border(*[Side(style="thin", color="FFD0D0D0")] * 4)
        centro = Alignment(horizontal="center", vertical="center")
        ajusta = Alignment(wrap_text=True, vertical="top")

        def cabecera(ws, fila, cols, n_grises):
            for i, texto in enumerate(cols, start=1):
                c = ws.cell(row=fila, column=i, value=texto)
                c.font = blanco
                c.fill = fondo_cab
                c.alignment = centro
                c.border = borde
            ws.freeze_panes = ws.cell(row=fila + 1, column=n_grises + 1)

        def pinta(ws, fila, n_grises, n_total):
            for i in range(1, n_total + 1):
                c = ws.cell(row=fila, column=i)
                c.fill = fondo_gris if i <= n_grises else fondo_ama
                c.border = borde
                if i > n_grises:
                    c.alignment = centro

        # ------------------------------------------------------------------ #
        # 1) Instrucciones
        # ------------------------------------------------------------------ #
        ws = wb.active
        ws.title = "Cómo rellenar"
        ws.column_dimensions["A"].width = 110
        lineas = [
            ("G Tennis · Recogida de datos", True),
            ("", False),
            ("Rellena solo lo AMARILLO. Lo gris lo pone la app.", False),
            ("Escribe como te salga: lo interpretamos nosotros y te preguntamos lo que no", False),
            ("entendamos. No hay formato que respetar.", False),
            ("", False),
            ("JUGADORES · una fila por jugador, una columna por día", True),
            (f"   {leyenda_turnos}", False),
            ("   En cada día, qué turnos hace:", False),
            ("       M1+T2        los dos          M1       solo por la mañana", False),
            ("       mañana       sin concretar    8:30     por la hora", False),
            ("       -            no viene         (vacío)  no lo sabes", False),
            ("   RESPONSABLE: hay que rellenarlo casi siempre. Hoy cada jugador cuelga de todo", False),
            ("   su bloque y solo puede haber uno. Que le entrenen los demás no cambia: eso va", False),
            ("   por división.", False),
            ("   El resto de columnas (parejas, vetos, contratos, superficie): solo si aplica.", False),
            ("", False),
            ("ENTRENADORES · qué divisiones puede entrenar, y qué jornada hace", True),
            ("   En los días:  mañana / tarde / ambas / -        En blanco = jornada completa", False),
            ("", False),
            ("AUSENCIAS · solo lo que ya sabes: torneos, lesiones largas, viajes", True),
            ("   Un día suelto: repite la fecha en las dos columnas.", False),
            ("   Lo de «hoy no viene» va en la app, no aquí: eso cambia cada semana.", False),
        ]
        for i, (texto, es_titulo) in enumerate(lineas, start=1):
            c = ws.cell(row=i, column=1, value=texto)
            if es_titulo:
                c.font = Font(bold=True, size=13 if i == 1 else 11, color=CABECERA)

        # ------------------------------------------------------------------ #
        # 2) Jugadores
        # ------------------------------------------------------------------ #
        ws = wb.create_sheet("Jugadores")
        resp = {}
        for r in ResponsableJugador.objects.filter(activo=True).select_related(
            "jugador", "entrenador"
        ).order_by("jugador_id", "prioridad", "entrenador__nombre"):
            resp.setdefault(r.jugador_id, []).append(r.entrenador.nombre)

        cols = (["Jugador", "Grupo", "División app", "División correcta",
                 "Responsables hoy", "Responsable correcto"] + DIAS
                + ["Ses./semana", "Entrena SIEMPRE con", "NO ponerlo con",
                   "Contrato con", "Superficie", "Notas"])
        ws.cell(row=1, column=1, value="Jugadores · gris = la app · amarillo = tú").font = neg
        ws.cell(row=2, column=1, value=f"Turnos:  {leyenda_turnos}")
        cabecera(ws, 4, cols, 3)

        jugadores = (
            Jugador.objects.filter(activo=True)
            .select_related("escuela", "division")
            .order_by("escuela__nombre", "division__nivel", "nombre")
        )
        fila = 5
        for j in jugadores:
            ws.cell(row=fila, column=1, value=j.nombre)
            ws.cell(row=fila, column=2, value=j.escuela.nombre if j.escuela else "")
            ws.cell(row=fila, column=3,
                    value=j.division.nivel if j.division else "SIN DIVISIÓN")
            actuales = resp.get(j.id, [])
            ws.cell(row=fila, column=5, value=(
                ", ".join(actuales) if len(actuales) == 1
                else f"⚠ {len(actuales)}: " + ", ".join(actuales) if actuales
                else "— falta —"))
            pinta(ws, fila, 3, len(cols))
            # La columna E la pone la app aunque caiga en zona amarilla.
            c = ws.cell(row=fila, column=5)
            c.fill = fondo_gris
            fila += 1

        anchos = [30, 17, 11, 13, 42, 22] + [13] * 5 + [12, 22, 22, 20, 13, 40]
        for i, w in enumerate(anchos, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.cell(row=4, column=len(cols)).alignment = centro

        # ------------------------------------------------------------------ #
        # 3) Entrenadores
        # ------------------------------------------------------------------ #
        ws = wb.create_sheet("Entrenadores")
        cols = ["Entrenador", "Divisiones en la app", "Divisiones correctas"] + DIAS + [
            "Notas"
        ]
        ws.cell(row=1, column=1,
                value="Entrenadores · divisiones que PUEDE entrenar y jornada semanal").font = neg
        ws.cell(row=2, column=1,
                value="En los días: mañana / tarde / ambas / -    ·    En blanco = jornada completa")
        cabecera(ws, 4, cols, 2)

        fila = 5
        for e in Entrenador.objects.filter(activo=True).order_by("nombre"):
            niveles = sorted(e.divisiones_habilitadas.values_list("nivel", flat=True))
            ws.cell(row=fila, column=1, value=e.nombre)
            ws.cell(row=fila, column=2,
                    value=", ".join(str(n) for n in niveles) if niveles else "— sin asignar —")
            pinta(ws, fila, 2, len(cols))
            fila += 1

        for i, w in enumerate([28, 20, 20] + [13] * 5 + [46], start=1):
            ws.column_dimensions[get_column_letter(i)].width = w

        # ------------------------------------------------------------------ #
        # 4) Ausencias
        # ------------------------------------------------------------------ #
        ws = wb.create_sheet("Ausencias")
        ws.cell(row=1, column=1, value="Ausencias que ya conoces").font = neg
        ws.cell(row=2, column=1,
                value="Torneos, lesiones largas, viajes. Un solo día: repite la fecha en las dos columnas.")
        cols = ["Jugador o entrenador", "Desde", "Hasta", "Motivo", "Turnos afectados", "Notas"]
        cabecera(ws, 4, cols, 0)
        for fila in range(5, 65):
            pinta(ws, fila, 0, len(cols))
        for i, w in enumerate([30, 14, 14, 26, 20, 40], start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.cell(row=3, column=1,
                value="«Turnos afectados» solo si no falta el día entero: M1, tarde, hasta las 10:30...")

        wb.save(ruta)
        self.stdout.write(self.style.SUCCESS(
            f"Escrito {ruta}  ·  {jugadores.count()} jugadores, "
            f"{Entrenador.objects.filter(activo=True).count()} entrenadores"
        ))
