"""Marca como HECHO en el backlog de feedback (#A4) los items ya implementados.
Deja intactos los que quedan FUERA de la app (web/precios/inglés, #14).

Correr en PRODUCCIÓN **después** de desplegar (para que las migraciones de
datos #7/#8/#12 ya estén aplicadas):
    fly ssh console -a gtennis-api-jesus --command \
        "python manage.py sync_feedback_estados"
Idempotente.
"""
from django.core.management.base import BaseCommand

from academy.models import Feedback

# Palabras clave de los items que NO son de la app (quedan sin marcar).
FUERA_APP = ["precios", "pagina web", "página web", "ingl"]


class Command(BaseCommand):
    help = "Marca como HECHO el feedback ya implementado (todo menos la web/inglés)."

    def handle(self, *args, **opts):
        hechos, fuera = 0, 0
        for fb in Feedback.objects.all():
            texto = f"{fb.titulo or ''} {fb.descripcion or ''}".lower()
            if any(k in texto for k in FUERA_APP):
                fuera += 1
                continue
            if fb.estado != Feedback.EstadoFeedback.HECHO:
                fb.estado = Feedback.EstadoFeedback.HECHO
                fb.save(update_fields=["estado"])
            hechos += 1
        self.stdout.write(self.style.SUCCESS(
            f"HECHO: {hechos} | fuera de la app (sin tocar): {fuera}"
        ))
