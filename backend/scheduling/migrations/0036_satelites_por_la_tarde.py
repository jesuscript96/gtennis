from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scheduling", "0035_satelites_sin_desbordar"),
    ]

    operations = [
        migrations.AlterField(
            model_name="configuracionmotor",
            name="modo_satelites",
            field=models.CharField(
                choices=[
                    ("NUNCA", "Nunca"),
                    ("RESCATE", "Cuando el Resort se llena (solo mañanas)"),
                    ("SIEMPRE", "Cuando el Resort se llena, también por la tarde"),
                ],
                default="RESCATE",
                help_text="Cuándo usa el motor los Satélites.",
                max_length=10,
            ),
        ),
    ]
