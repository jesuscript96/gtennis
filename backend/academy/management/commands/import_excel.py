"""Extract real players and coaches from the academy's management Excel
(`PLANTILLA MAÑANAS`) and seed them. The sheet is a manual grid, so this is a
best-effort cleaner; Iván curates the rest in the admin (divisions, contracts,
rencillas — which the Excel does not contain).

Usage:
    python manage.py import_excel --file ~/Downloads/2026.xlsx
"""
import os
import re

from django.core.management.base import BaseCommand

from academy.models import Entrenador, Jugador

PLAYER_COLS = [2, 5, 8, 11, 14, 17]        # B,E,H,K,N,Q
COACH_COLS = [3, 6, 9, 12, 15, 18, 20]     # C,F,I,L,O,R,T

SKIP = {
    "PISTA", "ENTRENADORES", "TORNEO", "SESION", "SESIÓN", "DOMINGO", "SABADO",
    "SÁBADO", "LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES",
    "STA. BARBARA", "STA. BÁRBARA", "GRUPO ADULTOS", "CUBOS Y CONTROLES",
}
TIME_RE = re.compile(r"\b\d{1,2}[.:]\d{2}\b")
AGE_RE = re.compile(r"\s(\d{1,2})\s*$")
DAYS_RE = re.compile(r"\b[LMXJVSD](\s*[,yY]\s*[LMXJVSD])+\b.*$")


def clean(value):
    """Return (name, age) or (None, None) if the cell isn't a real name."""
    if value is None:
        return None, None
    s = str(value).strip()
    if not s or s.upper() in SKIP:
        return None, None
    if any(s.upper().startswith(p) for p in ("PISTA", "GRUPO", "CUBOS", "SESION")):
        return None, None
    # Pure numbers / court ids / times.
    if re.fullmatch(r"[\d.,:\s]+", s):
        return None, None
    age = None
    m = AGE_RE.search(s)
    if m:
        n = int(m.group(1))
        if 6 <= n <= 20:
            age = n
        s = AGE_RE.sub("", s)
    s = TIME_RE.sub("", s)
    s = re.sub(r"\b(a|de|hasta)\b\s*$", "", s, flags=re.I)
    s = DAYS_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" .,-")
    # Keep plausible person names: letters + at least one space (first+last).
    if len(s) < 4 or not re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", s):
        return None, None
    if sum(c.isdigit() for c in s) > 0:
        return None, None
    return s, age


class Command(BaseCommand):
    help = "Import players and coaches from the academy Excel."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file", default=os.path.expanduser("~/Downloads/2026.xlsx")
        )
        parser.add_argument("--sheet", default="PLANTILLA MAÑANAS 20252026")

    def handle(self, *args, **opts):
        import openpyxl

        wb = openpyxl.load_workbook(opts["file"], data_only=True, read_only=True)
        ws = wb[opts["sheet"]]

        players: dict[str, int | None] = {}
        coaches: set[str] = set()
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                name, age = clean(cell.value)
                if not name:
                    continue
                if cell.column in PLAYER_COLS:
                    if name not in players or (age and not players[name]):
                        players[name] = age
                elif cell.column in COACH_COLS:
                    # In this sheet real coaches are written as uppercase codes
                    # ("VICTOR M.", "JORGE I."); mixed-case cells are leaked
                    # players and are ignored here (captured from PLAYER_COLS).
                    if name == name.upper() and age is None:
                        coaches.add(name)

        # Coaches that also appear as players -> treat as coaches only.
        for c in coaches:
            players.pop(c, None)

        n_coach = 0
        for name in sorted(coaches):
            _, created = Entrenador.objects.get_or_create(nombre=name)
            n_coach += int(created)
        n_play = 0
        for name, age in sorted(players.items()):
            obj, created = Jugador.objects.get_or_create(
                nombre=name, defaults={"edad": age}
            )
            if not created and age and not obj.edad:
                obj.edad = age
                obj.save(update_fields=["edad", "es_menor"])
            n_play += int(created)

        self.stdout.write(self.style.SUCCESS(
            f"Importados {n_play} jugadores nuevos ({len(players)} totales) y "
            f"{n_coach} entrenadores nuevos ({len(coaches)} totales)."
        ))
