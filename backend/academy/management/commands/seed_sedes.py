"""Deja la estructura REAL de recintos y horarios de la escuela (feedback de
Sergio, #8/#1/#7). Idempotente: se puede re-ejecutar sin duplicar.

Sedes definitivas y orden de desbordamiento:
    0  Resort         (base, no satélite)   — conserva sus pistas actuales
    1  Sta. Bárbara   (satélite)  3 pistas  tierra
    2  Poli Bétera    (satélite)  2 pistas  resina
    3  Mas Camarena   (satélite)  1 pista   resina
Cualquier otra sede se desactiva (p. ej. Liria).

Horarios de turno (normal / julio-agosto):
    M1 08:30-10:30 / 08:00-10:00
    M2 10:30-12:30 / 10:00-12:00
    T1 14:15-15:30 / 14:00-15:15
    T2 15:30-16:45 / 15:15-16:30
"""
from datetime import time

from django.core.management.base import BaseCommand
from django.db import transaction

from academy.models import Pista, Sede, Turno

RESORT = "Resort"
# Nombres previos que deben mapearse al Resort (base histórica).
ALIAS_RESORT = ["Resort", "Central", "GTennis", "Gtennis", "Gtennis - Mascamarena"]

SATELITES = [
    # nombre, orden, nº pistas, superficie
    ("Sta. Bárbara", 1, 3, Pista.Superficie.TIERRA),
    ("Poli Bétera", 2, 2, Pista.Superficie.RESINA),
    ("Mas Camarena", 3, 1, Pista.Superficie.RESINA),
]

TURNOS = [
    # codigo, nombre, bloque, normal (ini,fin), verano (ini,fin), orden
    ("M1", "Mañana 1", Turno.Bloque.MANANA, (time(8, 30), time(10, 30)), (time(8, 0), time(10, 0)), 1),
    ("M2", "Mañana 2", Turno.Bloque.MANANA, (time(10, 30), time(12, 30)), (time(10, 0), time(12, 0)), 2),
    ("T1", "Tarde 1", Turno.Bloque.TARDE, (time(14, 15), time(15, 30)), (time(14, 0), time(15, 15)), 3),
    ("T2", "Tarde 2", Turno.Bloque.TARDE, (time(15, 30), time(16, 45)), (time(15, 15), time(16, 30)), 4),
]


class Command(BaseCommand):
    help = "Siembra las 4 sedes reales, sus pistas/superficies y los horarios de turno."

    def _ensure_pistas(self, sede, n, superficie):
        """Deja exactamente `n` pistas activas (1..n) con la superficie dada.
        Las pistas sobrantes se desactivan (no se borran: pueden tener historial)."""
        for i in range(1, n + 1):
            Pista.objects.update_or_create(
                sede=sede, numero=i,
                defaults={"superficie": superficie, "activa": True},
            )
        Pista.objects.filter(sede=sede, numero__gt=n).update(activa=False)

    @transaction.atomic
    def handle(self, *args, **opts):
        # 1) Resort (base). Reutiliza la sede base histórica si existe.
        resort = None
        for alias in ALIAS_RESORT:
            resort = Sede.objects.filter(nombre__iexact=alias).first()
            if resort:
                break
        if resort is None:
            resort = Sede.objects.filter(es_satelite=False).order_by("-id").first()
        if resort is None:
            resort = Sede.objects.create(nombre=RESORT)
        resort.nombre = RESORT
        resort.es_satelite = False
        resort.orden_desbordamiento = 0
        resort.densidad_default = 2
        resort.densidad_max = 4
        resort.activa = True
        resort.save()
        # El Resort conserva sus pistas y su disposición real del club (3
        # columnas). Superficies según el plano: pistas 1-6 tierra, 7-8 resina.
        if not resort.pistas.exists():
            self._ensure_pistas(resort, 8, Pista.Superficie.RESINA)
        for p in resort.pistas.all():
            p.superficie = (
                Pista.Superficie.TIERRA if p.numero <= 6 else Pista.Superficie.RESINA
            )
            p.save(update_fields=["superficie"])
        keep = {resort.id}

        # 2) Satélites reales.
        for nombre, orden, npistas, superficie in SATELITES:
            sede, _ = Sede.objects.get_or_create(nombre=nombre)
            sede.es_satelite = True
            sede.orden_desbordamiento = orden
            sede.densidad_default = 2
            sede.densidad_max = 4
            sede.activa = True
            sede.save()
            self._ensure_pistas(sede, npistas, superficie)
            keep.add(sede.id)

        # 3) Cualquier otra sede (Liria, Base militar, duplicados) se desactiva.
        desactivadas = (
            Sede.objects.exclude(id__in=keep).exclude(activa=False)
        )
        nombres_off = list(desactivadas.values_list("nombre", flat=True))
        desactivadas.update(activa=False)

        # 4) Horarios de turno (normal + verano).
        for codigo, nombre, bloque, (ni, nf), (vi, vf), orden in TURNOS:
            Turno.objects.update_or_create(
                codigo=codigo,
                defaults={
                    "nombre": nombre, "bloque": bloque,
                    "hora_inicio": ni, "hora_fin": nf,
                    "hora_inicio_verano": vi, "hora_fin_verano": vf,
                    "orden": orden,
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f"Sedes activas: Resort ({resort.pistas.filter(activa=True).count()} pistas) + "
            + ", ".join(f"{n} ({p} pistas {s.lower()})" for n, _, p, s in SATELITES)
            + (f"\nDesactivadas: {', '.join(nombres_off)}" if nombres_off else "")
            + "\nTurnos actualizados con horario normal + verano (jul/ago)."
        ))
