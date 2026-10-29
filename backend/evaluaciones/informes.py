"""El circuito del informe de Competición de tardes (27/10/2026).

Tenis y físico se hacen por separado; cada uno queda colgando del informe
abierto de su jugador. Cuando las dos partes están terminadas, el informe pasa
a «pendiente de validar»: se genera el PDF conjunto, se guarda en Drive en la
carpeta «Pendientes de validar» del jugador y se avisa a quien valida. Quien
valida lo aprueba (va a «Validados y enviados») o lo devuelve con una nota a
quien hizo esa parte. El envío por correo a las familias aún no existe: al
aprobar se guardan los destinatarios para cuando lo haya.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from academy.models import Aviso
from academy.permissions import (
    COORDINAN_COMPETICION_TARDES, EVALUAN_COMPETICION_TARDES, FISICO_COMPETICION_TARDES, usuarios_valida_informes,
)

from .models import AsignacionInforme, Evaluacion, EvaluacionFisica, Informe

log = logging.getLogger(__name__)

CICLO_PRONTO = 75     # días desde la validación: «toca pronto»
CICLO_VENCIDO = 90    # «vencido»
PRIMERA_TRAS_ALTA = 7  # un jugador nuevo, a la semana de su alta


class InformeError(Exception):
    """Algo que el usuario tiene que saber (se devuelve como 400)."""


def es_de_informe(jugador):
    return bool(jugador.escuela_id and jugador.escuela.solo_informes)


def informe_abierto(jugador, crear=True):
    """El informe en curso del jugador (no validado). Si no hay y `crear`, uno nuevo."""
    inf = jugador.informes.exclude(estado=Informe.Estado.VALIDADO).order_by("-creado").first()
    if inf is None and crear:
        inf = Informe.objects.create(jugador=jugador)
    return inf


def vincular(ev):
    """Cuelga una evaluación recién creada (de tenis o física) del informe
    abierto de su jugador. Si ese informe ya tiene esa parte, no deja crear
    otra: hay que seguir con la que hay."""
    if not es_de_informe(ev.jugador):
        return None
    campo = "tenis" if isinstance(ev, Evaluacion) else "fisica"
    with transaction.atomic():
        inf = informe_abierto(ev.jugador)
        actual = getattr(inf, campo)
        if actual is not None and actual.pk != ev.pk:
            raise InformeError(actual.pk)
        setattr(inf, campo, ev)
        inf.save(update_fields=[campo, "actualizado"])
    return inf


def parte_existente(jugador, campo):
    """La evaluación de esa parte que ya está en el informe abierto, si la hay."""
    inf = informe_abierto(jugador, crear=False) if es_de_informe(jugador) else None
    return getattr(inf, campo) if inf else None


def _avisar(usuarios, titulo, mensaje):
    vistos = set()
    for u in usuarios:
        if u is None or u.pk in vistos:
            continue
        vistos.add(u.pk)
        Aviso.objects.create(usuario=u, tipo=Aviso.Tipo.GENERAL, titulo=titulo, mensaje=mensaje)


def autores(inf, partes=("tenis", "fisico")):
    out = []
    if "tenis" in partes and inf.tenis and inf.tenis.evaluador:
        out.append(inf.tenis.evaluador)
    if "fisico" in partes and inf.fisica and inf.fisica.evaluador:
        out.append(inf.fisica.evaluador)
    return out


def _traducir_fisico(inf):
    """Si el informe va en inglés, los textos del preparador físico (que se
    escriben en español) se pasan a inglés con la IA."""
    from . import ia

    if not inf.tenis or inf.tenis.idioma == "ES" or not inf.fisica:
        inf.textos_fisico_traducidos = {}
        return
    out = {}
    for clave, texto in inf.fisica.textos.items():
        if not texto:
            continue
        try:
            out[clave] = ia.pulir(texto, inf.tenis.idioma, "la preparación física")
        except ia.IANoDisponible:
            out[clave] = texto
    inf.textos_fisico_traducidos = out


def guardar_en_drive(inf):
    """Genera el PDF conjunto y lo deja en la carpeta que toca según el
    estado. Devuelve un aviso si Drive falla (el informe sigue en la app)."""
    from . import drive

    if not drive.configurado():
        return None
    try:
        drive.subir_informe(inf)
        inf.save(update_fields=["drive_file_id", "drive_url", "drive_carpeta", "actualizado"])
    except drive.DriveNoDisponible as e:
        return f"{e} El informe está en la app; se reintenta al validar."
    return None


def parte_terminada(ev):
    """Se llama al terminar (o volver a terminar) una parte. Si con ella el
    informe queda completo, pasa a pendiente de validar."""
    inf = getattr(ev, "informe", None)
    if inf is None:
        return None
    inf.refresh_from_db()
    if not inf.completo:
        return inf
    if inf.estado == Informe.Estado.PENDIENTE:
        # Ya estaba pendiente y se ha retocado: se rehace el PDF, sin avisar otra vez.
        _traducir_fisico(inf)
        inf.save(update_fields=["textos_fisico_traducidos", "actualizado"])
        guardar_en_drive(inf)
        return inf
    corregido = inf.estado == Informe.Estado.VALIDADO
    if corregido:
        inf.version += 1
    inf.estado = Informe.Estado.PENDIENTE
    inf.devuelto_partes = []
    _traducir_fisico(inf)
    inf.save()
    guardar_en_drive(inf)
    nombre = inf.jugador.nombre
    _avisar(usuarios_valida_informes(),
            f"Informe de {nombre} {'corregido, ' if corregido else ''}listo para validar",
            "Tenis y preparación física están terminados. Revísalo en Informes y apruébalo o "
            "devuélvelo con una nota.")
    return inf


def aprobar(inf, usuario, destinatarios):
    if inf.estado != Informe.Estado.PENDIENTE:
        raise InformeError("Solo se aprueban informes pendientes de validar.")
    inf.estado = Informe.Estado.VALIDADO
    inf.validado_por = usuario
    inf.validado_en = timezone.now()
    inf.destinatarios = destinatarios
    inf.save()
    aviso_drive = guardar_en_drive(inf)
    _avisar(autores(inf), f"Informe de {inf.jugador.nombre} validado",
            "Ya está en «Validados y enviados». El siguiente toca en unos 90 días.")
    return aviso_drive


def devolver(inf, usuario, partes, nota):
    if inf.estado != Informe.Estado.PENDIENTE:
        raise InformeError("Solo se devuelven informes pendientes de validar.")
    partes = [p for p in partes if p in ("tenis", "fisico")]
    if not partes:
        raise InformeError("Indica qué parte hay que corregir: tenis, físico o las dos.")
    if not nota.strip():
        raise InformeError("Escribe qué hay que corregir.")
    inf.estado = Informe.Estado.DEVUELTO
    inf.devuelto_partes = partes
    inf.nota_devolucion = nota.strip()
    inf.devuelto_por = usuario
    inf.devuelto_en = timezone.now()
    inf.save()
    que = " y ".join({"tenis": "tenis", "fisico": "preparación física"}[p] for p in partes)
    destinatarios = autores(inf, partes)
    _avisar(destinatarios, f"Informe de {inf.jugador.nombre} devuelto: {que}",
            f"{usuario.get_full_name() or usuario.username}: {inf.nota_devolucion}")


# --- Ciclo de cada jugador ------------------------------------------------------

def ultimo_validado(jugador):
    return (jugador.informes.filter(estado=Informe.Estado.VALIDADO, validado_en__isnull=False)
            .order_by("-validado_en").first())


def ciclo(jugador, hoy=None):
    """Dónde está el jugador en su ciclo trimestral:
    `{"estado": nuevo|primera|al_dia|pronto|vencido, "proxima": fecha, "desde": fecha}`.
    «nuevo»: aún no toca (menos de una semana desde el alta); «primera»: le toca
    su primer informe; el resto cuenta desde la validación del último."""
    hoy = hoy or timezone.localdate()
    ult = ultimo_validado(jugador)
    if ult is None:
        desde = jugador.fecha_alta
        proxima = (desde + timedelta(days=PRIMERA_TRAS_ALTA)) if desde else hoy
        return {"estado": "nuevo" if hoy < proxima else "primera", "proxima": proxima, "desde": desde}
    desde = timezone.localtime(ult.validado_en).date()
    dias = (hoy - desde).days
    estado = "al_dia" if dias < CICLO_PRONTO else "pronto" if dias < CICLO_VENCIDO else "vencido"
    return {"estado": estado, "proxima": desde + timedelta(days=CICLO_VENCIDO), "desde": desde}


def _usuarios(**filtro):
    from django.contrib.auth import get_user_model

    return list(get_user_model().objects.filter(is_active=True, **filtro).select_related("entrenador")
                .order_by("first_name", "username"))


def evaluadores_tenis_por_defecto():
    """Los entrenadores de tenis de Competición de tardes: entre ellos reparte el coordinador."""
    return _usuarios(username__in=EVALUAN_COMPETICION_TARDES)


def coordinadores():
    return _usuarios(username__in=COORDINAN_COMPETICION_TARDES)


def preparadores():
    """Quien hace la física de Competición de tardes; sin él, todos los preparadores."""
    return _usuarios(username__in=FISICO_COMPETICION_TARDES) or _usuarios(role="PREPARADOR")


def asignar(jugadores, evaluador, por):
    """El coordinador da (o quita, con `evaluador=None`) los informes de tenis
    de esos jugadores a un entrenador, que recibe un aviso con los nuevos."""
    nuevos = []
    for j in jugadores:
        if evaluador is None:
            AsignacionInforme.objects.filter(jugador=j).delete()
            continue
        a, creada = AsignacionInforme.objects.get_or_create(
            jugador=j, defaults={"evaluador": evaluador, "asignado_por": por})
        if not creada and a.evaluador_id != evaluador.pk:
            a.evaluador, a.asignado_por = evaluador, por
            a.save()
            creada = True
        if creada:
            nuevos.append(j.nombre)
    if nuevos and evaluador.pk != por.pk:
        n = len(nuevos)
        _avisar([evaluador], f"Te han asignado {n} jugador{'es' if n != 1 else ''} para los informes",
                f"Te toca hacer el informe de tenis de: {', '.join(nuevos)}. Los tienes en Informes, "
                f"en «Mis jugadores».")
    return nuevos
