"""Sésame HR integration (PRD §06): pull coach clock-ins and vacation/leave so
coach availability isn't double-managed.

This is the contract/skeleton. The real HTTP calls go in `fetch_*` once the
client's Sésame plan + API token are confirmed (the biggest external unknown
flagged in discovery). Until then, the manual fallback (Entrenador.
disponible_semana, set from the coach UI) is the source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


@dataclass
class CoachAvailability:
    external_id: str
    available_week: bool
    note: str = ""


def is_configured() -> bool:
    return bool(settings.SESAME_API_BASE and settings.SESAME_API_TOKEN)


def fetch_coach_availability() -> list[CoachAvailability]:
    """Return availability for all coaches for the current week.

    Raises if not configured so callers fall back to the manual flag.
    """
    if not is_configured():
        raise RuntimeError("Sésame no configurado — usar fallback manual.")
    # TODO: GET {SESAME_API_BASE}/employees + /worked-hours + /holidays with the
    # bearer token, map external ids to Entrenador, derive available_week.
    raise NotImplementedError("Conectar API Sésame en su fase.")


def sync_to_db() -> dict:
    """Best-effort sync; on any failure leaves the manual flags untouched."""
    try:
        rows = fetch_coach_availability()
    except (RuntimeError, NotImplementedError) as exc:
        return {"synced": False, "reason": str(exc)}
    # TODO: update Entrenador.disponible_semana from `rows`.
    return {"synced": True, "count": len(rows)}
