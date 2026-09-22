"""Excel de recogida COMPLETO: todo lo que el motor usa, por jugador y por entrenador.

`plantilla_recogida` pregunta lo básico (cuándo viene cada uno). Esta plantilla
pregunta **todo** lo que hoy decide el cuadrante: ficha del alumno, ficha del
entrenador, la semana habitual, la semana concreta día a día —con turnos,
ausencias y torneos—, y las reglas especiales (rencillas, contratos,
preferencias de pista).

Gris = lo que ya sabe la app, para contrastar. Amarillo = lo que rellena la
dirección deportiva. Verde = ejemplo.

    python manage.py plantilla_completa
    python manage.py plantilla_completa --salida /ruta/archivo.xlsx --semana 2026-09-21
"""
from datetime import date, timedelta

from django.core.management.base import BaseCommand

GRIS = "FFF2F2F2"
AMARILLO = "FFFFF6D8"
EJEMPLO = "FFEFF6EE"
CABECERA = "FF1F3A5F"
SECCION = "FF2E5E8C"
FUENTE = "Arial"
DIAS = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES"]

VECINDAD = {
    "CLUB": "la del club (±1)", "SOLO": "solo su división",
    "ARRIBA": "su división y la de encima", "ABAJO": "su división y la de debajo",
    "AMBAS": "su división y las dos vecinas",
}


class Command(BaseCommand):
    help = "Genera el Excel completo de recogida de datos (jugadores y entrenadores)."

    def add_arguments(self, parser):
        parser.add_argument("--salida", default="docs/GTennis_datos_completo.xlsx")
        parser.add_argument(
            "--semana", help="Lunes de la semana a rellenar (AAAA-MM-DD). "
                             "Por defecto, el lunes que viene.")
        parser.add_argument(
            "--ejemplo", help="Lunes de la semana ya vivida que se usa de ejemplo.")

    # ---------------------------------------------------------------- datos
    def _datos(self):
        from academy.models import (Contrato, Entrenador, HorarioEntrenador,
                                    HorarioJugador, Jugador, PreferenciaPareja,
                                    PreferenciaSuperficie, Rencilla, Turno)

        turnos = list(Turno.objects.filter(activo=True).order_by("orden"))
        jugadores = list(
            Jugador.objects.filter(activo=True)
            .select_related("escuela", "division", "entrenador_responsable",
                            "turno_manana", "turno_tarde")
            .order_by("division__nivel", "nombre"))
        entrenadores = list(
            Entrenador.objects.filter(activo=True)
            .select_related("turno_manana", "turno_tarde").order_by("nombre"))
        horarios = {}
        for h in HorarioJugador.objects.select_related("turno_manana", "turno_tarde"):
            horarios[(h.jugador_id, h.dia)] = h
        jornadas = {}
        for h in HorarioEntrenador.objects.all():
            jornadas[(h.entrenador_id, h.dia)] = h
        return {
            "turnos": turnos, "jugadores": jugadores, "entrenadores": entrenadores,
            "horarios": horarios, "jornadas": jornadas,
            "contratos": list(Contrato.objects.filter(activo=True)
                              .select_related("jugador", "entrenador")),
            "rencillas": list(Rencilla.objects.filter(activa=True)
                              .select_related("jugador_a", "jugador_b")),
            "parejas": list(PreferenciaPareja.objects.filter(activa=True)
                            .select_related("jugador", "jugador_objetivo")),
            "superficies": list(PreferenciaSuperficie.objects.select_related("jugador")),
        }

    def _semana_vivida(self, lunes):
        """Qué hizo cada jugador esa semana: franja por día y motivo si faltó."""
        from scheduling.models import Asignacion, Disponibilidad, Semana

        s = Semana.objects.filter(fecha_inicio=lunes).first()
        if s is None:
            return {}, None
        datos = {}
        for a in Asignacion.objects.filter(semana=s).select_related("turno"):
            datos.setdefault(a.jugador_id, {}).setdefault(a.dia, {})
            bloque = "manana" if a.turno.bloque == "MANANA" else "tarde"
            datos[a.jugador_id][a.dia][bloque] = a.turno.codigo
        for d in Disponibilidad.objects.filter(semana=s).select_related("jugador"):
            if d.estado != "AUSENCIA_JUGADOR":
                continue
            dia = datos.setdefault(d.jugador_id, {}).setdefault(d.dia, {})
            if d.ambito in ("DIA", "MANANA"):
                dia.setdefault("manana", "no")
            if d.ambito in ("DIA", "TARDE"):
                dia.setdefault("tarde", "no")
            # El motivo es el de la dirección; las notas internas del sistema
            # no pintan nada en una plantilla que se rellena a mano.
            if d.subtipo:
                dia["motivo"] = d.get_subtipo_display()
        return datos, s

    # ---------------------------------------------------------------- hoja
    def handle(self, *args, **opts):
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
        from openpyxl.worksheet.datavalidation import DataValidation

        d = self._datos()
        hoy = date.today()
        lunes = (date.fromisoformat(opts["semana"]) if opts["semana"]
                 else hoy + timedelta(days=(7 - hoy.weekday()) % 7 or 7))
        ejemplo_lunes = (date.fromisoformat(opts["ejemplo"]) if opts["ejemplo"]
                         else lunes - timedelta(days=7))
        vivida, semana_ej = self._semana_vivida(ejemplo_lunes)

        wb = Workbook()
        base = Font(name=FUENTE, size=11)
        neg = Font(name=FUENTE, size=11, bold=True)
        blanco = Font(name=FUENTE, size=11, bold=True, color="FFFFFFFF")
        gris_txt = Font(name=FUENTE, size=10, italic=True, color="FF808080")
        fondos = {"cab": PatternFill("solid", fgColor=CABECERA),
                  "sec": PatternFill("solid", fgColor=SECCION),
                  "gris": PatternFill("solid", fgColor=GRIS),
                  "ama": PatternFill("solid", fgColor=AMARILLO),
                  "ej": PatternFill("solid", fgColor=EJEMPLO)}
        borde = Border(*[Side(style="thin", color="FFD0D0D0")] * 4)
        centro = Alignment(horizontal="center", vertical="center", wrap_text=True)
        izq = Alignment(horizontal="left", vertical="center", wrap_text=True)

        def hoja(titulo, intro, cols, n_grises, filas, ejemplo=None, validaciones=None):
            ws = wb.create_sheet(titulo[:31])
            ws.sheet_view.showGridLines = False
            ws["A1"] = titulo
            ws["A1"].font = Font(name=FUENTE, size=14, bold=True)
            ws["A2"] = intro
            ws["A2"].font = gris_txt
            ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max(3, len(cols)))
            ws.row_dimensions[2].height = 30
            for i, (texto, ancho) in enumerate(cols, start=1):
                c = ws.cell(row=4, column=i, value=texto)
                c.font, c.fill, c.alignment, c.border = blanco, fondos["cab"], centro, borde
                ws.column_dimensions[get_column_letter(i)].width = ancho
            fila = 5
            if ejemplo:
                for i, v in enumerate(ejemplo, start=1):
                    c = ws.cell(row=fila, column=i, value=v)
                    c.font, c.fill, c.alignment, c.border = base, fondos["ej"], izq, borde
                fila += 1
            for datos_fila in filas:
                for i, v in enumerate(datos_fila, start=1):
                    c = ws.cell(row=fila, column=i, value=v)
                    c.font = base
                    c.fill = fondos["gris"] if i <= n_grises else fondos["ama"]
                    c.alignment = izq if i == 1 else centro
                    c.border = borde
                fila += 1
            ws.freeze_panes = ws.cell(row=5, column=2)
            for rango, opciones in (validaciones or {}).items():
                dv = DataValidation(type="list", formula1='"' + ",".join(opciones) + '"',
                                    allow_blank=True)
                ws.add_data_validation(dv)
                dv.add(f"{rango}5:{rango}{fila + 200}")
            return ws

        codigos = [t.codigo for t in d["turnos"]]
        man = [c for c, t in zip(codigos, d["turnos"]) if t.bloque == "MANANA"]
        tar = [c for c, t in zip(codigos, d["turnos"]) if t.bloque == "TARDE"]
        leyenda = "   ·   ".join(f"{t.codigo} = {t.hora_inicio:%H:%M}-{t.hora_fin:%H:%M}"
                                 for t in d["turnos"])

        # ---- 1. Leyenda
        ws = wb.active
        ws.title = "Cómo se rellena"
        ws.sheet_view.showGridLines = False
        ws.column_dimensions["A"].width = 120
        textos = [
            ("GTennis · recogida de datos", 16, True),
            (f"Franjas del club: {leyenda}", 11, False),
            ("", 11, False),
            ("Gris = lo que ya tiene la app, para que lo contrastes. Amarillo = lo que rellenas tú. Verde = ejemplo.", 11, False),
            ("Se puede escribir en corto: M1, M2, T1, 'no', '-', 'torneo', 'lesión'. Lo que no se entienda sale en un informe al importar.", 11, False),
            ("", 11, False),
            ("Las hojas, por orden:", 12, True),
            ("1. JUGADORES · la ficha de cada alumno: lo que no cambia de semana en semana.", 11, False),
            ("2. ENTRENADORES · la ficha de cada entrenador, con su grupo de divisiones y su jornada.", 11, False),
            ("3. SEMANA HABITUAL · qué días y a qué hora entrena normalmente cada alumno.", 11, False),
            (f"4. SEMANA EJEMPLO · la del {ejemplo_lunes:%d/%m}, ya rellena con lo que pasó, para ver cómo se rellena.", 11, False),
            (f"5. SEMANA A RELLENAR · la del {lunes:%d/%m}: día a día, turno, ausencia y torneo.", 11, False),
            ("6. AUSENCIAS Y TORNEOS · las que duran varios días, con fecha de ida y vuelta.", 11, False),
            ("7. REGLAS ESPECIALES · rencillas, contratos y parejas fijas.", 11, False),
            ("8. PREFERENCIAS DE PISTA · superficie y pista de cada alumno.", 11, False),
            ("", 11, False),
            ("Lo que el motor hace hoy con estos datos:", 12, True),
            ("· Empareja dentro de ±1 división, y menos aún si el alumno lo tiene declarado en su ficha.", 11, False),
            ("· Un chico no comparte pista con una chica de división más baja.", 11, False),
            ("· Por edades: de 10 a 14 años, como mucho dos de diferencia; de 15 a 18, tres.", 11, False),
            ("· Las divisiones de arriba entrenan en las primeras pistas, y siempre en tierra salvo que no quede.", 11, False),
            ("· Cada entrenador lleva su grupo de divisiones mientras se pueda; el grupo 1 es el más estricto.", 11, False),
            ("· Todos vienen todos los días salvo lo que se declare aquí. No hay cupo de sesiones por semana.", 11, False),
        ]
        for i, (t, tam, bold) in enumerate(textos, start=1):
            c = ws.cell(row=i, column=1, value=t)
            c.font = Font(name=FUENTE, size=tam, bold=bold)
            c.alignment = izq

        # ---- 2. Jugadores
        cols_j = [("Jugador", 28), ("Cód.", 8), ("Escuela", 15), ("División", 9),
                  ("Responsable", 20), ("Edad", 7), ("Chico/chica", 11),
                  ("Franja mañana", 12), ("Franja tarde", 12), ("Divisiones con las que entrena", 24),
                  ("Máx. al día", 9), ("Alta", 11), ("Baja", 11),
                  # amarillas
                  ("Escuela correcta", 16), ("División correcta", 12), ("Responsable correcto", 20),
                  ("Fecha de nacimiento", 15), ("Chico o chica", 12),
                  ("Entrena de normal · MAÑANA", 16), ("· TARDE", 12),
                  ("Con qué divisiones entrena", 24), ("Máx. sesiones al día", 12),
                  ("Entra el día", 12), ("Último día", 12), ("Notas", 40)]
        filas_j = []
        for j in d["jugadores"]:
            filas_j.append([
                j.nombre, j.codigo_cliente or "", j.escuela.nombre if j.escuela_id else "",
                f"D{j.division.nivel}" if j.division_id else "sin división",
                j.entrenador_responsable.nombre if j.entrenador_responsable_id else "— falta —",
                j.edad if j.edad is not None else "", j.get_sexo_display() if j.sexo else "— falta —",
                j.turno_manana.codigo if j.turno_manana_id else "cualquiera",
                j.turno_tarde.codigo if j.turno_tarde_id else "cualquiera",
                VECINDAD.get(j.vecindad, j.vecindad),
                j.sesiones_dia_max if j.sesiones_dia_max is not None else "2 (por defecto)",
                f"{j.fecha_alta:%d/%m/%Y}" if j.fecha_alta else "",
                f"{j.fecha_baja:%d/%m/%Y}" if j.fecha_baja else "",
                "", "", "", "", "", "", "", "", "", "", "", "",
            ])
        ejemplo_j = ["(ejemplo) Juan Pérez", "", "", "", "", "", "", "", "", "", "", "", "",
                     "Alto Rendimiento", "4", "Mario Muniesa", "12/03/2011", "Chico",
                     "M2", "T1", "su división y la de encima", "2", "16/09/2026", "", "los miércoles llega a las 11"]
        hoja("JUGADORES", "La ficha de cada alumno: lo que no cambia cada semana. "
             "En gris, lo que hay ahora en la app; escribe al lado solo lo que haya que corregir.",
             cols_j, 13, filas_j, ejemplo_j,
             {"R": ["Chico", "Chica"], "S": man + ["cualquiera"], "T": tar + ["cualquiera"],
              "U": list(VECINDAD.values())})

        # ---- 3. Entrenadores
        cols_e = [("Entrenador", 24), ("Grupo en la app", 14), ("Franja mañana", 12),
                  ("Franja tarde", 12), ("Banquillo", 10), ("Disponible", 10),
                  ("Grupo correcto · desde", 14), ("· hasta", 10),
                  ("Franja mañana", 12), ("Franja tarde", 12),
                  ("¿Solo a mano (banquillo)?", 14)] + [(f"{x} (mañana/tarde/no)", 14) for x in DIAS] + [("Notas", 40)]
        filas_e = []
        for e in d["entrenadores"]:
            grupo = (f"D{e.division_desde}-D{e.division_hasta}"
                     if e.division_desde or e.division_hasta else "cualquiera")
            filas_e.append([
                e.nombre, grupo,
                e.turno_manana.codigo if e.turno_manana_id else "cualquiera",
                e.turno_tarde.codigo if e.turno_tarde_id else "cualquiera",
                "sí" if e.reserva else "no", "sí" if e.disponible_semana else "no",
                "", "", "", "", "", "", "", "", "", "", "",
            ])
        ejemplo_e = ["(ejemplo) Mario Muniesa", "", "", "", "", "", "4", "6", "M2", "",
                     "no", "", "", "solo mañana", "", "no viene", "los viernes no viene"]
        hoja("ENTRENADORES", "La ficha de cada entrenador. El grupo son las divisiones que lleva: "
             "si no queda nadie de ese grupo cogerá otra pista, pero el motor lo evita.",
             cols_e, 6, filas_e, ejemplo_e,
             {"I": man + ["cualquiera"], "J": tar + ["cualquiera"], "K": ["sí", "no"]})

        # ---- 4. Semana habitual
        cols_h = [("Jugador", 28), ("División", 9)]
        for dia in DIAS:
            cols_h += [(f"{dia} · mañana", 13), (f"{dia} · tarde", 13)]
        filas_h = []
        for j in d["jugadores"]:
            fila = [j.nombre, f"D{j.division.nivel}" if j.division_id else ""]
            for i in range(5):
                h = d["horarios"].get((j.id, i))
                if h is None:
                    fila += ["", ""]
                else:
                    fila += [
                        (h.turno_manana.codigo if h.turno_manana_id else "sí") if h.entrena_manana else "no",
                        (h.turno_tarde.codigo if h.turno_tarde_id else "sí") if h.entrena_tarde else "no",
                    ]
            filas_h.append(fila)
        ejemplo_h = ["(ejemplo) Juan Pérez", "D4", "M2", "T1", "M2", "no", "M1", "no", "M2", "T1", "no", "no"]
        hoja("SEMANA HABITUAL", "Lo normal de cada alumno: a qué hora entrena cada día. "
             "M1/M2 por la mañana, T1 por la tarde, «no» si ese día no viene y vacío si da igual.",
             cols_h, 2, filas_h, ejemplo_h,
             {get_column_letter(3 + 2 * i): man + ["no"] for i in range(5)}
             | {get_column_letter(4 + 2 * i): tar + ["no"] for i in range(5)})

        # ---- 5. Semana ejemplo (ya vivida) y 6. semana a rellenar
        def hoja_semana(titulo, intro, lunes_hoja, relleno):
            cols = [("Jugador", 28), ("División", 9)]
            for i, dia in enumerate(DIAS):
                fecha = lunes_hoja + timedelta(days=i)
                cols += [(f"{dia} {fecha:%d/%m} · mañana", 13),
                         (f"{dia} {fecha:%d/%m} · tarde", 13),
                         (f"{dia} {fecha:%d/%m} · ausencia o torneo", 18)]
            filas = []
            for j in d["jugadores"]:
                fila = [j.nombre, f"D{j.division.nivel}" if j.division_id else ""]
                for i in range(5):
                    dia = (relleno.get(j.id) or {}).get(i, {}) if relleno else {}
                    fila += [dia.get("manana", ""), dia.get("tarde", ""), dia.get("motivo", "")]
                filas.append(fila)
            ejemplo = ["(ejemplo) Juan Pérez", "D4", "M2", "T1", "", "M2", "no", "",
                       "no", "no", "torneo en Alicante", "M1", "no", "", "M2", "T1", ""]
            val = {}
            for i in range(5):
                val[get_column_letter(3 + 3 * i)] = man + ["no"]
                val[get_column_letter(4 + 3 * i)] = tar + ["no"]
                val[get_column_letter(5 + 3 * i)] = [
                    "torneo", "lesión", "enfermedad", "estudios", "prueba médica", "vacaciones"]
            hoja(titulo, intro, cols, 2 if relleno else 2, filas, ejemplo, val)

        hoja_semana(f"SEMANA EJEMPLO {ejemplo_lunes:%d-%m}",
                    f"La semana del {ejemplo_lunes:%d/%m}, tal como quedó: sirve de muestra. "
                    "Cada día, la franja de la mañana, la de la tarde y el motivo si faltó.",
                    ejemplo_lunes, vivida)
        hoja_semana(f"SEMANA {lunes:%d-%m}",
                    f"La semana del {lunes:%d/%m}, para rellenar. Deja en blanco lo que sea lo "
                    "de siempre; escribe «no» el día que no venga y el motivo si es torneo o lesión.",
                    lunes, None)

        # ---- 7. Ausencias y torneos
        cols_a = [("Jugador o entrenador", 26), ("Qué es", 14), ("Desde", 12), ("Hasta", 12),
                  ("Qué se pierde", 18), ("Motivo", 20), ("Notas", 40)]
        hoja("AUSENCIAS Y TORNEOS",
             "Para lo que dura varios días: un torneo, una lesión, unas vacaciones. "
             "Lo de un solo día es más cómodo ponerlo en la hoja de la semana.",
             cols_a, 0, [],
             ["(ejemplo) Juan Pérez", "torneo", "02/10/2026", "09/10/2026", "todo el día",
              "torneo en Alicante", "vuelve el lunes 12"],
             {"B": ["torneo", "lesión", "enfermedad", "estudios", "prueba médica", "vacaciones"],
              "E": ["todo el día", "solo la mañana", "solo la tarde"] + codigos})

        # ---- 8. Reglas especiales
        cols_r = [("Tipo", 18), ("Jugador", 26), ("Con quién", 26), ("Detalle", 22), ("Notas", 40)]
        filas_r = []
        for c in d["contratos"]:
            filas_r.append(["contrato", c.jugador.nombre, c.entrenador.nombre,
                            "siempre con él" if c.tipo == "DURO" else "a ser posible", ""])
        for r in d["rencillas"]:
            filas_r.append(["rencilla", r.jugador_a.nombre, r.jugador_b.nombre, "nunca juntos", ""])
        for p in d["parejas"]:
            filas_r.append(["pareja fija", p.jugador.nombre, p.jugador_objetivo.nombre,
                            "siempre juntos" if p.tipo == "HARD" else "a ser posible", ""])
        hoja("REGLAS ESPECIALES",
             "Rencillas (nunca juntos), contratos (siempre con ese entrenador) y parejas fijas.",
             cols_r, 0, filas_r,
             ["(ejemplo) rencilla", "Juan Pérez", "Marco Ruiz", "nunca juntos", "se llevan fatal"],
             {"A": ["rencilla", "contrato", "pareja fija"],
              "D": ["nunca juntos", "siempre juntos", "a ser posible", "siempre con él"]})

        # ---- 9. Preferencias de pista
        cols_p = [("Jugador", 26), ("Superficie en la app", 16), ("Superficie", 14),
                  ("¿Obligatorio?", 12), ("Pistas preferidas", 18), ("Desde", 12), ("Hasta", 12), ("Notas", 36)]
        filas_p = []
        for j in d["jugadores"]:
            actuales = [p for p in d["superficies"] if p.jugador_id == j.id]
            filas_p.append([
                j.nombre,
                ", ".join(f"{p.get_superficie_display()}{' (obligatorio)' if p.estricta else ''}"
                          for p in actuales) or "",
                "", "", "", "", "", "",
            ])
        hoja("PREFERENCIAS DE PISTA",
             "Superficie y pistas de cada alumno. El club entrena en tierra por defecto: "
             "esto es para las excepciones.",
             cols_p, 2, filas_p,
             ["(ejemplo) Juan Pérez", "", "tierra", "sí", "1, 2, 3", "", "", "por la rodilla"],
             {"C": ["tierra", "resina"], "D": ["sí", "no"]})

        wb.save(opts["salida"])
        self.stdout.write(self.style.SUCCESS(
            f"Escrito {opts['salida']} · {len(d['jugadores'])} jugadores, "
            f"{len(d['entrenadores'])} entrenadores, semana a rellenar {lunes}, "
            f"ejemplo {ejemplo_lunes}" + ("" if semana_ej else " (sin datos)")))
