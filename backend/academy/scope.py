"""Alcance de datos por rol (#16).

Reglas:
  * Super Admin (dirección) → ve todo.
  * Coach                   → ve a sus entrenadores y a todos los jugadores de
                              esos entrenadores.
  * Entrenador              → ve sus jugadores y los que gestionan los demás
                              de su grupo de gestión (`Entrenador.q_jugadores`).
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
    # Dirección y Administración (altas y datos de jugadores) ven a todos.
    if user.is_superadmin or getattr(user, "is_administracion", False):
        return qs
    coach = _coach(user)
    if coach is not None:
        ents = coach.entrenadores.all()
        # Las altas nuevas llegan sin entrenador de gestión y es el head coach
        # quien se lo pone (06/10/2026): hasta entonces las ven todos.
        return qs.filter(
            Q(entrenador_responsable__isnull=True)
            | Q(entrenador_responsable__in=ents)
            | Q(cogestores__in=ents)
            | Q(responsables__entrenador__in=ents)
        ).distinct()
    ent = getattr(user, "entrenador", None)
    if ent is not None:
        if ent.gestiona_todos_jugadores:
            return qs
        # Los que gestiona, los que entrena (tiene porcentaje con ellos) y los
        # que gestionan los demás de su grupo de gestión (su color).
        return qs.filter(ent.q_jugadores()).distinct()
    return qs.none()


def puede_ver_jugador(user, jugador):
    """¿`user` tiene a `jugador` dentro de su alcance?"""
    if user.is_superadmin or getattr(user, "is_administracion", False):
        return True
    return jugadores_visibles(user).filter(pk=jugador.pk).exists()


def jugadores_que_evalua(user, base=None):
    """Los jugadores de Alto rendimiento a los que `user` hace el informe de
    tenis (12/11/2026), sin reparto de nadie:

      * Dirección → todos.
      * Head coach → los de su color: los que gestionan los entrenadores de su
        bloque.
      * Entrenador → su grupo: su columna de Grupos (los que gestiona o cuya
        gestión comparte). Ni los demás de su color ni los que solo entrena.

    Competición de tardes va aparte (su equipo, `MiembroTardes`) y a los
    invitados no se les hace informe. `base` por defecto son los activos; para
    ver informes de antes, `Jugador.objects.all()`.
    """
    qs = base if base is not None else Jugador.objects.filter(activo=True)
    qs = qs.exclude(escuela__solo_informes=True).filter(invitaciones__isnull=True)
    if user.is_superadmin:
        return qs
    coach = _coach(user)
    if coach is not None:
        ents = coach.entrenadores.all()
        return qs.filter(Q(entrenador_responsable__in=ents) | Q(cogestores__in=ents)).distinct()
    ent = getattr(user, "entrenador", None)
    if ent is not None:
        return qs.filter(Q(entrenador_responsable=ent) | Q(cogestores=ent)).distinct()
    return qs.none()


def coaches_del_entrenador(entrenador):
    """Usuarios Coach a los que notificar sobre un entrenador (#5/#4)."""
    if entrenador is None:
        return []
    return [
        c.user
        for c in entrenador.coaches.filter(activo=True)
        if c.user_id is not None
    ]
