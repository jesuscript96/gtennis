"""Alcance de datos por rol (#16).

Reglas:
  * Super Admin (dirección) → ve todo.
  * Coach                   → ve a sus entrenadores y a todos los jugadores de
                              esos entrenadores.
  * Entrenador              → ve solo sus jugadores (`jugadores_permitidos`).
"""
from django.db.models import Q

from .models import Coach, Entrenador, Jugador


def _coach(user):
    coach = getattr(user, "coach", None)
    return coach if (coach is not None and coach.activo) else None


def entrenadores_visibles(user):
    """Queryset de Entrenador que `user` puede ver."""
    qs = Entrenador.objects.all()
    if user.is_superadmin:
        return qs
    coach = _coach(user)
    if coach is not None:
        return coach.entrenadores.all()
    ent = getattr(user, "entrenador", None)
    # Un entrenador ve a los demás (necesario para selects/cuadrante); el filtro
    # fuerte es sobre jugadores, no sobre la lista de entrenadores.
    return qs if ent is not None else qs.none()


def coaches_visibles(user):
    """Queryset de Coach (bloques) que `user` puede ver: dirección los ve
    todos; un coach, el suyo."""
    qs = Coach.objects.filter(activo=True)
    if user.is_superadmin:
        return qs
    coach = _coach(user)
    return qs.filter(pk=coach.pk) if coach else qs.none()


def jugadores_visibles(user, base=None):
    """Queryset de Jugador que `user` puede ver. `base` permite partir de un
    queryset ya filtrado (p. ej. activos)."""
    qs = base if base is not None else Jugador.objects.filter(activo=True)
    if user.is_superadmin:
        return qs
    coach = _coach(user)
    if coach is not None:
        ents = coach.entrenadores.all()
        return qs.filter(
            Q(entrenador_responsable__in=ents)
            | Q(entrenadores_gestores__in=ents)
            | Q(responsables__entrenador__in=ents)
        ).distinct()
    ent = getattr(user, "entrenador", None)
    if ent is not None:
        if ent.gestiona_todos_jugadores:
            return qs
        # Fuente única de la verdad: ResponsableJugador (donde el entrenador
        # figura como responsable, con cualquier prioridad). Se mantiene la
        # unión con `entrenadores_gestores` por compatibilidad (hoy vacío).
        return qs.filter(
            Q(responsables__entrenador=ent) | Q(entrenadores_gestores=ent)
        ).distinct()
    return qs.none()


def puede_ver_jugador(user, jugador):
    """¿`user` tiene a `jugador` dentro de su alcance?"""
    if user.is_superadmin:
        return True
    return jugadores_visibles(user).filter(pk=jugador.pk).exists()


def coaches_del_entrenador(entrenador):
    """Usuarios Coach a los que notificar sobre un entrenador (#5/#4)."""
    if entrenador is None:
        return []
    return [
        c.user
        for c in entrenador.coaches.filter(activo=True)
        if c.user_id is not None
    ]
