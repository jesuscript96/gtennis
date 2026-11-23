"""Solo Resort y Satélites (23/11/2026, pedido del club).

Ya no se distingue entre Sta. Bárbara, Poli Bétera y Mas Camarena: lo que no
cabe en el Resort va a «Satélites», donde se montan las pistas que hagan falta,
de tierra o de resina. Sta. Bárbara pasa a llamarse «Satélites» (así lo que ya
está puesto esta semana sigue en su sitio) y se queda con cuatro de tierra y
dos de resina para empezar; el motor añade más si hacen falta. Poli Bétera y
Mas Camarena se apagan sin borrarlas (tienen historial).

Lo que cambia queda en el archivo de migraciones: deshacerla lo deja
exactamente como estaba.
"""
from django.db import migrations, transaction
from django.db.models import ProtectedError

from users import archivo_migraciones as archivo

NOMBRE = "academy.0066_resort_y_satelites"
SATELITES = "Satélites"
ANTIGUA = "Sta. Bárbara"
APAGAR = ("Poli Bétera", "Mas Camarena")
# Las pistas de partida: el motor crea más cuando no le llegan.
PISTAS = [(1, "TIERRA"), (2, "TIERRA"), (3, "TIERRA"), (4, "TIERRA"),
          (5, "RESINA"), (6, "RESINA")]


def a_satelites(apps, schema_editor):
    Sede = apps.get_model("academy", "Sede")
    Pista = apps.get_model("academy", "Pista")
    campos_sede = ["nombre", "es_satelite", "activa", "orden_desbordamiento",
                   "densidad_default", "densidad_max"]
    sede = (Sede.objects.filter(nombre=SATELITES).first()
            or Sede.objects.filter(nombre=ANTIGUA).first())
    if sede is None:
        sede = Sede.objects.create(
            nombre=SATELITES, es_satelite=True, activa=True, orden_desbordamiento=1,
            densidad_default=2, densidad_max=4)
        archivo.guardar(apps, NOMBRE, "creado", sede)
    else:
        archivo.guardar(apps, NOMBRE, "cambiado", sede, campos=campos_sede)
        Sede.objects.filter(pk=sede.pk).update(
            nombre=SATELITES, es_satelite=True, activa=True, orden_desbordamiento=1,
            densidad_default=2, densidad_max=4)
    for numero, superficie in PISTAS:
        pista = Pista.objects.filter(sede=sede, numero=numero).first()
        if pista is None:
            pista = Pista.objects.create(sede=sede, numero=numero, superficie=superficie,
                                         activa=True)
            archivo.guardar(apps, NOMBRE, "creado", pista)
        elif pista.superficie != superficie or not pista.activa:
            archivo.guardar(apps, NOMBRE, "cambiado", pista, campos=["superficie", "activa"])
            Pista.objects.filter(pk=pista.pk).update(superficie=superficie, activa=True)
    for otra in Sede.objects.filter(nombre__in=APAGAR, activa=True):
        archivo.guardar(apps, NOMBRE, "cambiado", otra, campos=["activa"])
        Sede.objects.filter(pk=otra.pk).update(activa=False)


def deshacer(apps, schema_editor):
    # Una pista (o la sede) creada aquí que ya tiene entrenamientos no se puede
    # borrar: se apaga y el resto se deshace como siempre.
    for e in archivo.entradas(apps, NOMBRE, "creado"):
        Modelo = apps.get_model(*e.modelo.split("."))
        try:
            with transaction.atomic():
                Modelo.objects.filter(pk=e.pk_original).delete()
        except ProtectedError:
            Modelo.objects.filter(pk=e.pk_original).update(activa=False)
        e.delete()
    archivo.deshacer(apps, NOMBRE)


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0065_entrenadores_y_gonzalo"),
        ("users", "0007_funciones_preparacion_fisica"),
    ]

    operations = [migrations.RunPython(a_satelites, deshacer)]
