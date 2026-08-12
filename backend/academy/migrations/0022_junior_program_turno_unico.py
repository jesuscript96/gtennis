"""Reinterpreta Junior Program (#6): NO es un turno/columna aparte, sino una
escuela cuyos jugadores solo entrenan en M2 y solo en el Resort. Retira el
turno "JP" creado antes, restaura el orden de tarde y configura la escuela.
"""
from django.db import migrations


def forward(apps, schema_editor):
    Turno = apps.get_model("academy", "Turno")
    Escuela = apps.get_model("academy", "Escuela")
    Asignacion = apps.get_model("scheduling", "Asignacion")

    # Quitar el turno JP (interpretación antigua) y restaurar M1·M2·T1·T2.
    jp_turno = Turno.objects.filter(codigo="JP").first()
    if jp_turno is not None:
        # Sus asignaciones lo protegen (FK PROTECT): se borran antes.
        Asignacion.objects.filter(turno=jp_turno).delete()
        jp_turno.delete()
    Turno.objects.filter(codigo="T1").update(orden=3)
    Turno.objects.filter(codigo="T2").update(orden=4)

    # Junior Program → solo M2, solo Resort.
    m2 = Turno.objects.filter(codigo="M2").first()
    jp = Escuela.objects.filter(nombre__icontains="junior").first()
    if jp is not None and m2 is not None:
        jp.turno_unico = m2
        jp.solo_central = True
        jp.save(update_fields=["turno_unico", "solo_central"])


def backward(apps, schema_editor):
    Escuela = apps.get_model("academy", "Escuela")
    Escuela.objects.filter(nombre__icontains="junior").update(
        turno_unico=None, solo_central=False
    )


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0021_remove_turno_solo_escuela_escuela_solo_central_and_more"),
        ("scheduling", "0005_disponibilidadentrenador"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
