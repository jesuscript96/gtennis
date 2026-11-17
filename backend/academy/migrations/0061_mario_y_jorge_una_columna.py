"""Mario Muniesa y Jorge Ibáñez llevan el mismo grupo (17/11/2026, pedido del
club): en Grupos pasan a salir como una sola columna, «Mario Muniesa / Jorge
Ibáñez». Solo se apunta que Jorge comparte columna con Mario; su gestión (Mario
responsable, Jorge cogestor de los suyos) no cambia.

Se buscan por nombre sin acentos ni mayúsculas. Si no están los dos, o Jorge ya
tiene otra columna, no se toca nada. Deshacerla quita el enlace."""
import unicodedata

from django.db import migrations


def _clave(nombre):
    plano = unicodedata.normalize("NFKD", nombre or "")
    return " ".join("".join(c for c in plano if not unicodedata.combining(c)).lower().split())


def unir(apps, schema_editor):
    Entrenador = apps.get_model("academy", "Entrenador")
    por_clave = {}
    for e in Entrenador.objects.filter(activo=True):
        por_clave.setdefault(_clave(e.nombre), []).append(e)
    mario = por_clave.get("mario muniesa", [])
    jorge = por_clave.get("jorge ibanez", [])
    if len(mario) != 1 or len(jorge) != 1 or jorge[0].columna_con_id:
        return
    Entrenador.objects.filter(pk=jorge[0].pk).update(columna_con=mario[0].pk)


def separar(apps, schema_editor):
    Entrenador = apps.get_model("academy", "Entrenador")
    for e in Entrenador.objects.filter(columna_con__isnull=False):
        if _clave(e.nombre) == "jorge ibanez" and _clave(e.columna_con.nombre) == "mario muniesa":
            Entrenador.objects.filter(pk=e.pk).update(columna_con=None)


class Migration(migrations.Migration):

    dependencies = [("academy", "0060_columna_compartida")]

    operations = [migrations.RunPython(unir, separar)]
