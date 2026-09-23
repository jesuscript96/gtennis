"""Deshacer los cambios a mano del cuadrante.

Cada operación manual (mover un jugador, mover una pista entera, poner o quitar
un entrenador, colocar a alguien en una pista vacía) guarda antes una foto de
la semana. Deshacer es volver a la última foto y tirarla.
"""
from .models import Asignacion, CambioSemana

CAMPOS = ("dia", "turno_id", "pista_id", "jugador_id", "entrenador_id",
          "estado", "manual")


def foto(semana_id):
    return list(
        Asignacion.objects.filter(semana_id=semana_id).values(*CAMPOS)
    )


def registrar(semana_id, descripcion, usuario=None):
    """Guarda cómo está la semana antes de tocarla."""
    if not semana_id:
        return None
    cambio = CambioSemana.objects.create(
        semana_id=semana_id, descripcion=descripcion[:120], foto=foto(semana_id),
        creado_por=usuario if usuario and usuario.is_authenticated else None,
    )
    sobran = CambioSemana.objects.filter(semana_id=semana_id).values_list(
        "id", flat=True)[CambioSemana.MAXIMO:]
    if sobran:
        CambioSemana.objects.filter(id__in=list(sobran)).delete()
    return cambio


def deshacer(semana_id):
    """Restaura la última foto. Devuelve qué se deshizo, o None si no hay nada.

    La semana se rehace entera: borrar y volver a crear evita pelearse con el
    unique de (semana, día, turno, jugador) al cruzarse dos filas.
    """
    cambio = CambioSemana.objects.filter(semana_id=semana_id).first()
    if cambio is None:
        return None
    Asignacion.objects.filter(semana_id=semana_id).delete()
    Asignacion.objects.bulk_create([
        Asignacion(semana_id=semana_id, **fila) for fila in cambio.foto
    ])
    descripcion = cambio.descripcion
    cambio.delete()
    return descripcion


def quedan(semana_id):
    return CambioSemana.objects.filter(semana_id=semana_id).count()
