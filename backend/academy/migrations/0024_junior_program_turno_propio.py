"""Restaura Junior Program como TURNO propio (#6, feedback de Sergio).

La migración 0022 había interpretado JP como 'una escuela que solo va en M2'.
Sergio confirma que JP es un TURNO aparte con su propia columna en el
cuadrante, entre M2 y T1, con jugadores exclusivos y siempre en el Resort.

Esta migración:
  1. Crea (o restaura) el turno JP entre M2 y T1: orden M1·M2·JP·T1·T2.
  2. Pone Junior Program.escuela.turno_unico = JP, solo_central = True.
  3. Limpia Alto Rendimiento.escuela.turno_unico = None: sus jugadores vuelven
     a jugar en M1 y M2 (turnos de mañana compartidos), no en JP.

El motor (engine/service._available_players) ya excluye a los jugadores de una
escuela con turno_unico de los demás turnos. Falta la regla inversa (que
jugadores que NO sean de la escuela JP no caigan en el turno JP), que se
implementa en código en este mismo commit.
"""
from datetime import time

from django.db import migrations


def forward(apps, schema_editor):
    Turno = apps.get_model("academy", "Turno")
    Escuela = apps.get_model("academy", "Escuela")

    # 1) Reordenar: M1·M2·JP·T1·T2
    Turno.objects.filter(codigo="M1").update(orden=1)
    Turno.objects.filter(codigo="M2").update(orden=2)
    Turno.objects.filter(codigo="T1").update(orden=4)
    Turno.objects.filter(codigo="T2").update(orden=5)

    # 2) Crear/restaurar el turno JP entre M2 y T1 (orden 3), bloque mañana.
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
        },
    )

    # 3) Junior Program → turno exclusivo JP, solo Resort.
    jp_turno = Turno.objects.filter(codigo="JP").first()
    jp_esc = Escuela.objects.filter(nombre__icontains="junior").first()
    if jp_turno and jp_esc:
        jp_esc.turno_unico = jp_turno
        jp_esc.solo_central = True
        jp_esc.save(update_fields=["turno_unico", "solo_central"])

    # 4) Alto Rendimiento → sin turno exclusivo (juegan en M1 y M2).
    ar_esc = Escuela.objects.filter(nombre__icontains="alto rendimiento").first()
    if ar_esc is not None and ar_esc.turno_unico_id is not None:
        ar_esc.turno_unico = None
        ar_esc.save(update_fields=["turno_unico"])


def backward(apps, schema_editor):
    Turno = apps.get_model("academy", "Turno")
    Escuela = apps.get_model("academy", "Escuela")
    jp_turno = Turno.objects.filter(codigo="JP").first()
    if jp_turno is not None:
        jp_esc = Escuela.objects.filter(nombre__icontains="junior").first()
        if jp_esc:
            jp_esc.turno_unico = None
            jp_esc.solo_central = False
            jp_esc.save(update_fields=["turno_unico", "solo_central"])
        jp_turno.delete()
    Turno.objects.filter(codigo="T1").update(orden=3)
    Turno.objects.filter(codigo="T2").update(orden=4)


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0023_desactivar_sedes_duplicadas"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
