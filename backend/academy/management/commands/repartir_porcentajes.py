"""Reparte los % objetivo de los responsables de cada jugador (#12): 70/15/15
según el nº de responsables. Idempotente."""
from django.core.management.base import BaseCommand

from academy.models import Jugador


class Command(BaseCommand):
    help = "Reparte los % objetivo de responsables (70/15/15) en todos los jugadores."

    def handle(self, *args, **opts):
        n = 0
        for j in Jugador.objects.filter(responsables__isnull=False).distinct():
            j.repartir_porcentajes()
            n += 1
        self.stdout.write(self.style.SUCCESS(f"Repartidos % en {n} jugadores."))
