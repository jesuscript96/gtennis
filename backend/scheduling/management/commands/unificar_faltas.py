"""Repaso tras desplegar el orden de la aplicación (11/11/2026). Si en el rato
del despliegue alguien apuntó una falta por el parte semanal o por «Disp.
entrenadores» desde la versión vieja, o un comando apagó el interruptor
«Disponible esta semana», aquí se pasan al registro único igual que hizo la
migración `scheduling.0034`, y todo queda en el archivo de migraciones.

    python manage.py unificar_faltas            # solo dice qué hay
    python manage.py unificar_faltas --aplicar  # lo pasa; se deshace con
                                                # archivo_migraciones --deshacer NOMBRE
"""
from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from academy.models import Entrenador
from scheduling.models import Disponibilidad, DisponibilidadEntrenador
from scheduling.unificacion import EXTRA, unificar


class Command(BaseCommand):
    help = "Pasa al registro único las faltas que queden en el parte semanal o en Disp. entrenadores."

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true")

    def handle(self, *args, **o):
        pendiente = {
            "faltas en el parte semanal": Disponibilidad.objects.exclude(estado=EXTRA).count(),
            "filas de Disp. entrenadores": DisponibilidadEntrenador.objects.count(),
            "interruptores apagados": Entrenador.objects.filter(disponible_semana=False).count(),
        }
        for k, v in pendiente.items():
            self.stdout.write(f"{k}: {v}")
        if not any(pendiente.values()):
            self.stdout.write("Nada que pasar.")
            return
        if not o["aplicar"]:
            self.stdout.write("Sin --aplicar no se cambia nada.")
            return
        nombre = f"scheduling.unificar_faltas.{timezone.now():%Y%m%d-%H%M%S}"
        with transaction.atomic():
            resumen = unificar(apps, nombre)
        self.stdout.write(f"Hecho y archivado como «{nombre}»: {resumen}")
