from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scheduling", "0003_alter_disponibilidad_unique_together_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracionmotor",
            name="peso_central",
            field=models.PositiveIntegerField(
                default=100,
                help_text="Bonus por jugador asignado a pista no satélite (rellenar GTennis primero).",
            ),
        ),
    ]
