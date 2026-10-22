from django.db import migrations, models

# 22/10/2026: cuando faltan entrenadores salen, por este orden, Dani Gimeno,
# Sergio Gallego, Iván Gallego y Jorge García.
ORDEN = ["Daniel Gimeno", "Sergio Gallego", "Ivan Gallego", "Jorge Garcia"]


def poner_orden(apps, schema_editor):
    Entrenador = apps.get_model("academy", "Entrenador")
    for n, nombre in enumerate(ORDEN, start=1):
        Entrenador.objects.filter(nombre__iexact=nombre).update(orden_banquillo=n)


class Migration(migrations.Migration):
    dependencies = [("academy", "0055_escuela_solo_informes")]

    operations = [
        migrations.AddField(
            model_name="entrenador",
            name="orden_banquillo",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name="Orden en el banquillo",
                help_text="1 = el primero que sale cuando faltan entrenadores. "
                          "Vacío = el motor no le saca para cubrir pistas."),
        ),
        migrations.RunPython(poner_orden, migrations.RunPython.noop),
    ]
