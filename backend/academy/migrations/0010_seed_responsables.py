from django.db import migrations


def volcar_responsables(apps, schema_editor):
    """Cada jugador con entrenador_responsable pasa a tener un ResponsableJugador
    de prioridad 1 (el principal). Idempotente."""
    Jugador = apps.get_model("academy", "Jugador")
    ResponsableJugador = apps.get_model("academy", "ResponsableJugador")
    for j in Jugador.objects.filter(entrenador_responsable__isnull=False):
        ResponsableJugador.objects.get_or_create(
            jugador_id=j.id,
            entrenador_id=j.entrenador_responsable_id,
            defaults={"prioridad": 1, "porcentaje_objetivo": 0, "activo": True},
        )


def revertir(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0009_responsablejugador"),
    ]

    operations = [
        migrations.RunPython(volcar_responsables, revertir),
    ]
