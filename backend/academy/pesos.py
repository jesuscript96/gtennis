"""Con quién entrena cada alumno, y en qué proporción.

La división solo sirve para emparejar alumnos entre sí. Con quién entrena cada
uno lo dicen sus porcentajes (`ResponsableJugador`): un entrenador principal y
el resto de su grupo como secundarios. Quién le gestiona es otra cosa:
`Jugador.entrenador_responsable`.

Regla de dirección para el reparto de partida: principal, el entrenador de su
columna del organigrama (si la firman varios, a partes iguales); el resto de su
grupo, secundarios con un 10% cada uno, que es el mínimo. Carlos Taberner:
Víctor 60% y Dani, Javi, Blas y Emilio 10% cada uno.
"""
from django.db import transaction

MINIMO_SECUNDARIO = 10
PRINCIPAL, SECUNDARIO = 1, 2


def reparto_por_defecto(principales, secundarios):
    """[(entrenador, prioridad, porcentaje)]: los secundarios con el mínimo y
    los principales a partes iguales con lo que queda (lo que no divide exacto,
    para los primeros). Sin principales, los secundarios pasan a serlo."""
    principales = list(dict.fromkeys(principales))
    secundarios = [s for s in dict.fromkeys(secundarios) if s not in principales]
    if not principales:
        principales, secundarios = secundarios, []
    if not principales:
        return []
    resto = 100 - MINIMO_SECUNDARIO * len(secundarios)
    if resto < len(principales):
        # Un grupo tan grande no deja sitio al principal: a partes iguales.
        principales, secundarios, resto = principales + secundarios, [], 100
    base, sobra = divmod(resto, len(principales))
    return (
        [(e, PRINCIPAL, base + (1 if i < sobra else 0))
         for i, e in enumerate(principales)]
        + [(e, SECUNDARIO, MINIMO_SECUNDARIO) for e in secundarios]
    )


def errores(filas):
    """Por qué no se pueden guardar estos porcentajes, dicho para quien los
    teclea. `filas` son (entrenador, prioridad, porcentaje); sin filas no hay
    nada que cuadrar."""
    if not filas:
        return []
    fallos = []
    if len({e for e, _p, _c in filas}) != len(filas):
        fallos.append("Hay un entrenador repetido.")
    for _e, prioridad, pct in filas:
        if prioridad not in (PRINCIPAL, SECUNDARIO):
            fallos.append("Cada entrenador es principal o secundario.")
        elif not 0 <= pct <= 100:
            fallos.append("Los porcentajes van de 0 a 100.")
        elif prioridad == SECUNDARIO and pct < MINIMO_SECUNDARIO:
            fallos.append(f"Un secundario lleva como mínimo un {MINIMO_SECUNDARIO}%.")
    if not any(p == PRINCIPAL for _e, p, _c in filas):
        fallos.append("Falta el entrenador principal.")
    total = sum(c for _e, _p, c in filas)
    if total != 100:
        fallos.append(f"Tienen que sumar 100 (ahora suman {total}).")
    return list(dict.fromkeys(fallos))


def propuesta(entrenador):
    """El reparto de partida con este entrenador de principal y el resto de su
    bloque de secundarios."""
    from .models import Entrenador

    if entrenador is None:
        return []
    otros = (
        Entrenador.objects.filter(
            coaches__in=entrenador.coaches.filter(activo=True),
            activo=True, disponible_semana=True,
        )
        .exclude(pk=entrenador.pk).distinct().order_by("nombre")
        .values_list("id", flat=True)
    )
    return reparto_por_defecto([entrenador.id], list(otros))


@transaction.atomic
def guardar(jugador, filas):
    """Sustituye los porcentajes del alumno por `filas`."""
    from .models import ResponsableJugador

    ResponsableJugador.objects.filter(jugador=jugador).delete()
    ResponsableJugador.objects.bulk_create([
        ResponsableJugador(
            jugador=jugador, entrenador_id=e, prioridad=p,
            porcentaje_objetivo=c, activo=True,
        )
        for e, p, c in filas
    ])


def quitar(jugador, entrenador_id):
    """Este entrenador deja de entrenarle; su parte pasa al principal que más
    lleva, para que sigan sumando 100."""
    from .models import ResponsableJugador

    filas = list(
        ResponsableJugador.objects.filter(jugador=jugador, activo=True)
        .order_by("prioridad", "-porcentaje_objetivo", "id")
        .values_list("entrenador_id", "prioridad", "porcentaje_objetivo")
    )
    libre = sum(c for e, _p, c in filas if e == entrenador_id)
    quedan = [list(f) for f in filas if f[0] != entrenador_id]
    if quedan:
        quedan[0][2] += libre
    guardar(jugador, [tuple(f) for f in quedan])
