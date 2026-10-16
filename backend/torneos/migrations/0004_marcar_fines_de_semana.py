"""Los torneos que en su nombre dicen «fin de semana», «fines de semana» o
«finde» se marcan como de solo fines de semana (17 en el Excel de 2026)."""
import re

from django.db import migrations

PATRON = re.compile(r"fin(es)? de semana|\bfinde\b", re.I)


def marcar(apps, schema_editor):
    Torneo = apps.get_model("torneos", "Torneo")
    ids = [t.id for t in Torneo.objects.only("id", "nombre") if PATRON.search(t.nombre)]
    Torneo.objects.filter(id__in=ids).update(solo_fines_semana=True)


class Migration(migrations.Migration):
    dependencies = [("torneos", "0003_previa_y_fines_de_semana")]
    operations = [migrations.RunPython(marcar, migrations.RunPython.noop)]
