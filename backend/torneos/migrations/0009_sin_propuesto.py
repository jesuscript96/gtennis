"""Fuera el estado «Propuesto (pendiente de validar)» de los torneos: nadie lo
validaba (10/11/2026). Los que lo tuvieran pasan a validados; cuáles eran queda
en el archivo de migraciones y deshacerla los devuelve a «Propuesto»
(11/11/2026). El cambio de opciones del campo va en la 0010, aparte: en
Postgres no conviene mezclar datos y estructura en la misma migración."""
from django.db import migrations

from users import archivo_migraciones as archivo

NOMBRE = "torneos.0009_sin_propuesto"


def a_validado(apps, schema_editor):
    Torneo = apps.get_model("torneos", "Torneo")
    for t in Torneo.objects.filter(estado="PROPUESTO"):
        archivo.guardar(apps, NOMBRE, "cambiado", t, campos=["estado"])
        Torneo.objects.filter(pk=t.pk).update(estado="VALIDADO")


def deshacer(apps, schema_editor):
    archivo.deshacer(apps, NOMBRE)


class Migration(migrations.Migration):

    dependencies = [("torneos", "0008_fecha_borrado"), ("users", "0005_archivo_migraciones")]

    operations = [migrations.RunPython(a_validado, deshacer)]
