"""El archivo donde las migraciones de datos del orden de la aplicación
guardan lo que cambian o borran (11/11/2026). Va antes que todas ellas."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("users", "0004_perfiles_y_funciones")]

    operations = [
        migrations.CreateModel(
            name="ArchivoMigracion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("migracion", models.CharField(db_index=True, max_length=80)),
                ("modelo", models.CharField(max_length=80)),
                ("pk_original", models.CharField(blank=True, max_length=40)),
                ("accion", models.CharField(max_length=10)),
                ("datos", models.JSONField(blank=True, default=dict)),
                ("creado", models.DateTimeField(auto_now_add=True)),
            ],
            options={"verbose_name": "archivo de migración", "verbose_name_plural": "archivo de migraciones",
                     "ordering": ["id"]},
        ),
    ]
