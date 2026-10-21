from django.db import migrations, models


def de_interruptor_a_modo(apps, schema_editor):
    # Lo que estaba encendido sigue desbordando; lo apagado (el verano) pasa al
    # modo nuevo: satélites solo para que nadie se quede en el banquillo.
    Cfg = apps.get_model("scheduling", "ConfiguracionMotor")
    for c in Cfg.objects.all():
        c.modo_satelites = "DESBORDAR" if c.usar_satelites else "RESCATE"
        c.save(update_fields=["modo_satelites"])


def de_modo_a_interruptor(apps, schema_editor):
    Cfg = apps.get_model("scheduling", "ConfiguracionMotor")
    for c in Cfg.objects.all():
        c.usar_satelites = c.modo_satelites == "DESBORDAR"
        c.save(update_fields=["usar_satelites"])


class Migration(migrations.Migration):

    dependencies = [
        ("scheduling", "0030_asignacion_forzada"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracionmotor",
            name="modo_satelites",
            field=models.CharField(
                choices=[
                    ("NUNCA", "Nunca"),
                    ("RESCATE", "Solo para no dejar a nadie en el banquillo"),
                    ("DESBORDAR", "Desbordar cuando el Resort se llena"),
                ],
                default="RESCATE",
                help_text="Cuándo usa el motor los clubs satélite (Sta. Bárbara, Bétera, Mas Camarena). Por la tarde nunca.",
                max_length=10,
            ),
        ),
        migrations.RunPython(de_interruptor_a_modo, de_modo_a_interruptor),
        migrations.RemoveField(model_name="configuracionmotor", name="usar_satelites"),
    ]
