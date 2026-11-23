"""Puesto en el ranking para quien volvió de una baja (23/11/2026).

Lucca Helguera estaba de baja cuando se ordenó la División 2 y, al darle de
alta el 16/11, se quedó sin puesto: salía al final sin número. Quien esté
activo sin puesto en una división que ya tiene ranking pasa a ser el último
de ella (por nombre si hay varios), como quien cambia de división. Las
divisiones sin ranking no se tocan.

Lo que cambia queda en el archivo de migraciones: deshacerla lo deja como
estaba."""
from django.db import migrations
from django.db.models import Max

from users import archivo_migraciones as archivo

NOMBRE = "academy.0067_puesto_a_quien_volvio_de_baja"


def poner_al_final(apps, schema_editor):
    Jugador = apps.get_model("academy", "Jugador")
    sin_puesto = (Jugador.objects.filter(activo=True, orden_division__isnull=True,
                                         division__isnull=False)
                  .order_by("division_id", "nombre"))
    for j in sin_puesto:
        ultimo = (Jugador.objects.filter(division_id=j.division_id, activo=True,
                                         orden_division__isnull=False)
                  .aggregate(m=Max("orden_division"))["m"])
        if ultimo is None:
            continue
        archivo.guardar(apps, NOMBRE, "cambiado", j, campos=["orden_division"])
        Jugador.objects.filter(pk=j.pk).update(orden_division=ultimo + 1)


def deshacer(apps, schema_editor):
    archivo.deshacer(apps, NOMBRE)


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0066_resort_y_satelites"),
        ("users", "0007_funciones_preparacion_fisica"),
    ]

    operations = [migrations.RunPython(poner_al_final, deshacer)]
