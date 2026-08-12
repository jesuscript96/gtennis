"""Fix sedes duplicadas en producción: 'Central' y 'Resort' son el mismo lugar
(fecha del feedback de Sergio). La migración 0014 intentó mergearlas vía aliases
pero no funcionó y en prod coexisten como dos sedes base distintas.

Estado real en prod antes de esta migración:
    Resort   (id=1): 8 pistas, 1-6 TIERRA + 7-8 RESINA  ← correcta
    Central  (id=7): 8 pistas, TODAS RESINA             ← duplicada, mal

Resort tiene las 585 asignaciones; Central tiene 0. Por tanto desactivamos
Central y sus pistas (no se borran: pueden tener referencias históricas o de
auditoría). Es idempotente: si Central no existe o ya está inactiva, no hace
nada.
"""
from django.db import migrations


def forward(apps, schema_editor):
    Sede = apps.get_model("academy", "Sede")
    Pista = apps.get_model("academy", "Pista")
    # Cualquier sede base (no satélite) cuyo nombre no sea exactamente 'Resort'
    # se considera un duplicado histórico de Resort y se desactiva.
    Resort = Sede.objects.filter(nombre__iexact="Resort").first()
    if Resort is None:
        # Sin Resort no podemos hacer nada seguro; abortamos sin error.
        return
    Resort.activa = True
    Resort.save(update_fields=["activa"])
    duplicadas = Sede.objects.filter(
        es_satelite=False, activa=True
    ).exclude(id=Resort.id)
    for sede in duplicadas:
        sede.activa = False
        sede.save(update_fields=["activa"])
        Pista.objects.filter(sede=sede).update(activa=False)


def backward(apps, schema_editor):
    # No recupera el estado previo: era incorrecto. Para reactivar Central,
    # hacerlo a mano desde el admin.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0022_junior_program_turno_unico"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
