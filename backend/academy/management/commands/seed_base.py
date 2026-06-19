"""Create the deterministic structure from the PRD: venues, courts, the 4 fixed
shifts and an empty 1-8 division scale. Idempotent."""
from datetime import time

from django.core.management.base import BaseCommand

from academy.models import Division, Pista, Sede, Turno

SEDES = [
    # nombre, es_satelite, densidad_default, densidad_max, orden, n_pistas
    ("Central", False, 2, 2, 0, 8),
    ("Sta. Bárbara", True, 2, 4, 1, 4),
    ("Bétera", True, 2, 2, 2, 2),
    ("Liria", True, 2, 2, 3, 2),
]

TURNOS = [
    ("M1", "Mañana 1 — técnico/táctico", Turno.Bloque.MANANA, time(8, 30), time(10, 0), 1),
    ("M2", "Mañana 2 — rotación de parejas", Turno.Bloque.MANANA, time(10, 30), time(12, 30), 2),
    ("T1", "Tarde 1 — bloque A", Turno.Bloque.TARDE, time(14, 15), time(15, 30), 3),
    ("T2", "Tarde 2 — bloque B", Turno.Bloque.TARDE, time(15, 30), time(16, 45), 4),
]


class Command(BaseCommand):
    help = "Seed venues, courts, shifts and the division scale."

    def handle(self, *args, **opts):
        for nombre, sat, dd, dm, orden, n in SEDES:
            sede, _ = Sede.objects.update_or_create(
                nombre=nombre,
                defaults={
                    "es_satelite": sat, "densidad_default": dd,
                    "densidad_max": dm, "orden_desbordamiento": orden,
                },
            )
            for i in range(1, n + 1):
                Pista.objects.get_or_create(sede=sede, numero=i)

        for codigo, nombre, bloque, ini, fin, orden in TURNOS:
            Turno.objects.update_or_create(
                codigo=codigo,
                defaults={"nombre": nombre, "bloque": bloque,
                          "hora_inicio": ini, "hora_fin": fin, "orden": orden},
            )

        for nivel in range(1, 9):
            Division.objects.get_or_create(
                nivel=nivel, defaults={"nombre": f"División {nivel}"}
            )

        self.stdout.write(self.style.SUCCESS(
            f"Base lista: {Sede.objects.count()} sedes, "
            f"{Pista.objects.count()} pistas, {Turno.objects.count()} turnos, "
            f"{Division.objects.count()} divisiones."
        ))
