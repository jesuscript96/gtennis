"""Deja los turnos en los cinco definitivos: M1, M2, JP, T1, T2.

La segunda franja de tarde es la de 15:30 a 17:30 — la que la dirección
confirmó que se mantiene — pero se llamaba T3 porque nació junto a las de la
escuela de noche. Se le devuelve el código T2, que es el que le toca por
orden, y desaparece la vieja T2 de 15:30-16:45 que no se usa.

Importa más de lo que parece: el selector de ausencias ofrece los ámbitos por
código (M1, M2, T1, T2), así que mientras la franja se llamara T3 **no se podía
declarar que un alumno falta por la tarde** — el código no existía en la lista.
"""
from django.db import migrations

FUERA = ["T4", "T5"]


def forward(apps, schema_editor):
    Turno = apps.get_model("academy", "Turno")

    # La vieja T2 (15:30-16:45) no se usa y su código lo necesita la buena.
    Turno.objects.filter(codigo="T2", hora_fin__lt="17:00").delete()
    Turno.objects.filter(codigo="T3").update(
        codigo="T2", nombre="Tarde 2", orden=5, activo=True
    )
    # Las de escuela de noche siguen existiendo pero fuera del reparto.
    Turno.objects.filter(codigo__in=FUERA).update(activo=False)
    Turno.objects.filter(codigo__in=["M1", "M2", "JP", "T1", "T2"]).update(activo=True)


def backward(apps, schema_editor):
    Turno = apps.get_model("academy", "Turno")
    Turno.objects.filter(codigo="T2").update(codigo="T3", nombre="Escuela tarde", orden=6)


class Migration(migrations.Migration):

    dependencies = [("academy", "0032_jornada_semanal_entrenador")]

    operations = [migrations.RunPython(forward, backward)]
