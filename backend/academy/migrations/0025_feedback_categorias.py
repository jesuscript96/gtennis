"""Reorganiza el feedback existente en los 3 estados definitivos
(segunPedro Sergio, 12 ago 2026):

  NUEVO     - pendiente de implementar (#4, #15, #16, #18)
  HECHO     - implementado, pendiente de testear en prod (los demas)
  AJENO     - temas fuera de esta plataforma (#14 precios pagina web)

Idempotente: usa ids concretos y solo actualiza si el estado actual difiere.
"""
from django.db import migrations


# Mapeo id -> estado destino.
NUEVO_IDS = [4, 15, 16, 18]     # Movimientos escuelas, Edad, Coaches, Notificacion Baja
AJENO_IDS = [14]                # Precios pagina web
# Los demas (1,2,3,5,6,7,8,9,10,11,12,13,17,19,20) quedan en HECHO.


def forward(apps, schema_editor):
    Feedback = apps.get_model("academy", "Feedback")
    Feedback.objects.filter(id__in=NUEVO_IDS).update(estado="NUEVO")
    Feedback.objects.filter(id__in=AJENO_IDS).update(estado="AJENO")
    # El resto a HECHO (por si alguno estaba en NUEVO/EN_PROGRESO).
    Feedback.objects.exclude(id__in=NUEVO_IDS + AJENO_IDS).update(estado="HECHO")


def backward(apps, schema_editor):
    # Sin backward significativo: los estados son categorizacion, no historia.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0024_junior_program_turno_propio"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
