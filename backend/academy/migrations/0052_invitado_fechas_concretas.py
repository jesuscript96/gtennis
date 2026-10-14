from datetime import timedelta

from django.db import migrations, models


def dias_a_fechas(apps, schema_editor):
    """El patrón semanal entre dos fechas pasa a ser la lista de días."""
    Invitado = apps.get_model("academy", "Invitado")
    for inv in Invitado.objects.all():
        if not (inv.fecha_desde and inv.fecha_hasta and inv.dias):
            continue
        fechas, dia = {}, inv.fecha_desde
        while dia <= inv.fecha_hasta:
            fila = inv.dias.get(str(dia.weekday()))
            if fila:
                fechas[dia.isoformat()] = fila
            dia += timedelta(days=1)
        inv.fechas = fechas
        inv.save(update_fields=["fechas"])


class Migration(migrations.Migration):

    dependencies = [
        ('academy', '0051_invitado_como_jugador'),
    ]

    operations = [
        migrations.AddField(
            model_name='invitado',
            name='fechas',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(dias_a_fechas, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='invitado',
            name='dias',
        ),
    ]
