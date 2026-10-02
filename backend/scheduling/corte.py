"""El corte del día siguiente (01/10/2026).

A las 19:00 se genera el día siguiente y queda cerrado; el sábado, el viernes
a las 16:30. Lo que se declare antes entra en esa generación. Lo que llegue
después no toca el cuadrante: el jugador sale tachado y se avisa a quien puede
verle para que lo cambie a mano.
"""
from datetime import date, datetime, time, timedelta

from django.utils import timezone

HORA_CORTE = time(19, 0)
HORA_CORTE_SABADO = time(16, 30)  # el viernes, para el sábado
SABADO, DOMINGO = 5, 6


def corte(fecha: date) -> datetime:
    """Momento en que se cierra `fecha`: el día anterior a la hora de corte."""
    hora = HORA_CORTE_SABADO if fecha.weekday() == SABADO else HORA_CORTE
    return timezone.make_aware(datetime.combine(fecha - timedelta(days=1), hora))


def cerrado(fecha: date, ahora: datetime | None = None) -> bool:
    return (ahora or timezone.now()) >= corte(fecha)


def lunes_y_dia(fecha: date) -> tuple[date, int]:
    return fecha - timedelta(days=fecha.weekday()), fecha.weekday()


def dia_a_generar(ahora: datetime | None = None) -> date | None:
    """El día de entreno cuyo corte ya ha pasado y que todavía no ha empezado:
    mañana después de las 19:00 (o del viernes a las 16:30). El domingo no se
    entrena."""
    ahora = timezone.localtime(ahora or timezone.now())
    manana = ahora.date() + timedelta(days=1)
    if manana.weekday() == DOMINGO:
        return None
    return manana if cerrado(manana, ahora) else None


def dias_cerrados(desde: date, hasta: date, ahora: datetime | None = None) -> list[date]:
    """De las fechas entre `desde` y `hasta`, las que ya están cerradas y no
    han pasado: hoy y, después del corte, mañana."""
    ahora = timezone.localtime(ahora or timezone.now())
    hoy = ahora.date()
    out = []
    d = max(desde, hoy)
    while d <= hasta and d <= hoy + timedelta(days=1):
        if d.weekday() != DOMINGO and cerrado(d, ahora):
            out.append(d)
        d += timedelta(days=1)
    return out
