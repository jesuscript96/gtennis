"""El calendario del entrenador escrito desde los comandos de carga.

Desde el 10/11/2026 que un entrenador no está se apunta solo en su calendario
(`VacacionesEntrenador`). El interruptor «Disponible esta semana» de la ficha
ya no se ve en la app, pero el motor lo sigue leyendo: un comando que lo
apagara dejaría a alguien fuera sin que nadie lo viera. Por eso los comandos
que leen el Excel del club escriben aquí, con un motivo propio. Así se ve en su
calendario y cada carga puede deshacer lo suyo sin tocar lo apuntado a mano.
"""
from datetime import date, time, timedelta

from .models import VacacionesEntrenador

# «No disponible» indefinido: columna «disponible» de la plantilla del club o
# entrenador fuera de servicio en el organigrama.
MOTIVO_CARGA = "No disponible (carga de Excel)"
# No sale en el roster de una semana concreta (`sync_semana_excel`).
MOTIVO_SEMANA = "No sale esta semana (carga de Excel)"

INICIO_DIA, FIN_DIA = time(0, 0), time(23, 59)
# «Indefinido» = un año, como hizo la migración 0034 con el interruptor.
UN_ANIO = timedelta(days=365)
DIA = VacacionesEntrenador.Ambito.DIA
UN_DIA = timedelta(days=1)


def _dia_entero(qs):
    return qs.filter(ambito=DIA, hora_desde__isnull=True, hora_hasta__isnull=True)


def marcar_no_disponible(entrenador, desde=None, hasta=None, motivo=MOTIVO_CARGA):
    """Apunta que no está de `desde` a `hasta`, el día entero.

    Sin `desde`, desde hoy; sin `hasta`, un año. No duplica: si ya tiene una
    con el mismo motivo que pisa esas fechas o empieza o acaba justo al lado,
    la alarga hasta cubrirlas. Devuelve "creada", "ampliada" o "ya estaba".
    """
    desde = desde or date.today()
    hasta = hasta or desde + UN_ANIO
    if hasta < desde:
        raise ValueError("La fecha de fin no puede ser anterior al inicio.")
    vecina = (
        _dia_entero(VacacionesEntrenador.objects.filter(
            entrenador=entrenador, motivo=motivo,
            fecha_inicio__lte=hasta + UN_DIA, fecha_fin__gte=desde - UN_DIA,
        ))
        .order_by("fecha_inicio")
        .first()
    )
    if vecina is None:
        VacacionesEntrenador.objects.create(
            entrenador=entrenador, fecha_inicio=desde, fecha_fin=hasta,
            ambito=DIA, motivo=motivo)
        return "creada"
    ini, fin = min(vecina.fecha_inicio, desde), max(vecina.fecha_fin, hasta)
    if (ini, fin) == (vecina.fecha_inicio, vecina.fecha_fin):
        return "ya estaba"
    vecina.fecha_inicio, vecina.fecha_fin = ini, fin
    vecina.save(update_fields=["fecha_inicio", "fecha_fin"])
    return "ampliada"


def volver_disponible(entrenador, desde=None, hasta=None, motivo=MOTIVO_CARGA):
    """Le quita lo que apuntó la carga con `motivo` de `desde` a `hasta`.

    Sin `desde`, desde hoy; sin `hasta`, sin final: cierra todo lo abierto.
    Lo que cae fuera de esas fechas se conserva (lo pasado sigue en el
    historial: una ausencia que ya había empezado se cierra la víspera). Nada
    con otro motivo se toca. Devuelve cuántas ha cerrado, recortado o borrado.
    """
    desde = desde or date.today()
    qs = VacacionesEntrenador.objects.filter(
        entrenador=entrenador, motivo=motivo, fecha_fin__gte=desde)
    if hasta is not None:
        qs = qs.filter(fecha_inicio__lte=hasta)
    n = 0
    for v in qs:
        antes = v.fecha_inicio < desde
        despues = hasta is not None and v.fecha_fin > hasta
        if antes and despues:
            # El hueco cae en medio: queda un trozo a cada lado.
            VacacionesEntrenador.objects.create(
                entrenador_id=v.entrenador_id, fecha_inicio=hasta + UN_DIA,
                fecha_fin=v.fecha_fin, motivo=v.motivo, ambito=v.ambito,
                hora_desde=v.hora_desde, hora_hasta=v.hora_hasta)
        if antes:
            v.fecha_fin = desde - UN_DIA
        elif despues:
            v.fecha_inicio = hasta + UN_DIA
        if antes or despues:
            v.save(update_fields=["fecha_inicio", "fecha_fin"])
        else:
            v.delete()
        n += 1
    return n


def solo_disponible(entrenador, fecha, desde, hasta, motivo):
    """Ese día solo está de `desde` a `hasta`.

    Igual que la migración 0034: no está de 00:00 a `desde` ni de `hasta` a
    23:59. Devuelve las ausencias creadas (ninguna si cubre el día entero).
    """
    base = dict(entrenador=entrenador, fecha_inicio=fecha, fecha_fin=fecha,
                ambito=DIA, motivo=motivo[:200])
    nuevas = []
    if desde and desde > INICIO_DIA:
        nuevas.append(VacacionesEntrenador.objects.create(
            hora_desde=INICIO_DIA, hora_hasta=desde, **base))
    if hasta and hasta < FIN_DIA:
        nuevas.append(VacacionesEntrenador.objects.create(
            hora_desde=hasta, hora_hasta=FIN_DIA, **base))
    return nuevas


def ausentes_todo_el_dia(fecha, entrenadores=None):
    """Ids de los entrenadores que `fecha` tienen una ausencia del día entero
    y sin horas en su calendario."""
    qs = _dia_entero(VacacionesEntrenador.objects.filter(
        fecha_inicio__lte=fecha, fecha_fin__gte=fecha))
    if entrenadores is not None:
        qs = qs.filter(entrenador__in=entrenadores)
    return set(qs.values_list("entrenador_id", flat=True))


def marcado_por_carga(entrenador, desde, hasta, motivo=MOTIVO_CARGA):
    """¿Tiene una ausencia de la carga con `motivo` que cubre de `desde` a
    `hasta` entero?"""
    return _dia_entero(VacacionesEntrenador.objects.filter(
        entrenador=entrenador, motivo=motivo,
        fecha_inicio__lte=desde, fecha_fin__gte=hasta,
    )).exists()
