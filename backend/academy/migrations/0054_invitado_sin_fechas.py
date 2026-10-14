from django.db import migrations


class Migration(migrations.Migration):
    """Aparte de la 0053: Postgres no deja quitar columnas en la misma
    transacción en la que se han movido sus datos."""

    dependencies = [
        ('academy', '0053_visitas_de_invitado'),
    ]

    operations = [
        migrations.RemoveField(model_name='invitado', name='fechas'),
        migrations.RemoveField(model_name='invitado', name='fecha_desde'),
        migrations.RemoveField(model_name='invitado', name='fecha_hasta'),
        migrations.RemoveField(model_name='invitado', name='repite_de'),
    ]
