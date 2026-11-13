"""Meter a un alumno en un grupo (quién le gestiona): una sola regla y un solo
efecto, se haga desde Grupos o desde su ficha (decisión 4; la ficha vuelve a
tenerlo el 13/11/2026 a petición del club: dos puertas, una regla).

  * Dirección mete o saca a cualquiera.
  * El head coach, dentro de su grupo de color: el alumno es de una columna de
    su color (o no tiene grupo, o su gestor está de baja) y la columna a la que
    va, también.
  * Cambiar de grupo no toca los porcentajes (con quién entrena); quien
    compartía la gestión deja de compartirla.
"""
from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from .models import ResponsableJugador


def _color_propio(user):
    """Los entrenadores del grupo de color del usuario, si es su head coach;
    si no, None."""
    coach = getattr(user, "coach", None)
    if coach is None or not coach.activo or not coach.color:
        return None
    return set(coach.entrenadores.values_list("pk", flat=True))


def puede_mover(user, jugador, entrenador):
    """¿Puede `user` meter a `jugador` en el grupo de `entrenador`? Con
    `entrenador=None`, ¿puede sacarle de su grupo?"""
    if user.is_superadmin:
        return True
    suyos = _color_propio(user)
    if suyos is None:
        return False
    actual = jugador.entrenador_responsable
    sale_de_lo_suyo = actual is None or not actual.activo or actual.pk in suyos
    if entrenador is None:
        return actual is not None and actual.pk in suyos
    return entrenador.pk in suyos and sale_de_lo_suyo


def assert_puede_mover(user, jugador, entrenador):
    if not puede_mover(user, jugador, entrenador):
        raise PermissionDenied("Solo puedes mover a los alumnos de tu grupo de color.")


def meter_en_grupo(jugador, entrenador):
    """Le pone en el grupo de `entrenador` (o «Sin grupo» con None). Devuelve
    si conviene revisar sus porcentajes: el nuevo gestor no está entre los que
    le entrenan."""
    with transaction.atomic():
        jugador.entrenador_responsable = entrenador
        jugador.save(update_fields=["entrenador_responsable"])
        jugador.cogestores.clear()
    if entrenador is None:
        return False
    entrena_con = set(ResponsableJugador.objects.filter(jugador=jugador, activo=True)
                      .values_list("entrenador_id", flat=True))
    return bool(entrena_con) and entrenador.id not in entrena_con
