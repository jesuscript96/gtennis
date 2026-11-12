"""Cuántas filas tiene cada tabla de la aplicación (11/11/2026). Solo lee.

Sirve para comprobar una copia de seguridad (el recuento de producción tiene
que coincidir con el de la copia restaurada) y para comparar antes y después
de desplegar:

    python manage.py recuento > antes.json
    python manage.py recuento --comparar antes.json
"""
import json

from django.apps import apps
from django.core.management.base import BaseCommand

# Lo que Django rehace solo o no es del club.
FUERA = {"contenttypes", "auth.permission", "sessions", "admin"}


def recuento():
    out = {}
    for m in apps.get_models():
        clave = f"{m._meta.app_label}.{m._meta.model_name}"
        if m._meta.app_label in FUERA or clave in FUERA or not m._meta.managed:
            continue
        out[clave] = m._default_manager.count()
    return dict(sorted(out.items()))


class Command(BaseCommand):
    help = "Filas por tabla (JSON). Con --comparar, las diferencias con un recuento anterior."

    def add_arguments(self, parser):
        parser.add_argument("--comparar", help="Fichero JSON de un recuento anterior.")

    def handle(self, *args, **o):
        ahora = recuento()
        if not o["comparar"]:
            self.stdout.write(json.dumps(ahora, indent=1))
            return
        with open(o["comparar"]) as f:
            antes = json.load(f)
        cambios = 0
        for clave in sorted(set(antes) | set(ahora)):
            a, b = antes.get(clave), ahora.get(clave)
            if a != b:
                cambios += 1
                self.stdout.write(f"{clave}: {a} → {b}")
        self.stdout.write(f"{cambios} tablas distintas de {len(ahora)}.")
