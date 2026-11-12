"""Qué guardó cada migración de datos en el archivo (11/11/2026), y deshacer un
repaso de `unificar_faltas`. Las migraciones se deshacen con `migrate` (su
vuelta atrás usa este mismo archivo), no desde aquí.

    python manage.py archivo_migraciones
    python manage.py archivo_migraciones --deshacer scheduling.unificar_faltas.20261112-201500
"""
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from users import archivo_migraciones as archivo
from users.models import ArchivoMigracion


class Command(BaseCommand):
    help = "Lo archivado por las migraciones de datos; --deshacer un repaso de unificar_faltas."

    def add_arguments(self, parser):
        parser.add_argument("--deshacer", help="Nombre de un repaso de unificar_faltas.")

    def handle(self, *args, **o):
        if o["deshacer"]:
            if not o["deshacer"].startswith("scheduling.unificar_faltas."):
                raise CommandError("Las migraciones se deshacen con migrate; aquí solo los repasos.")
            if not ArchivoMigracion.objects.filter(migracion=o["deshacer"]).exists():
                raise CommandError("No hay nada archivado con ese nombre.")
            with transaction.atomic():
                archivo.deshacer(apps, o["deshacer"])
            self.stdout.write(f"Deshecho «{o['deshacer']}».")
            return
        filas = (ArchivoMigracion.objects.values("migracion", "modelo", "accion")
                 .annotate(n=Count("id")).order_by("migracion", "modelo", "accion"))
        for f in filas:
            self.stdout.write(f"{f['migracion']} · {f['accion']} {f['modelo']}: {f['n']}")
        if not filas:
            self.stdout.write("El archivo está vacío.")
