"""Arregla el reparto de % de los responsables ya cargados (#12). En prod los
52 ResponsableJugador estaban a porcentaje_objetivo=0; los reparte 70/15/15
según el nº de responsables por jugador. Corre una vez.
"""
from collections import defaultdict

from django.db import migrations


def forward(apps, schema_editor):
    ResponsableJugador = apps.get_model("academy", "ResponsableJugador")
    by_jug = defaultdict(list)
    for rj in ResponsableJugador.objects.filter(activo=True).order_by(
        "jugador_id", "prioridad", "id"
    ):
        by_jug[rj.jugador_id].append(rj)
    for resp in by_jug.values():
        n = len(resp)
        if n == 1:
            pesos = [100]
        elif n == 2:
            pesos = [70, 30]
        elif n == 3:
            pesos = [70, 15, 15]
        else:
            base = 100 // n
            pesos = [base] * n
            pesos[0] += 100 - base * n
        for r, p in zip(resp, pesos):
            if r.porcentaje_objetivo != p:
                r.porcentaje_objetivo = p
                r.save(update_fields=["porcentaje_objetivo"])


def backward(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0019_invitado_division_invitado_edad_invitado_jugar_con_and_more"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
