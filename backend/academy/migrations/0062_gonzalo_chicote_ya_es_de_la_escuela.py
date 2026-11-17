"""Gonzalo Chicote (de Iván) ya no es invitado: es de la escuela (17/11/2026,
pedido del club).

Era un invitado aprobado con tres visitas sueltas, su ficha se llamaba «Gonzalo
Chicote (invitado)» y estaba de baja desde el último día que vino. Pasa a ser un
alumno como los demás: se le quita «(invitado)» y la nota «Invitado de …», se le
quita la fecha de baja y se borra su registro de invitado con sus visitas (las
tres, ya pasadas), que por eso salía fuera de Jugadores y dentro de Invitados.

Su semana habitual sigue vacía —no viene ningún día—: sus días y turnos los
pone el club en «Horario habitual». Escuela, división, responsable y fecha de
alta no se tocan.

Se busca por nombre; si no hay un invitado con ficha llamado así, no hace nada.
Lo que cambia y lo que borra queda en el archivo de migraciones: deshacerla lo
deja exactamente como estaba."""
import unicodedata

from django.db import migrations

from users import archivo_migraciones as archivo

NOMBRE = "academy.0062_gonzalo_chicote_ya_es_de_la_escuela"


def _clave(nombre):
    plano = unicodedata.normalize("NFKD", nombre or "")
    return " ".join("".join(c for c in plano if not unicodedata.combining(c)).lower().split())


def pasar_a_la_escuela(apps, schema_editor):
    Invitado = apps.get_model("academy", "Invitado")
    Jugador = apps.get_model("academy", "Jugador")
    candidatos = [i for i in Invitado.objects.filter(jugador_creado__isnull=False)
                  if _clave(i.nombre) == "gonzalo chicote"]
    if len(candidatos) != 1:
        return
    inv = candidatos[0]
    jugador = Jugador.objects.get(pk=inv.jugador_creado_id)
    campos = ["nombre", "notas", "fecha_baja"]
    archivo.guardar(apps, NOMBRE, "cambiado", jugador, campos=campos)
    nombre = jugador.nombre
    if nombre.lower().endswith("(invitado)"):
        nombre = nombre[: -len("(invitado)")].rstrip()
    notas = "" if (jugador.notas or "").startswith("Invitado de") else jugador.notas
    Jugador.objects.filter(pk=jugador.pk).update(nombre=nombre, notas=notas, fecha_baja=None)
    # Primero sus visitas y luego el invitado: al deshacer se vuelven a poner en
    # orden inverso, el invitado antes que sus visitas.
    for visita in inv.visitas.all():
        archivo.guardar(apps, NOMBRE, "borrado", visita)
    archivo.guardar(apps, NOMBRE, "borrado", inv)
    inv.delete()


def deshacer(apps, schema_editor):
    archivo.deshacer(apps, NOMBRE)


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0061_mario_y_jorge_una_columna"),
        ("users", "0006_funciones_iniciales"),
    ]

    operations = [migrations.RunPython(pasar_a_la_escuela, deshacer)]
