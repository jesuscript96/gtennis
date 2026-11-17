"""Jorge Mico es entrenador de pádel y no debe salir en la aplicación
(17/11/2026, pedido del club; el 29/10 ya se había dicho que no hacía informes).

Se le da de baja como a cualquier entrenador que deja de salir: su ficha de
entrenador pasa a inactiva (fuera del cuadrante y su banquillo, de Grupos, de
Hoy, de torneos, de faltas…) y su usuario también (no entra, y no sale en
Personas y funciones). No se borra nada: sus bloques, su ficha y el historial
siguen ahí, y darle de alta otra vez es marcar «Activo» en Entrenadores.

Se busca por nombre; si no hay un entrenador activo llamado así, no hace nada.
Lo que cambia queda en el archivo de migraciones: deshacerla lo deja como
estaba."""
import unicodedata

from django.db import migrations

from users import archivo_migraciones as archivo

NOMBRE = "academy.0063_jorge_mico_fuera_de_la_aplicacion"


def _clave(nombre):
    plano = unicodedata.normalize("NFKD", nombre or "")
    return " ".join("".join(c for c in plano if not unicodedata.combining(c)).lower().split())


def dar_de_baja(apps, schema_editor):
    Entrenador = apps.get_model("academy", "Entrenador")
    User = apps.get_model("users", "User")
    candidatos = [e for e in Entrenador.objects.filter(activo=True)
                  if _clave(e.nombre) == "jorge mico"]
    if len(candidatos) != 1:
        return
    ent = candidatos[0]
    archivo.guardar(apps, NOMBRE, "cambiado", ent, campos=["activo"])
    Entrenador.objects.filter(pk=ent.pk).update(activo=False)
    if ent.user_id:
        usuario = User.objects.filter(pk=ent.user_id, is_active=True).first()
        if usuario is not None:
            archivo.guardar(apps, NOMBRE, "cambiado", usuario, campos=["is_active"])
            User.objects.filter(pk=usuario.pk).update(is_active=False)


def deshacer(apps, schema_editor):
    archivo.deshacer(apps, NOMBRE)


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0062_gonzalo_chicote_ya_es_de_la_escuela"),
        ("users", "0006_funciones_iniciales"),
    ]

    operations = [migrations.RunPython(dar_de_baja, deshacer)]
