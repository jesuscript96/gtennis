from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("torneos", "0009_sin_propuesto")]

    operations = [
        migrations.AlterField(
            model_name="torneo", name="estado",
            field=models.CharField(choices=[("VALIDADO", "Validado"), ("CANCELADO", "Cancelado")],
                                   default="VALIDADO", max_length=10),
        ),
    ]
