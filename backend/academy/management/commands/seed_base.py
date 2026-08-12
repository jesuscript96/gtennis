"""Seed determinista de la estructura del club: sedes, pistas (con superficie),
turnos (con horario de verano) y la escala de divisiones 1-8.

La estructura real de la academia (feedback de Sergio #7/#8/#1):
    Resort        base, 6 tierra (P1-P6) + 2 resina (P7-P8)
    Sta. Bárbara  satélite, 3 tierra
    Poli Bétera   satélite, 2 resina
    Mas Camarena  satélite, 1 resina
    (Liria, Bétera vieja y Central ya no se usan; están inactivos)

Turnos: M1·M2·JP·T1·T2 (JP entre M2 y T1, exclusivo de Junior Program).

Idempotente: reentry safe. NO reactiva sedes inactivas (no incluye activa=True
en defaults; respeta lo que diga la migración).
"""
from datetime import time

from django.core.management.base import BaseCommand

from academy.models import Division, Pista, Sede, Turno

# (nombre, es_satelite, densidad_default, densidad_max, orden, [(num, sup), ...])
SEDES = [
    ("Resort", False, 2, 4, 0, [
        (1, Pista.Superficie.TIERRA), (2, Pista.Superficie.TIERRA),
        (3, Pista.Superficie.TIERRA), (4, Pista.Superficie.TIERRA),
        (5, Pista.Superficie.TIERRA), (6, Pista.Superficie.TIERRA),
        (7, Pista.Superficie.RESINA),  (8, Pista.Superficie.RESINA),
    ]),
    ("Sta. Bárbara", True, 2, 4, 1, [
        (1, Pista.Superficie.TIERRA),
        (2, Pista.Superficie.TIERRA),
        (3, Pista.Superficie.TIERRA),
    ]),
    ("Poli Bétera", True, 2, 4, 2, [
        (1, Pista.Superficie.RESINA),
        (2, Pista.Superficie.RESINA),
    ]),
    ("Mas Camarena", True, 2, 4, 3, [
        (1, Pista.Superficie.RESINA),
    ]),
]

# (codigo, nombre, bloque, normal(ini,fin), verano(ini,fin), orden)
TURNOS = [
    ("M1", "Mañana 1 — técnico/táctico", Turno.Bloque.MANANA,
     (time(8, 30), time(10, 30)), (time(8, 0), time(10, 0)), 1),
    ("M2", "Mañana 2 — rotación de parejas", Turno.Bloque.MANANA,
     (time(10, 30), time(12, 30)), (time(10, 0), time(12, 0)), 2),
    ("JP", "Junior Program", Turno.Bloque.MANANA,
     (time(12, 30), time(14, 0)), (time(12, 0), time(14, 0)), 3),
    ("T1", "Tarde 1 — bloque A", Turno.Bloque.TARDE,
     (time(14, 15), time(15, 30)), (time(14, 0), time(15, 15)), 4),
    ("T2", "Tarde 2 — bloque B", Turno.Bloque.TARDE,
     (time(15, 30), time(16, 45)), (time(15, 15), time(16, 30)), 5),
]


class Command(BaseCommand):
    help = "Seed venues, courts (with surface), shifts (with summer) and divisions."

    def handle(self, *args, **opts):
        for nombre, sat, dd, dm, orden, pistas in SEDES:
            sede, _ = Sede.objects.update_or_create(
                nombre=nombre,
                defaults={
                    "es_satelite": sat, "densidad_default": dd,
                    "densidad_max": dm, "orden_desbordamiento": orden,
                },
            )
            for num, sup in pistas:
                Pista.objects.update_or_create(
                    sede=sede, numero=num,
                    defaults={"superficie": sup, "activa": True},
                )

        for codigo, nombre, bloque, (ini, fin), (ini_v, fin_v), orden in TURNOS:
            Turno.objects.update_or_create(
                codigo=codigo,
                defaults={
                    "nombre": nombre, "bloque": bloque,
                    "hora_inicio": ini, "hora_fin": fin,
                    "hora_inicio_verano": ini_v, "hora_fin_verano": fin_v,
                    "orden": orden,
                },
            )

        for nivel in range(1, 9):
            Division.objects.get_or_create(
                nivel=nivel, defaults={"nombre": f"División {nivel}"}
            )

        self.stdout.write(self.style.SUCCESS(
            f"Base lista: {Sede.objects.filter(activa=True).count()} sedes activas, "
            f"{Pista.objects.filter(activa=True).count()} pistas activas, "
            f"{Turno.objects.count()} turnos, "
            f"{Division.objects.count()} divisiones."
        ))
