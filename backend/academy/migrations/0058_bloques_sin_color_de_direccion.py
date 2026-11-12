"""Los bloques sin color de quien ya es dirección (Sergio e Iván, que
abarcaban a los 18 entrenadores) se desactivan: como dirección ya lo ven todo,
y el bloque solo servía para repartir porcentajes del 6 % y avisos de más
(10/11/2026, decisión 9). Se desactivan, no se borran, y cuáles eran queda en
el archivo de migraciones: deshacerla reactiva exactamente esos (11/11/2026)."""
from django.db import migrations
from django.db.models import Q

from users import archivo_migraciones as archivo

NOMBRE = "academy.0058_bloques_sin_color_de_direccion"


def desactivar(apps, schema_editor):
    Coach = apps.get_model("academy", "Coach")
    for c in Coach.objects.filter(color="", activo=True).filter(
            Q(user__role="SUPERADMIN") | Q(user__is_superuser=True)):
        archivo.guardar(apps, NOMBRE, "cambiado", c, campos=["activo"])
        Coach.objects.filter(pk=c.pk).update(activo=False)


def reactivar(apps, schema_editor):
    archivo.deshacer(apps, NOMBRE)


class Migration(migrations.Migration):

    dependencies = [("academy", "0057_orden_division"), ("users", "0006_funciones_iniciales")]

    operations = [migrations.RunPython(desactivar, reactivar)]
