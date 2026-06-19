"""The weekly operational flow — "The 5 PM Rule" (PRD §07)."""
from datetime import date, timedelta

from celery import shared_task


def _next_monday(today=None):
    today = today or date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


@shared_task
def alert_empty_availability():
    """Fri ~16:30: ping coaches whose players still have empty fields before the
    17:00 technical close. (Email/push wiring is a later phase.)"""
    # TODO: detect coaches with missing Disponibilidad for next week and notify.
    return "alerts-checked"


@shared_task
def generate_next_week_draft():
    """Sun: run the engine and produce next week's draft for Iván to review."""
    from .models import Semana
    from engine.service import generate

    semana, _ = Semana.objects.get_or_create(fecha_inicio=_next_monday())
    return generate(semana)


@shared_task
def sync_sesame():
    """Daily: pull coach availability from Sésame (no-op until configured)."""
    from integrations.sesame import sync_to_db

    return sync_to_db()
