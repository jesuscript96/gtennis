"""Crea la franja aislada Junior Program (#6): 12:30-14:00 (verano 12:00-14:00),
exclusiva de la escuela Junior Program y siempre en el Resort. Reordena los
turnos de tarde para dejarla en su hueco cronológico: M1 · M2 · JP · T1 · T2.
"""
from datetime import time

from django.db import migrations


def forward(apps, schema_editor):
    Turno = apps.get_model("academy", "Turno")
    Escuela = apps.get_model("academy", "Escuela")

    jp = Escuela.objects.filter(nombre__icontains="junior").first()
    if jp is None:
        jp = Escuela.objects.create(nombre="Junior Program")

    # Hueco cronológico para JP entre la mañana y la tarde.
    Turno.objects.filter(codigo="T1").update(orden=4)
    Turno.objects.filter(codigo="T2").update(orden=5)

    Turno.objects.update_or_create(
        codigo="JP",
        defaults={
            "nombre": "Junior Program",
            "bloque": "MANANA",
            "hora_inicio": time(12, 30),
            "hora_fin": time(14, 0),
            "hora_inicio_verano": time(12, 0),
            "hora_fin_verano": time(14, 0),
            "orden": 3,
            "solo_escuela": jp,
        },
    )


def backward(apps, schema_editor):
    Turno = apps.get_model("academy", "Turno")
    Turno.objects.filter(codigo="JP").delete()
    Turno.objects.filter(codigo="T1").update(orden=3)
    Turno.objects.filter(codigo="T2").update(orden=4)


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0016_turno_solo_escuela"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
