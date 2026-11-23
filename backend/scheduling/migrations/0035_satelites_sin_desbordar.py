from django.db import migrations, models


def desbordar_a_rescate(apps, schema_editor):
    # El modo «desbordar» ya no existe (23/11/2026): quien lo tuviera pasa a
    # abrir Satélites cuando el Resort se llena.
    Cfg = apps.get_model("scheduling", "ConfiguracionMotor")
    Cfg.objects.filter(modo_satelites="DESBORDAR").update(modo_satelites="RESCATE")


class Migration(migrations.Migration):

    dependencies = [
        ("scheduling", "0034_un_solo_registro_de_faltas"),
    ]

    operations = [
        migrations.RunPython(desbordar_a_rescate, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="configuracionmotor",
            name="modo_satelites",
            field=models.CharField(
                choices=[("NUNCA", "Nunca"), ("RESCATE", "Cuando el Resort se llena")],
                default="RESCATE",
                help_text="Cuándo usa el motor los Satélites. Por la tarde nunca.",
                max_length=10,
            ),
        ),
    ]
