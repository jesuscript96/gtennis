from django.db import migrations


def seed_escuelas(apps, schema_editor):
    Escuela = apps.get_model("academy", "Escuela")
    Jugador = apps.get_model("academy", "Jugador")
    ar, _ = Escuela.objects.get_or_create(
        nombre="Alto Rendimiento", defaults={"orden": 0}
    )
    Escuela.objects.get_or_create(nombre="Junior Program", defaults={"orden": 1})
    # Los alumnos actuales pertenecen a Alto Rendimiento.
    Jugador.objects.filter(escuela__isnull=True).update(escuela=ar)


def revertir(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0011_escuela_aviso_jugador_escuela_invitado"),
    ]

    operations = [
        migrations.RunPython(seed_escuelas, revertir),
    ]
