"""Entrenadores y el duplicado de Gonzalo Chicote (19/11/2026, pedido del club).

1. Alberto Sanz no entrena en Alto Rendimiento: no debe salir en los
   entrenamientos ni en el banquillo. Su ficha de entrenador pasa a inactiva
   (fuera del cuadrante, Grupos, Hoy, torneos, faltas…), pero su USUARIO SIGUE
   ACTIVO: coordina Competición de tardes y hace sus informes (`MiembroTardes`
   va por usuario, no por ficha de entrenador).

2. Jorge Milla y Salva Barcala entrenan solo los sábados. No se dan de baja:
   su jornada pasa a ser «solo el sábado por la mañana», así que de lunes a
   viernes no salen como disponibles y el sábado sí. El resto de su ficha (como
   «Solo a mano») no se toca.

3. Gonzalo Chicote salía dos veces: «Gonzalo Chicote» (la ficha de cuando era
   invitado, que 0062 pasó a la escuela, sin código de cliente ni días) y
   «Gonzalo Chicote Revert», la que dio de alta administración con su código,
   su responsable y su horario. La primera pasa a inactiva; no se borra (sus
   visitas y pistas de octubre siguen en el historial).

4. Marc Giner, entrenador nuevo: se crea su ficha y su usuario `marc.giner`
   (perfil Entrenador). De momento sin grupo ni jugadores y «Solo a mano» (el
   motor no le pone hasta que se le quite esa marca en Entrenadores). El
   usuario se crea SIN contraseña: se la pone dirección.

Todo se busca por nombre y, si no se encuentra exactamente, esa parte no hace
nada. Lo que cambia y lo que crea queda en el archivo de migraciones: deshacerla
lo deja como estaba."""
import unicodedata

from django.contrib.auth.hashers import make_password
from django.db import migrations

from users import archivo_migraciones as archivo

NOMBRE = "academy.0065_entrenadores_y_gonzalo"

SOLO_SABADOS = ("jorge milla", "salva barcala")
SABADO = 5


def _clave(nombre):
    plano = unicodedata.normalize("NFKD", nombre or "")
    return " ".join("".join(c for c in plano if not unicodedata.combining(c)).lower().split())


def _uno(qs, clave):
    candidatos = [o for o in qs if _clave(o.nombre) == clave]
    return candidatos[0] if len(candidatos) == 1 else None


def aplicar(apps, schema_editor):
    Entrenador = apps.get_model("academy", "Entrenador")
    HorarioEntrenador = apps.get_model("academy", "HorarioEntrenador")
    Jugador = apps.get_model("academy", "Jugador")
    User = apps.get_model("users", "User")

    # 1. Alberto fuera del cuadrante; su usuario no se toca.
    alberto = _uno(Entrenador.objects.filter(activo=True), "alberto sanz")
    if alberto is not None:
        archivo.guardar(apps, NOMBRE, "cambiado", alberto, campos=["activo"])
        Entrenador.objects.filter(pk=alberto.pk).update(activo=False)

    # 2. Jornada de solo sábados (por la mañana: el sábado no hay tarde).
    for clave in SOLO_SABADOS:
        ent = _uno(Entrenador.objects.filter(activo=True), clave)
        if ent is None:
            continue
        for dia in range(6):
            manana = tarde = False
            if dia == SABADO:
                manana = True
            fila = HorarioEntrenador.objects.filter(entrenador=ent, dia=dia).first()
            if fila is None:
                fila = HorarioEntrenador.objects.create(
                    entrenador=ent, dia=dia, manana=manana, tarde=tarde)
                archivo.guardar(apps, NOMBRE, "creado", fila)
            elif (fila.manana, fila.tarde) != (manana, tarde):
                archivo.guardar(apps, NOMBRE, "cambiado", fila, campos=["manana", "tarde"])
                HorarioEntrenador.objects.filter(pk=fila.pk).update(manana=manana, tarde=tarde)

    # 3. El Gonzalo de sobra, solo si está el bueno.
    activos = Jugador.objects.filter(activo=True)
    sobra = _uno(activos, "gonzalo chicote")
    bueno = _uno(activos, "gonzalo chicote revert")
    if sobra is not None and bueno is not None and not sobra.codigo_cliente:
        archivo.guardar(apps, NOMBRE, "cambiado", sobra, campos=["activo"])
        Jugador.objects.filter(pk=sobra.pk).update(activo=False)

    # 4. Marc Giner.
    if User.objects.filter(username="marc.giner").exists():
        return
    if any(_clave(e.nombre) == "marc giner" for e in Entrenador.objects.all()):
        return
    usuario = User.objects.create(
        username="marc.giner", first_name="Marc", last_name="Giner",
        role="ENTRENADOR", is_active=True, password=make_password(None),
    )
    archivo.guardar(apps, NOMBRE, "creado", usuario)
    ent = Entrenador.objects.create(user=usuario, nombre="Marc Giner", solo_manual=True)
    archivo.guardar(apps, NOMBRE, "creado", ent)


def deshacer(apps, schema_editor):
    archivo.deshacer(apps, NOMBRE)


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0064_visita_superficie"),
        ("users", "0007_funciones_preparacion_fisica"),
    ]

    operations = [migrations.RunPython(aplicar, deshacer)]
