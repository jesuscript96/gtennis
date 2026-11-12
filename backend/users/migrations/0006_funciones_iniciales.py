"""Pasa a funciones lo que hasta hoy eran listas de nombres en el código, y
aplica las decisiones 9 y 10 del documento «cómo poner orden en la aplicación»
(10/11/2026).

  * Toca el cuadrante: los head coaches de color, que ya rehacían el cuadrante
    (decisión 1: quien rehace, también mueve y deshace).
  * Aprueba invitados: Dani Gimeno (antes, lista APRUEBAN_INVITADOS).
  * Coordina Competición de tardes: Alberto Sanz.
  * Valida informes: Alberto Sanz y Dani Gimeno (antes validaban por la lista
    de gestión deportiva y por coordinar).
  * Iván Gallego pasa a dirección y la cuenta «ivan» se da de baja (decisión 9).
  * La cuenta «administracion» pasa al perfil Administración (decisión 10).

Si una cuenta no existe (base nueva, pruebas), se salta. Todo lo que cambia
queda en el archivo de migraciones (11/11/2026): deshacerla deja cada cuenta
exactamente como estaba y quita solo las funciones que puso ella.
"""
from django.db import migrations

from users import archivo_migraciones as archivo

NOMBRE = "users.0006_funciones_iniciales"
INICIALES = {
    "daniel.gimeno": ["TOCA_CUADRANTE", "APRUEBA_INVITADOS", "VALIDA_INFORMES"],
    "pablo.gil": ["TOCA_CUADRANTE"],
    "santi.panzarassa": ["TOCA_CUADRANTE"],
    "alberto.sanz": ["COORDINA_TARDES", "VALIDA_INFORMES"],
}
CAMBIOS = {
    "ivan.gallego": {"role": "SUPERADMIN"},
    "ivan": {"is_active": False},
    "administracion": {"role": "ADMINISTRACION", "is_superuser": False, "is_staff": False},
}


def aplicar(apps, schema_editor):
    User = apps.get_model("users", "User")
    Funcion = apps.get_model("users", "Funcion")
    for username, codigos in INICIALES.items():
        u = User.objects.filter(username=username).first()
        if u is None:
            continue
        for codigo in codigos:
            f, creada = Funcion.objects.get_or_create(usuario=u, codigo=codigo)
            if creada:
                archivo.guardar(apps, NOMBRE, "creado", f)
    for username, cambios in CAMBIOS.items():
        u = User.objects.filter(username=username).first()
        if u is None:
            continue
        archivo.guardar(apps, NOMBRE, "cambiado", u, campos=list(cambios))
        User.objects.filter(pk=u.pk).update(**cambios)


def deshacer(apps, schema_editor):
    archivo.deshacer(apps, NOMBRE)


class Migration(migrations.Migration):

    dependencies = [("users", "0005_archivo_migraciones")]

    operations = [migrations.RunPython(aplicar, deshacer)]
