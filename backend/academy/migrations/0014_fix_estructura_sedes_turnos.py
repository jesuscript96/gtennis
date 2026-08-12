"""Corrige en producción la estructura REAL de sedes/pistas/turnos (feedback de
Sergio #7 #8 #1). Equivale a `seed_sedes` pero como migración de datos: corre
UNA sola vez en el próximo deploy y **no** vuelve a pisar las ediciones que el
club haga por la UI (a diferencia de meter el seed en el release_command).

Deja el estado definitivo:
    Resort        base, no satélite, pistas 1-6 tierra / 7-8 resina
    Sta. Bárbara  satélite, 3 pistas tierra
    Poli Bétera   satélite, 2 pistas resina
    Mas Camarena  satélite, 1 pista resina
    (Liria y cualquier otra sede se desactivan)
    M1 08:30-10:30 (verano 08:00-10:00)   M2 10:30-12:30 (10:00-12:00)
    T1 14:15-15:30 (14:00-15:15)          T2 15:30-16:45 (15:15-16:30)

La lógica se duplica aquí a propósito (apps.get_model, no el modelo real) para
que la migración quede congelada y no se rompa si el modelo evoluciona.
"""
from datetime import time

from django.db import migrations

# Nombres previos que deben mapearse al Resort (base histórica).
ALIAS_RESORT = ["Resort", "Central", "GTennis", "Gtennis", "Gtennis - Mascamarena"]

# nombre, orden_desbordamiento, nº pistas, superficie
SATELITES = [
    ("Sta. Bárbara", 1, 3, "TIERRA"),
    ("Poli Bétera", 2, 2, "RESINA"),
    ("Mas Camarena", 3, 1, "RESINA"),
]

# codigo, nombre, bloque, normal (ini, fin), verano (ini, fin), orden
TURNOS = [
    ("M1", "Mañana 1", "MANANA", (time(8, 30), time(10, 30)), (time(8, 0), time(10, 0)), 1),
    ("M2", "Mañana 2", "MANANA", (time(10, 30), time(12, 30)), (time(10, 0), time(12, 0)), 2),
    ("T1", "Tarde 1", "TARDE", (time(14, 15), time(15, 30)), (time(14, 0), time(15, 15)), 3),
    ("T2", "Tarde 2", "TARDE", (time(15, 30), time(16, 45)), (time(15, 15), time(16, 30)), 4),
]


def _ensure_pistas(Pista, sede, n, superficie):
    """Deja exactamente `n` pistas activas (1..n) con la superficie dada; las
    sobrantes se desactivan (no se borran: pueden tener historial)."""
    for i in range(1, n + 1):
        Pista.objects.update_or_create(
            sede=sede, numero=i,
            defaults={"superficie": superficie, "activa": True},
        )
    Pista.objects.filter(sede=sede, numero__gt=n).update(activa=False)


def forward(apps, schema_editor):
    Sede = apps.get_model("academy", "Sede")
    Pista = apps.get_model("academy", "Pista")
    Turno = apps.get_model("academy", "Turno")

    # 1) Resort (base). Reutiliza la sede base histórica si existe.
    resort = None
    for alias in ALIAS_RESORT:
        resort = Sede.objects.filter(nombre__iexact=alias).first()
        if resort:
            break
    if resort is None:
        resort = Sede.objects.filter(es_satelite=False).order_by("-id").first()
    if resort is None:
        resort = Sede.objects.create(nombre="Resort")
    resort.nombre = "Resort"
    resort.es_satelite = False
    resort.orden_desbordamiento = 0
    resort.densidad_default = 2
    resort.densidad_max = 4
    resort.activa = True
    resort.save()
    # Conserva sus pistas reales; superficies por plano: 1-6 tierra, 7-8 resina.
    if not resort.pistas.exists():
        _ensure_pistas(Pista, resort, 8, "RESINA")
    for p in resort.pistas.all():
        p.superficie = "TIERRA" if p.numero <= 6 else "RESINA"
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
        _ensure_pistas(Pista, sede, npistas, superficie)
        keep.add(sede.id)

    # 3) Cualquier otra sede (Liria, "Bétera" antigua, duplicados) se desactiva.
    Sede.objects.exclude(id__in=keep).exclude(activa=False).update(activa=False)

    # 4) Horarios de turno (normal + verano jul/ago).
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


def backward(apps, schema_editor):
    # Migración correctiva de datos: no tiene reversa segura.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0013_tareamantenimiento"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
