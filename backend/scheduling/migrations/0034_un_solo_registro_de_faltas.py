"""Un solo registro de faltas y un solo calendario del entrenador
(orden de la aplicación, 10/11/2026, tanda 3). La conversión está en
`scheduling/unificacion.py`, que explica qué pasa a dónde.

Todo lo que borra o cambia queda en el archivo de migraciones (11/11/2026):
deshacerla deja el parte semanal, «Disp. entrenadores» y el interruptor
exactamente como estaban, y quita solo las filas que puso ella.
"""
from django.db import migrations

from scheduling.unificacion import unificar
from users import archivo_migraciones as archivo

NOMBRE = "scheduling.0034_un_solo_registro_de_faltas"


def aplicar(apps, schema_editor):
    unificar(apps, NOMBRE)


def deshacer(apps, schema_editor):
    archivo.deshacer(apps, NOMBRE)


class Migration(migrations.Migration):

    dependencies = [
        ("scheduling", "0033_autor_de_la_falta"),
        ("academy", "0059_calendario_entrenador"),
        ("users", "0005_archivo_migraciones"),
    ]

    operations = [migrations.RunPython(aplicar, deshacer)]
