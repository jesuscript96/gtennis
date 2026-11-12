"""Permisos: perfiles y funciones (orden de la aplicación, 10/11/2026).

Cuatro perfiles más Administración (`users.User.Role`):

  * Dirección        → todo.
  * Head coach       → su grupo (su color): jugadores, entrenadores, faltas,
                       torneos y evaluaciones de su grupo.
  * Entrenador       → sus jugadores y su día.
  * Preparador físico→ la parte física de los informes.
  * Administración   → altas y datos de jugadores y envío de informes.

Lo demás son funciones que dirección marca a cada persona desde Club
(`users.Funcion`), en lugar de nombres escritos en el código:
Toca el cuadrante, Aprueba invitados, Coordina Competición de tardes, Valida
informes y Envía informes. Evaluar tenis o física de tardes es el equipo de
tardes (`evaluaciones.MiembroTardes`). Dirección las tiene todas.

Una sola regla por permiso, se entre por donde se entre: las vistas preguntan
aquí y el usuario lleva estas mismas respuestas a la interfaz (/auth/me/), que
esconde lo que no puede usar.

El alcance por filas (qué jugadores/entrenadores ve cada uno) vive en
`academy.scope`.
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS

TOCA_CUADRANTE = "TOCA_CUADRANTE"
APRUEBA_INVITADOS = "APRUEBA_INVITADOS"
COORDINA_TARDES = "COORDINA_TARDES"
VALIDA_INFORMES = "VALIDA_INFORMES"
ENVIA_INFORMES = "ENVIA_INFORMES"


def _autenticado(user):
    return bool(user and user.is_authenticated)


def es_direccion(user):
    return bool(_autenticado(user) and user.is_superadmin)


def es_administracion(user):
    return bool(_autenticado(user) and getattr(user, "is_administracion", False))


def es_coach(user):
    """Head coach activo (con su bloque de entrenadores)."""
    coach = getattr(user, "coach", None) if _autenticado(user) else None
    return bool(coach is not None and coach.activo and not user.is_superadmin)


def es_preparador(user):
    return bool(_autenticado(user) and getattr(user, "is_preparador", False))


def tiene_funcion(user, codigo):
    """Dirección las tiene todas; el resto, las que tenga marcadas en Club."""
    if not _autenticado(user):
        return False
    if es_direccion(user):
        return True
    return codigo in user.codigos_funcion()


def toca_cuadrante(user):
    """Mueve el cuadrante a mano, lo rehace, lo deshace y lo publica (decisión 1)."""
    return tiene_funcion(user, TOCA_CUADRANTE)


def aprueba_invitados(user):
    """Mete invitados ya aprobados y aprueba sus días. Solo dirección propone
    invitados (decisión 8); quien tiene la función cuenta como dirección para
    los invitados."""
    return tiene_funcion(user, APRUEBA_INVITADOS)


def mueve_divisiones(user):
    """División y ranking: solo dirección (decisión 5)."""
    return es_direccion(user)


# Compatibilidad: «gestión deportiva» era dirección más Dani Gimeno. Desde el
# 10/11/2026 lo que hacía Dani por estar en esa lista son funciones suyas.
gestion_deportiva = es_direccion


def ve_reglas_jugador(user):
    """Rencillas y contratos: dirección y head coaches; el entrenador, nada
    (decisión 7)."""
    return es_direccion(user) or es_coach(user)


def ve_todos_los_jugadores(user):
    """Dirección y Administración ven a todos los jugadores."""
    return es_direccion(user) or es_administracion(user)


def _en_tardes(user, funcion):
    if not _autenticado(user):
        return False
    from evaluaciones.models import MiembroTardes

    return MiembroTardes.objects.filter(usuario=user, funcion=funcion).exists()


def coordina_informes(user):
    """Lleva Competición de tardes: reparte jugadores, da altas y bajas de
    jugadores y del equipo de informes, y recibe el aviso de validar."""
    return tiene_funcion(user, COORDINA_TARDES)


def es_coordinador_tardes(user):
    """Tiene marcada la función (sin contar a dirección)."""
    return bool(_autenticado(user) and COORDINA_TARDES in user.codigos_funcion())


def valida_informes(user):
    """Aprueba, corrige o devuelve los informes. Abre y corrige las dos partes
    (decisión 11)."""
    return tiene_funcion(user, VALIDA_INFORMES)


def envia_informes(user):
    """Envía a las familias los informes aprobados: dirección, Administración
    y quien tenga la función."""
    return es_administracion(user) or tiene_funcion(user, ENVIA_INFORMES)


def evalua_tenis_solo_informes(user):
    """Hace la evaluación de tenis de los alumnos de escuelas «solo informes»."""
    return coordina_informes(user) or _en_tardes(user, "TENIS") or valida_informes(user)


def evalua_fisico(user):
    """Ve y hace evaluaciones físicas: el preparador físico, quien esté de
    físico en el equipo de tardes y quien valida (abre las dos partes)."""
    return es_preparador(user) or _en_tardes(user, "FISICO") or valida_informes(user)


def ve_informes(user):
    """Entra en los informes: quien evalúa tenis o físico, quien valida y
    quien los envía."""
    return (evalua_tenis_solo_informes(user) or evalua_fisico(user)
            or valida_informes(user) or envia_informes(user))


def _usuarios_con(codigo, con_direccion=True):
    from django.contrib.auth import get_user_model
    from django.db.models import Q

    q = Q(funciones__codigo=codigo)
    if con_direccion:
        q |= Q(role="SUPERADMIN") | Q(is_superuser=True)
    return list(get_user_model().objects.filter(is_active=True).filter(q).distinct())


def usuarios_valida_informes():
    """Usuarios activos que validan, para avisarles."""
    return _usuarios_con(VALIDA_INFORMES)


def usuarios_avisar_validar():
    """A quién se avisa de que hay un informe listo para validar: a quien
    coordina Competición de tardes (decisión 11). Si nadie tiene la función,
    a todos los que validan."""
    return _usuarios_con(COORDINA_TARDES, con_direccion=False) or usuarios_valida_informes()


def resumen(user):
    """Lo que la interfaz necesita saber para enseñar solo lo que funciona."""
    return {
        "perfil": user.perfil,
        "funciones": sorted(user.codigos_funcion()) if not es_direccion(user) else [
            TOCA_CUADRANTE, APRUEBA_INVITADOS, COORDINA_TARDES, VALIDA_INFORMES, ENVIA_INFORMES],
        "toca_cuadrante": toca_cuadrante(user),
        "aprueba_invitados": aprueba_invitados(user),
        "mueve_divisiones": mueve_divisiones(user),
        "ve_reglas_jugador": ve_reglas_jugador(user),
        "ve_todos_los_jugadores": ve_todos_los_jugadores(user),
        "coordina_informes": coordina_informes(user),
        "valida_informes": valida_informes(user),
        "envia_informes": envia_informes(user),
        "evalua_fisico": evalua_fisico(user),
        "evalua_tenis_informes": evalua_tenis_solo_informes(user),
        "ve_informes": ve_informes(user),
        # Compatibilidad con pantallas que aún lo leen.
        "gestion_deportiva": es_direccion(user),
    }


class ReadOnlyOrDireccion(BasePermission):
    """Lectura para cualquier autenticado; escritura solo para dirección."""

    message = "Solo dirección puede cambiar esto."

    def has_permission(self, request, view):
        if not _autenticado(request.user):
            return False
        if request.method in SAFE_METHODS:
            return True
        return es_direccion(request.user)


class DireccionOrCoachWrite(BasePermission):
    """Lectura para cualquier autenticado; escritura para dirección y head
    coaches. El alcance fino lo aplica el get_queryset de cada vista."""

    message = "Solo dirección o un head coach pueden cambiar esto."

    def has_permission(self, request, view):
        if not _autenticado(request.user):
            return False
        if request.method in SAFE_METHODS:
            return True
        return es_direccion(request.user) or es_coach(request.user)


class ReglasJugador(BasePermission):
    """Rencillas y contratos: ni leer ni escribir para quien no es dirección
    ni head coach (decisión 7)."""

    message = "Las rencillas y los contratos solo los ven dirección y los head coaches."

    def has_permission(self, request, view):
        return ve_reglas_jugador(request.user)


class TocaCuadrante(BasePermission):
    """Lectura para cualquier autenticado; cambios para quien toca el cuadrante."""

    message = "No tienes la función «Toca el cuadrante»."

    def has_permission(self, request, view):
        if not _autenticado(request.user):
            return False
        if request.method in SAFE_METHODS:
            return True
        return toca_cuadrante(request.user)
