"""Dos alumnos no entrenan juntos más de 2 días a la semana (26/11/2026, antes
3). Solo se cambia si seguía en 3: si alguien lo había puesto a otro valor en
Criterios del motor, se respeta. Lo cambiado queda en el archivo de
migraciones: deshacerla lo deja como estaba."""
from django.db import migrations, models

from users import archivo_migraciones as archivo

NOMBRE = "scheduling.0038_tope_dos_dias_juntos"


def a_dos(apps, schema_editor):
    Cfg = apps.get_model("scheduling", "ConfiguracionMotor")
    for c in Cfg.objects.filter(max_dias_misma_pista=3):
        archivo.guardar(apps, NOMBRE, "cambiado", c, campos=["max_dias_misma_pista"])
        Cfg.objects.filter(pk=c.pk).update(max_dias_misma_pista=2)


def deshacer(apps, schema_editor):
    archivo.deshacer(apps, NOMBRE)


class Migration(migrations.Migration):

    dependencies = [
        ("scheduling", "0037_falta_descanso"),
        ("users", "0007_funciones_preparacion_fisica"),
    ]

    operations = [
        migrations.AlterField(
            model_name="configuracionmotor",
            name="max_dias_misma_pista",
            field=models.PositiveSmallIntegerField(
                default=2,
                help_text="Regla dura: dos alumnos no comparten pista más de estos días en la semana, aunque tengan la pareja declarada (salvo las parejas que «pueden repetir más días»). Mañana y tarde del mismo día cuentan como uno. 0 = sin tope.",
                verbose_name="Máx. días juntos a la semana",
            ),
        ),
        migrations.RunPython(a_dos, deshacer),
    ]
