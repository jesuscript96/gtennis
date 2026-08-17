"""Permisos por rol (arquitectura de usuarios).

Jerarquía: Dirección deportiva (SUPERADMIN) → Coach → Entrenador.

  * ReadOnlyOrDireccion   → cualquiera autenticado lee; solo dirección escribe.
                            Config de club (sedes, pistas, divisiones, motor…).
  * DireccionOrCoachWrite → cualquiera autenticado lee; dirección y coaches
                            escriben. El alcance fino (equipo del coach) lo
                            aplica el get_queryset de cada viewset.

El alcance por filas (qué jugadores/entrenadores ve cada uno) vive en
`academy.scope`; aquí solo se decide quién puede escribir por método.
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS


def es_direccion(user):
    return bool(user and user.is_authenticated and user.is_superadmin)


def es_coach(user):
    coach = getattr(user, "coach", None) if (user and user.is_authenticated) else None
    return bool(coach is not None and coach.activo)


class ReadOnlyOrDireccion(BasePermission):
    """Lectura para cualquier autenticado; escritura solo para dirección."""

    message = "Solo la dirección deportiva puede modificar este recurso."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return es_direccion(request.user)


class DireccionOrCoachWrite(BasePermission):
    """Lectura para cualquier autenticado; escritura para dirección y coaches."""

    message = "Necesitas ser dirección o coach para modificar este recurso."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return es_direccion(request.user) or es_coach(request.user)
