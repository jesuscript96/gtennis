"""Quitar unos días de algo declarado por fechas (20/10/2026).

Un torneo del lunes al sábado del que vuelve el miércoles: hasta ahora solo se
podía quitar la falta entera. Aquí se quitan solo los días que ya no valen y el
resto se queda como estaba: se acorta por un lado, por el otro, o se parte en
dos si los días quitados caen en medio.
"""
from datetime import date, timedelta

UN_DIA = timedelta(days=1)


def quitar_dias(fila, desde, hasta, campo_ini="fecha_inicio", campo_fin="fecha_fin"):
    """Quita de `fila` los días de `desde` a `hasta`, ambos incluidos.

    Devuelve las filas que quedan: ninguna si se quitan todos sus días, una si
    se acorta y dos si se parte. La parte de detrás es una fila nueva con los
    mismos datos y la misma fecha de alta: sigue siendo lo que se declaró
    entonces, no algo nuevo.
    """
    ini, fin = getattr(fila, campo_ini), getattr(fila, campo_fin)
    desde, hasta = max(desde, ini), min(hasta, fin)
    if desde > hasta:
        raise ValueError("Esos días no están dentro de lo declarado.")

    queda_antes = desde > ini
    queda_despues = hasta < fin
    if not queda_antes and not queda_despues:
        fila.delete()
        return []
    if not queda_antes:
        setattr(fila, campo_ini, hasta + UN_DIA)
        fila.save(update_fields=[campo_ini])
        return [fila]

    setattr(fila, campo_fin, desde - UN_DIA)
    fila.save(update_fields=[campo_fin])
    if not queda_despues:
        return [fila]

    modelo = type(fila)
    copia = modelo.objects.get(pk=fila.pk)
    copia.pk = None
    copia._state.adding = True
    setattr(copia, campo_ini, hasta + UN_DIA)
    setattr(copia, campo_fin, fin)
    copia.save()
    alta = getattr(fila, "created_at", None)
    if alta is not None:
        # `auto_now_add` le pone la hora de ahora; se le devuelve la suya.
        modelo.objects.filter(pk=copia.pk).update(created_at=alta)
        copia.created_at = alta
    return [fila, copia]


def fechas_a_quitar(datos, fin):
    """(desde, hasta) de la petición. Sin `hasta`, hasta el final: «ha vuelto
    el miércoles» quita del miércoles en adelante."""
    from rest_framework.exceptions import ValidationError

    try:
        desde = date.fromisoformat(str(datos.get("desde")))
        hasta = date.fromisoformat(str(datos["hasta"])) if datos.get("hasta") else fin
    except ValueError:
        raise ValidationError({"error": "Fecha no válida (AAAA-MM-DD)."})
    if hasta < desde:
        raise ValidationError({"error": "El último día no puede ser anterior al primero."})
    return desde, hasta
