"""Empezar de cero a evaluar (19/11/2026, lo pide el club).

Borra todas las evaluaciones de tenis, todas las físicas y todos los informes
(también los validados) y manda a la papelera de Drive el PDF de cada informe
(y su copia en español). No toca las fotos, el reparto de entrenadores y
preparadores, los datos de las familias ni los recordatorios ya dados, ni los
ficheros antiguos de la unidad «Informes de jugadores» de cada evaluación.

Todo lo borrado queda entero en el archivo de migraciones: deshacerla
(`migrate evaluaciones 0014`) lo vuelve a poner con sus mismas claves y saca
los PDF de la papelera de Drive (allí duran 30 días).
"""
from django.db import migrations

from users import archivo_migraciones as archivo

NOMBRE = "evaluaciones.0015_empezar_de_cero"


def aplicar(apps, schema_editor):
    from evaluaciones import drive

    Informe = apps.get_model("evaluaciones", "Informe")
    Evaluacion = apps.get_model("evaluaciones", "Evaluacion")
    EvaluacionFisica = apps.get_model("evaluaciones", "EvaluacionFisica")
    informes = list(Informe.objects.order_by("id"))
    # Primero los informes: al deshacer (en orden inverso) vuelven después de
    # las evaluaciones a las que apuntan.
    for inf in informes:
        archivo.guardar(apps, NOMBRE, "borrado", inf)
    for Modelo in (Evaluacion, EvaluacionFisica):
        for ev in Modelo.objects.order_by("id"):
            archivo.guardar(apps, NOMBRE, "borrado", ev)
    pdfs = [f for inf in informes for f in (inf.drive_file_id, inf.drive_file_id_es) if f]
    Informe.objects.all().delete()
    Evaluacion.objects.all().delete()
    EvaluacionFisica.objects.all().delete()
    for f in pdfs:
        drive.a_la_papelera(f)


def deshacer(apps, schema_editor):
    from evaluaciones import drive

    pdfs = []
    for e in archivo.entradas(apps, NOMBRE, "borrado"):
        if e.modelo == "evaluaciones.informe":
            pdfs += [e.datos.get("drive_file_id"), e.datos.get("drive_file_id_es")]
    archivo.deshacer(apps, NOMBRE)
    for f in filter(None, pdfs):
        drive.sacar_de_papelera(f)


class Migration(migrations.Migration):

    dependencies = [
        ("evaluaciones", "0014_envio_programado"),
        ("users", "0006_funciones_iniciales"),
    ]

    operations = [migrations.RunPython(aplicar, deshacer)]
