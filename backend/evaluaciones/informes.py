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

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

from academy.models import Aviso
from academy.permissions import COORDINA_TARDES, usuarios_avisar_validar, usuarios_valida_informes

from .models import AsignacionInforme, Evaluacion, EvaluacionFisica, Informe, MiembroTardes

log = logging.getLogger(__name__)

CICLO_PRONTO = 75     # días desde la validación: «toca pronto»
CICLO_VENCIDO = 90    # «vencido»
PRIMERA_TRAS_ALTA = 7  # un jugador nuevo, a la semana de su alta


class InformeError(Exception):
    """Algo que el usuario tiene que saber (se devuelve como 400)."""


def idioma_familia(jugador, defecto="ES"):
    """Idioma del PDF que se envía a la familia (02/11/2026): lo demás va
    siempre en español. Sin dato, `defecto` (el de las evaluaciones de antes,
    cuando lo elegía el entrenador)."""
    try:
        return jugador.datos_informe.idioma
    except ObjectDoesNotExist:
        return defecto


def destinatarios_propuestos(jugador):
    """Los correos de la familia que se proponen al aprobar el informe."""
    datos = getattr(jugador, "datos_informe", None)
    out = []
    if jugador.email:
        out.append({"email": jugador.email, "quien": (datos.quien_1 if datos else "") or "Familia"})
    if datos and datos.email_2:
        out.append({"email": datos.email_2, "quien": datos.quien_2 or "Familia"})
    return out


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
    otra: hay que seguir con la que hay.

    Desde el 10/11/2026 también Alto rendimiento (decisión 12): su informe es
    solo la parte de tenis y pasa por la misma validación."""
    if not es_de_informe(ev.jugador) and not isinstance(ev, Evaluacion):
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
    inf = informe_abierto(jugador, crear=False)
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


def idioma_pdf(inf):
    """El idioma del PDF que se guarda: en español mientras se revisa; una vez
    validado, el de la familia, que es el que se le envía."""
    if inf.estado != Informe.Estado.VALIDADO:
        return "ES"
    return idioma_familia(inf.jugador, inf.tenis.idioma if inf.tenis else "ES")


def pdf_de(inf, idioma="ES"):
    """(nombre, contenido) del PDF del informe: el conjunto de tardes o, en
    Alto rendimiento, el de su evaluación de tenis."""
    from . import pdf

    if inf.circuito == "alto_rendimiento":
        return pdf.nombre(inf.tenis, idioma), pdf.generar(inf.tenis, idioma)
    return pdf.nombre_informe(inf, idioma), pdf.generar_informe(inf, idioma)


def _drive_alto_rendimiento(inf, idioma):
    """Alto rendimiento va a la carpeta del jugador, como antes, pero solo
    una vez validado."""
    from . import drive

    if inf.estado != Informe.Estado.VALIDADO or not drive.configurado():
        return None
    ev = inf.tenis
    try:
        ev.drive_file_id, ev.drive_url = drive.subir(ev, idioma)
        ev.save(update_fields=["drive_file_id", "drive_url", "actualizada"])
        inf.drive_file_id, inf.drive_url, inf.drive_carpeta = ev.drive_file_id, ev.drive_url, "validados"
        inf.save(update_fields=["drive_file_id", "drive_url", "drive_carpeta", "actualizado"])
    except drive.DriveNoDisponible as e:
        return f"{e} El informe está en la app; se reintenta al validar."
    return None


def guardar_en_drive(inf):
    """Genera el PDF conjunto y lo deja en la carpeta que toca según el
    estado. Devuelve un aviso si Drive o la traducción fallan (el informe
    sigue en la app)."""
    from . import drive, ia, traduccion

    if inf.circuito == "alto_rendimiento":
        idioma = idioma_pdf(inf)
        try:
            if idioma != "ES":
                traduccion.tenis(inf.tenis, idioma)
        except ia.IANoDisponible:
            idioma = "ES"
        return _drive_alto_rendimiento(inf, idioma)
    if not (drive.configurado() or drive.ct_configurado()):
        return None
    idioma, aviso = idioma_pdf(inf), None
    if idioma != "ES":
        try:
            traduccion.tenis(inf.tenis, idioma)
            if inf.fisica:
                traduccion.fisica(inf.fisica, idioma)
        except ia.IANoDisponible as e:
            idioma, aviso = "ES", f"No se ha podido traducir el PDF ({e}): en Drive queda en español. Pulsa «Guardar en Drive» para reintentarlo."
    try:
        drive.subir_informe(inf, idioma)
        inf.save(update_fields=["drive_file_id", "drive_url", "drive_carpeta", "actualizado"])
    except drive.DriveNoDisponible as e:
        return f"{e} El informe está en la app; se reintenta al validar."
    return aviso


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
        inf.save(update_fields=["actualizado"])
        guardar_en_drive(inf)
        return inf
    corregido = inf.estado == Informe.Estado.VALIDADO
    if corregido:
        inf.version += 1
    inf.estado = Informe.Estado.PENDIENTE
    inf.devuelto_partes = []
    inf.save()
    guardar_en_drive(inf)
    nombre = inf.jugador.nombre
    # Tardes: se avisa a quien coordina (decisión 11). Alto rendimiento no tiene
    # coordinador: a quien valida.
    if inf.circuito == "alto_rendimiento":
        quienes, partes = usuarios_valida_informes(), "La evaluación de tenis está terminada."
    else:
        quienes, partes = usuarios_avisar_validar(), "Tenis y preparación física están terminados."
    _avisar(quienes,
            f"Informe de {nombre} {'corregido, ' if corregido else ''}listo para validar",
            f"{partes} Revísalo en Rendimiento → Informes y apruébalo o devuélvelo con una nota.")
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
            "Ya está validado y en la carpeta «Validados» de Drive. El siguiente toca en unos 90 días.")
    return aviso_drive


def reabrir(inf, usuario):
    """Para corregir un informe ya aprobado, primero se reabre (10/11/2026):
    vuelve a «a medias» con una versión nueva y, al terminar otra vez la parte
    corregida, pasa de nuevo a validar. Hasta entonces nadie puede cambiarlo."""
    if inf.estado != Informe.Estado.VALIDADO:
        raise InformeError("Solo se reabren informes ya aprobados.")
    inf.estado = Informe.Estado.EN_CURSO
    inf.version += 1
    inf.validado_por = None
    inf.validado_en = None
    inf.save()
    return inf


def correo_configurado():
    from django.conf import settings

    return bool(getattr(settings, "EMAIL_HOST", "")) or settings.EMAIL_BACKEND.endswith("console.EmailBackend")


def enviar(inf, usuario):
    """Envía el informe aprobado a la familia por correo, con el PDF en su
    idioma (10/11/2026, decisión 13). Deja constancia de cuándo y quién."""
    from django.conf import settings
    from django.core.mail import EmailMessage

    from .correo import correo

    if inf.estado != Informe.Estado.VALIDADO:
        raise InformeError("Solo se envían informes aprobados.")
    para = [d["email"] for d in inf.destinatarios or [] if d.get("email")]
    if not para:
        raise InformeError("Este informe no tiene a quién enviarse: añade el correo de la familia.")
    if not correo_configurado():
        raise InformeError("El envío por correo aún no está configurado en el servidor.")
    idioma = idioma_pdf(inf)
    try:
        nombre_pdf, contenido = pdf_de(inf, idioma)
        asunto, texto = correo(inf.jugador.nombre, idioma)
        mensaje = EmailMessage(asunto, texto, settings.DEFAULT_FROM_EMAIL, para)
        mensaje.attach(nombre_pdf, contenido, "application/pdf")
        mensaje.send(fail_silently=False)
    except Exception as e:  # noqa: BLE001 — se guarda el motivo y se dice
        inf.envio_error = str(e)[:300]
        inf.save(update_fields=["envio_error", "actualizado"])
        raise InformeError(f"No se ha podido enviar: {e}")
    inf.enviado_en = timezone.now()
    inf.enviado_por = usuario
    inf.envio_error = ""
    inf.save(update_fields=["enviado_en", "enviado_por", "envio_error", "actualizado"])
    return inf


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


def _usuarios(*q, **filtro):
    from django.contrib.auth import get_user_model

    return list(get_user_model().objects.filter(*q, is_active=True, **filtro).select_related("entrenador")
                .distinct().order_by("first_name", "username"))


def evaluadores_tenis_por_defecto():
    """Los entrenadores de tenis de Competición de tardes (el equipo y el
    coordinador): entre ellos reparte el coordinador."""
    from django.db.models import Q

    return _usuarios(Q(tardes__funcion=MiembroTardes.Funcion.TENIS) | Q(funciones__codigo=COORDINA_TARDES))


def coordinadores():
    return _usuarios(funciones__codigo=COORDINA_TARDES)


def preparadores():
    """Quien hace la física de Competición de tardes; sin él, todos los preparadores."""
    return _usuarios(tardes__funcion=MiembroTardes.Funcion.FISICO) or _usuarios(role="PREPARADOR")


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
                f"en «Asignados a mí».")
    return nuevos
