"""Celery app for the scheduled weekly flow ("The 5 PM Rule").

Beat schedule (configured on Render):
- Fri 16:30 -> alert coaches with empty availability fields before the 17:00 close.
- Sun 09:00 -> run the pairing engine and produce next week's draft cuadrante.
- Daily -> pull coach availability from Sésame.
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("gtenis")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
