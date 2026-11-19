"""Dos preparadores físicos nuevos y el reparto de la física (19/11/2026).

  * alex.ante (Alex Ante): preparador físico de Alto rendimiento.
  * santiago.pico (Santiago Pico): preparador físico de Competición de tardes
    (entra en el equipo de física de tardes).
  * josep.mari reparte («Coordina preparación física») y hace la física de las
    dos escuelas: ya estaba en el equipo de tardes y se le marca «Evalúa física
    de Alto rendimiento».

Las cuentas nuevas llevan la contraseña inicial de las altas del club
(`setup_usuarios_prod`), que cada uno cambia en «Mi cuenta». Si una cuenta ya
existe, no se le toca la contraseña.

Solo en la base del club (donde está josep.mari): en una base nueva o en las
pruebas no hace nada. Lo que crea queda en el archivo de migraciones y al
deshacerla se quita exactamente eso.
"""
from django.contrib.auth.hashers import make_password
from django.db import migrations

from users import archivo_migraciones as archivo

NOMBRE = "evaluaciones.0013_preparadores_fisicos"
NUEVOS = [("alex.ante", "Alex", "Ante"), ("santiago.pico", "Santiago", "Pico")]
FUNCIONES = {"josep.mari": ["COORDINA_FISICO", "FISICO_AR"], "alex.ante": ["FISICO_AR"]}
EQUIPO_TARDES = ["santiago.pico"]


def aplicar(apps, schema_editor):
    from academy.management.commands.setup_usuarios_prod import PASSWORD_DEFAULT

    User = apps.get_model("users", "User")
    Funcion = apps.get_model("users", "Funcion")
    Miembro = apps.get_model("evaluaciones", "MiembroTardes")
    if not User.objects.filter(username="josep.mari").exists():
        return
    for username, nombre, apellido in NUEVOS:
        if User.objects.filter(username=username).exists():
            continue
        u = User.objects.create(username=username, first_name=nombre, last_name=apellido,
                                role="PREPARADOR", is_active=True, password=make_password(PASSWORD_DEFAULT))
        archivo.guardar(apps, NOMBRE, "creado", u)
    for username, codigos in FUNCIONES.items():
        u = User.objects.filter(username=username).first()
        if u is None:
            continue
        for codigo in codigos:
            f, creada = Funcion.objects.get_or_create(usuario=u, codigo=codigo)
            if creada:
                archivo.guardar(apps, NOMBRE, "creado", f)
    for username in EQUIPO_TARDES:
        u = User.objects.filter(username=username).first()
        if u is None:
            continue
        m, creado = Miembro.objects.get_or_create(usuario=u, funcion="FISICO")
        if creado:
            archivo.guardar(apps, NOMBRE, "creado", m)


def deshacer(apps, schema_editor):
    archivo.deshacer(apps, NOMBRE)


class Migration(migrations.Migration):

    dependencies = [
        ("evaluaciones", "0012_reparto_fisico"),
        ("users", "0007_funciones_preparacion_fisica"),
    ]

    operations = [migrations.RunPython(aplicar, deshacer)]
