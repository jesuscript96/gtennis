"""Deshacer en el calendario de torneos.

Cada cambio (alta, edición, acompañante, borrar, fusionar, apuntar, mover,
confirmar, quitar) guarda antes la foto de los torneos que toca. Deshacer
devuelve esos torneos a la foto y la tira. Cada usuario deshace lo suyo, del
último cambio hacia atrás; si alguien tocó después alguno de esos torneos, no
se deshace, para no pisar su trabajo.
"""
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from academy.models import Entrenador, Jugador

from .models import CambioTorneo, Participante, Torneo

CAMPOS = ("nombre", "circuito", "nivel", "lugar", "fecha_inicio", "fecha_fin",
          "cierre_inscripcion", "estado", "acompanante_nota", "notas", "fuente",
          "alias", "creado_por_id", "created_at", "qualy_inicio", "qualy_fin", "solo_fines_semana")
# Añadidos el 16/10: una foto anterior no los trae y entonces se respetan
# los que tenga ahora el torneo.
CAMPOS_NUEVOS = ("qualy_inicio", "qualy_fin", "solo_fines_semana")
CAMPOS_P = ("id", "jugador_id", "nombre", "certeza", "entrenador_ref", "detalle")


def _estado(tid):
    t = Torneo.objects.filter(pk=tid).values(*CAMPOS).first()
    if t is None:
        return None
    # A mano: el codificador JSON de Django recorta los microsegundos.
    t["created_at"] = t["created_at"].isoformat() if t["created_at"] else None
    t["acompanantes"] = list(
        Torneo.acompanantes.through.objects.filter(torneo_id=tid).values_list("entrenador_id", flat=True))
    t["participantes"] = list(Participante.objects.filter(torneo_id=tid).values(*CAMPOS_P))
    return t


def foto(*ids):
    return {str(i): _estado(i) for i in dict.fromkeys(i for i in ids if i)}


def registrar(usuario, descripcion, *ids, foto_previa=None):
    """Guarda cómo están los torneos `ids` antes de tocarlos (o `foto_previa`
    si ya se tomó, p. ej. en un alta, donde el torneo aún no existía)."""
    cambio = CambioTorneo.objects.create(
        descripcion=descripcion[:160], foto=foto_previa if foto_previa is not None else foto(*ids),
        creado_por=usuario if usuario and usuario.is_authenticated else None,
    )
    sobran = CambioTorneo.objects.filter(creado_por=cambio.creado_por).values_list(
        "id", flat=True)[CambioTorneo.MAXIMO:]
    if sobran:
        CambioTorneo.objects.filter(id__in=list(sobran)).delete()
    return cambio


def ultimo(usuario):
    return CambioTorneo.objects.filter(creado_por=usuario).first()


def bloqueo(cambio):
    """Un cambio posterior de otra persona sobre alguno de estos torneos."""
    ids = set(cambio.foto)
    for c in CambioTorneo.objects.filter(creado_at__gt=cambio.creado_at).exclude(
            creado_por=cambio.creado_por).select_related("creado_por"):
        if ids & set(c.foto):
            return c
    return None


@transaction.atomic
def deshacer(cambio):
    """Devuelve los torneos de la foto a como estaban. Devuelve la descripción."""
    foto_ = cambio.foto
    ids = [int(i) for i in foto_]
    ids_p = [p["id"] for e in foto_.values() if e for p in e["participantes"]]
    Participante.objects.filter(torneo_id__in=ids).delete()
    Participante.objects.filter(id__in=ids_p).delete()
    jugadores = set(Jugador.objects.filter(
        id__in=[p["jugador_id"] for e in foto_.values() if e for p in e["participantes"] if p["jugador_id"]]
    ).values_list("id", flat=True))
    entrenadores = set(Entrenador.objects.values_list("id", flat=True))
    nuevos = []
    for tid, e in ((int(k), v) for k, v in foto_.items()):
        if e is None:
            Torneo.objects.filter(pk=tid).delete()
            continue
        actual = Torneo.objects.filter(pk=tid).values(*CAMPOS_NUEVOS).first() or {}
        campos = {**actual, **{k: v for k, v in e.items() if k in CAMPOS and k != "created_at"}}
        creado = parse_datetime(e["created_at"]) if e.get("created_at") else timezone.now()
        # Con el pk puesto, save() actualiza si existe y crea si no; la fecha de
        # alta hay que darla, o el UPDATE la dejaría vacía.
        Torneo(pk=tid, created_at=creado, **campos).save()
        Torneo.objects.filter(pk=tid).update(created_at=creado)
        Torneo.objects.get(pk=tid).acompanantes.set([i for i in e["acompanantes"] if i in entrenadores])
        for p in e["participantes"]:
            nuevos.append(Participante(
                torneo_id=tid, **{**p, "jugador_id": p["jugador_id"] if p["jugador_id"] in jugadores else None}))
    Participante.objects.bulk_create(nuevos)
    descripcion = cambio.descripcion
    cambio.delete()
    return descripcion
