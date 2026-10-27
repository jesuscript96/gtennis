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


# Además de dirección, estos usuarios meten invitados ya aprobados y aprueban
# los de los demás (petición del 21/10/2026: Dani e Iván cuentan como dirección
# para los invitados aunque su rol sea de coach).
APRUEBAN_INVITADOS = {"daniel.gimeno", "ivan.gallego"}


def aprueba_invitados(user):
    return es_direccion(user) or bool(
        user and user.is_authenticated and user.username in APRUEBAN_INVITADOS)


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


# Gestión deportiva (21/10/2026): dirección y, además, Dani Gimeno aunque su
# rol sea de coach. Mueven alumnos de una división a otra desde Divisiones y
# ven y hacen la parte física de los informes.
GESTION_DEPORTIVA = {"daniel.gimeno"}


def gestion_deportiva(user):
    return es_direccion(user) or bool(
        user and user.is_authenticated and user.username in GESTION_DEPORTIVA)


mueve_divisiones = gestion_deportiva


def es_preparador(user):
    return bool(user and user.is_authenticated and getattr(user, "is_preparador", False))


def evalua_fisico(user):
    """Ve y hace evaluaciones físicas: el preparador físico y gestión deportiva."""
    return es_preparador(user) or gestion_deportiva(user)


# Entrenadores de tenis de Competición de tardes (27/10/2026): de momento los
# tres evalúan a todos los jugadores de la escuela. Gestión deportiva también.
EVALUAN_COMPETICION_TARDES = {"alvaro.mantoan", "alberto.sanz", "jorge.mico"}


def evalua_tenis_solo_informes(user):
    """Hace la evaluación de tenis de los alumnos de escuelas «solo informes»."""
    return gestion_deportiva(user) or bool(
        user and user.is_authenticated and user.username in EVALUAN_COMPETICION_TARDES)
