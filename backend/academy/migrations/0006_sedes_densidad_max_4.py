from django.db import migrations


def subir_densidad_max(apps, schema_editor):
    """Todas las pistas pasan a admitir hasta 4 jugadores (forzado manual).
    Solo sube; nunca baja por debajo de la densidad por defecto de la sede."""
    Sede = apps.get_model("academy", "Sede")
    for sede in Sede.objects.all():
        nuevo = max(4, sede.densidad_default or 0)
        if sede.densidad_max != nuevo:
            sede.densidad_max = nuevo
            sede.save(update_fields=["densidad_max"])


def revertir(apps, schema_editor):
    # No-op: no restauramos el valor anterior (era 2 por defecto).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0005_alter_sede_densidad_max_feedback"),
    ]

    operations = [
        migrations.RunPython(subir_densidad_max, revertir),
    ]
