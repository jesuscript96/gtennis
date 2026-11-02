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
    """Ve y hace evaluaciones físicas: el preparador físico, gestión deportiva y
    quien esté de físico en el equipo de tardes."""
    return es_preparador(user) or gestion_deportiva(user) or _en_tardes(user, "FISICO")


# Competición de tardes. Alberto Sanz coordina (29/10/2026) y desde el
# 02/11/2026 también valida sus informes, reparte los jugadores y da de alta y
# de baja a jugadores y entrenadores de tardes. Quién evalúa cada parte ya no
# es una lista fija: lo lleva él en la app (`evaluaciones.MiembroTardes`).
COORDINAN_COMPETICION_TARDES = {"alberto.sanz"}


def _de(user, nombres):
    return bool(user and user.is_authenticated and user.username in nombres)


def _en_tardes(user, funcion):
    if not (user and user.is_authenticated):
        return False
    from evaluaciones.models import MiembroTardes

    return MiembroTardes.objects.filter(usuario=user, funcion=funcion).exists()


def es_coordinador_tardes(user):
    return _de(user, COORDINAN_COMPETICION_TARDES)


def coordina_informes(user):
    """Lleva Competición de tardes: reparte jugadores, da altas y bajas de
    jugadores y del equipo de informes."""
    return gestion_deportiva(user) or es_coordinador_tardes(user)


def evalua_tenis_solo_informes(user):
    """Hace la evaluación de tenis de los alumnos de escuelas «solo informes»."""
    return (gestion_deportiva(user) or es_coordinador_tardes(user)
            or _en_tardes(user, "TENIS"))


# Además de gestión deportiva, valida Iván Gallego (coach, como Dani: «validan
# Sergio, Iván, Dani Gimeno o admin», 27/10/2026), y el coordinador de tardes.
VALIDAN_INFORMES = {"ivan.gallego"}
# Administración envía los informes a las familias, pero no los valida (29/10/2026).
NO_VALIDAN_INFORMES = {"administracion"}


def valida_informes(user):
    """Valida (aprueba, corrige o devuelve) los informes: el coordinador de
    tardes y gestión deportiva (Sergio, Iván, Dani Gimeno, admin y el resto de
    dirección, menos administración)."""
    if _de(user, NO_VALIDAN_INFORMES):
        return False
    return gestion_deportiva(user) or _de(user, VALIDAN_INFORMES) or es_coordinador_tardes(user)


def ve_informes(user):
    """Ve los informes de Competición de tardes: quien evalúa tenis o físico
    de esos alumnos y quien valida."""
    return evalua_tenis_solo_informes(user) or evalua_fisico(user) or valida_informes(user)


def usuarios_valida_informes():
    """Usuarios activos que validan, para avisarles."""
    from django.contrib.auth import get_user_model

    from django.db.models import Q
    User = get_user_model()
    return [u for u in User.objects.filter(is_active=True).filter(
        Q(role="SUPERADMIN") | Q(is_superuser=True) | Q(username__in=GESTION_DEPORTIVA | VALIDAN_INFORMES | COORDINAN_COMPETICION_TARDES))
        .exclude(username__in=NO_VALIDAN_INFORMES)]


def usuarios_avisar_validar():
    """A quién se avisa de que hay un informe listo para validar: el
    coordinador de tardes (02/11/2026). Sin él activo, a todos los que validan."""
    from django.contrib.auth import get_user_model

    coord = list(get_user_model().objects.filter(is_active=True, username__in=COORDINAN_COMPETICION_TARDES))
    return coord or usuarios_valida_informes()
