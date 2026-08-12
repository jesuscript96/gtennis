"""Reasigna los responsables por BLOQUE de color (#2/#12), corrigiendo el
import antiguo (que usaba divisiones vecinas y cruzaba colores).

Modelo correcto:
  * Principal(es) (prioridad 1) = entrenadores de la sub-columna del jugador
    (su división).
  * Secundarios (prioridad 2)  = entrenadores de las OTRAS sub-columnas del
    mismo bloque de color.

Bloques de color (divisiones que van juntas):
    [1, 2, 3]  ·  [4, 5]  ·  [6, 7]  ·  [8]

La sub-columna de cada división se reconstruye desde los responsables prioridad 1
actuales (ese dato es fiable; lo que estaba mal eran los secundarios).
Idempotente.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from academy.models import Jugador, ResponsableJugador

BLOQUES = [[1, 2, 3], [4, 5], [6, 7], [8]]


class Command(BaseCommand):
    help = "Reasigna responsables por bloque de color (principal sub-columna + secundarios del bloque)."

    @transaction.atomic
    def handle(self, *args, **opts):
        # Sub-columna por división = entrenadores hoy prioridad 1 en esa división.
        coaches_div = defaultdict(set)
        for rj in ResponsableJugador.objects.filter(prioridad=1).select_related(
            "jugador__division"
        ):
            div = rj.jugador.division.nivel if rj.jugador.division_id else None
            if div is not None:
                coaches_div[div].add(rj.entrenador_id)

        bloque_de = {d: b for b in BLOQUES for d in b}

        n = 0
        for j in Jugador.objects.filter(
            activo=True, division__isnull=False
        ).select_related("division"):
            div = j.division.nivel
            bloque = bloque_de.get(div)
            if bloque is None:
                continue
            principales = set(coaches_div.get(div, set()))
            if not principales:
                continue
            secundarios = set()
            for d2 in bloque:
                if d2 != div:
                    secundarios |= coaches_div.get(d2, set())
            secundarios -= principales

            j.responsables.all().delete()
            for eid in principales:
                ResponsableJugador.objects.create(jugador=j, entrenador_id=eid, prioridad=1)
            for eid in secundarios:
                ResponsableJugador.objects.create(jugador=j, entrenador_id=eid, prioridad=2)
            j.repartir_porcentajes()
            n += 1

        self.stdout.write(self.style.SUCCESS(
            f"Reasignados responsables de {n} jugadores por bloque de color."
        ))
