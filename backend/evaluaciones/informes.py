"""El circuito del informe de Competición de tardes (27/10/2026) y, desde el
10/11/2026, también de Alto rendimiento (lo valida dirección y el head coach de
su color). Desde el 17/11/2026 el de Alto rendimiento puede llevar además la
parte física (opcional: manda el tenis).

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
from academy.permissions import (
    COORDINA_TARDES, FISICO_AR, es_coach, es_direccion, usuarios_avisar_validar, usuarios_direccion,
    valida_informes,
)

from .models import AsignacionFisica, AsignacionInforme, Evaluacion, EvaluacionFisica, Informe, MiembroTardes

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


def informe_abierto(jugador, crear=True):
    """El informe en curso del jugador (no validado). Si no hay y `crear`, uno nuevo."""
    inf = jugador.informes.exclude(estado=Informe.Estado.VALIDADO).order_by("-creado").first()
    if inf is None and crear:
        inf = Informe.objects.create(jugador=jugador)
    return inf


def validado_sin_fisica(jugador):
    """El informe ya validado al que todavía se le puede sumar la física que
    llega tarde (24/11/2026): el último validado del jugador, sin parte física,
    sin enviar a la familia y de este trimestre (validado hace menos de 75
    días). Si no, la física es para el informe siguiente."""
    ult = ultimo_validado(jugador)
    if ult is None or ult.fisica_id or ult.enviado_en:
        return None
    if (timezone.now() - ult.validado_en).days >= CICLO_PRONTO:
        return None
    return ult


def _reabrir_para_fisica(inf, ev):
    """Vuelve a abrir el informe validado para sumarle la física (24/11/2026).
    Como al reabrirlo para corregir: versión nueva y, al terminar la física,
    otra vez a validar con el PDF completo. Si estaba programado para salir,
    deja de estarlo; se avisa a quien lo aprobó y a quien lo programó."""
    avisar = [inf.validado_por, inf.envio_programado_por if inf.envio_programado else None]
    reabrir(inf, None)
    _avisar(avisar, f"Informe de {inf.jugador.nombre}: se le suma la parte física",
            f"{ev.nombre_evaluador or 'El preparador'} está haciendo la preparación física de este informe, que "
            f"ya estaba aprobado y aún no se había enviado a la familia. Cuando la termine, vuelve a validar "
            f"con el PDF completo{' (se ha cancelado el envío programado)' if avisar[1] else ''}.")


def vincular(ev):
    """Cuelga una evaluación recién creada (de tenis o física) del informe
    abierto de su jugador. Si ese informe ya tiene esa parte, no deja crear
    otra: hay que seguir con la que hay.

    Desde el 10/11/2026 también Alto rendimiento (decisión 12): su informe pasa
    por la misma validación y lo manda la parte de tenis. Desde el 17/11/2026
    la parte física también se cuelga del informe de Alto rendimiento (se suma
    al PDF, sin hacer falta para validarlo). Desde el 24/11/2026, la física que
    llega cuando el tenis ya está validado se suma a ese informe si aún no ha
    salido hacia la familia (antes abría el del trimestre siguiente)."""
    campo = "tenis" if isinstance(ev, Evaluacion) else "fisica"
    with transaction.atomic():
        inf = informe_abierto(ev.jugador, crear=False)
        if inf is None and campo == "fisica":
            inf = validado_sin_fisica(ev.jugador)
            if inf is not None:
                _reabrir_para_fisica(inf, ev)
        if inf is None:
            inf = Informe.objects.create(jugador=ev.jugador)
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
    """(nombre, contenido) del PDF del informe. Tardes lleva tenis y físico;
    Alto rendimiento, el tenis y la página física si ya está terminada, con
    la misma maqueta (foto subida y evolución respecto al último validado)."""
    from . import pdf

    return pdf.nombre_informe(inf, idioma), pdf.generar_informe(inf, idioma)


def puede_validar(user, inf):
    """Quién aprueba, devuelve o reabre este informe. Alto rendimiento
    (12/11/2026): dirección y el head coach de su color. Tardes: quien tiene
    «Valida informes»."""
    if inf.circuito == "alto_rendimiento":
        if es_direccion(user):
            return True
        if not es_coach(user):
            return False
        from academy.models import Jugador
        from academy.scope import jugadores_que_evalua

        return jugadores_que_evalua(user, base=Jugador.objects.all()).filter(pk=inf.jugador_id).exists()
    return valida_informes(user)


def puede_enviar(user, inf):
    """Quién envía este informe a la familia (o programa o cancela su envío):
    dirección, Administración y quien tenga «Envía informes», todos; el head
    coach, desde el 25/11/2026, los de Alto rendimiento que valida (los de su
    color)."""
    from academy.permissions import envia_informes

    if envia_informes(user):
        return True
    return inf.circuito == "alto_rendimiento" and es_coach(user) and puede_validar(user, inf)


def head_coaches_de(jugador):
    """Los head coaches del color del jugador: los de los bloques donde está
    quien le gestiona."""
    from academy.models import Coach

    gestores = [jugador.entrenador_responsable_id, *jugador.cogestores.values_list("pk", flat=True)]
    coaches = (Coach.objects.filter(activo=True, entrenadores__in=[g for g in gestores if g],
                                    user__isnull=False, user__is_active=True)
               .select_related("user").distinct())
    return [c.user for c in coaches]


def usuarios_validan(inf):
    """A quién se avisa de que este informe está listo para validar."""
    if inf.circuito == "alto_rendimiento":
        return usuarios_direccion() + head_coaches_de(inf.jugador)
    return usuarios_avisar_validar()


def guardar_en_drive(inf):
    """Genera el PDF del informe y lo deja en la carpeta que toca según el
    estado y el circuito. Devuelve un aviso si Drive o la traducción fallan
    (el informe sigue en la app)."""
    from . import drive, ia, traduccion

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
    # Si la familia lo recibe en otro idioma, en Drive queda también el de
    # quien lo ha hecho, en español (17/11/2026); si ya no hace falta, se quita.
    try:
        if idioma != "ES":
            drive.subir_informe(inf, "ES", copia_es=True)
        elif inf.drive_file_id_es:
            drive.a_la_papelera(inf.drive_file_id_es)
            inf.drive_file_id_es, inf.drive_url_es = "", ""
        inf.save(update_fields=["drive_file_id_es", "drive_url_es", "actualizado"])
    except drive.DriveNoDisponible as e:
        aviso = " ".join(filter(None, [aviso, f"{e} La copia en español no se ha guardado; pulsa «Guardar en Drive» para reintentarlo."]))
    return aviso


def tras_borrar_parte(inf, fisica=False):
    """Después de borrar una evaluación: si su informe se ha quedado sin
    ninguna parte, se borra también, y su PDF va a la papelera de Drive
    (12/11/2026: se borran los de prueba para empezar del 1 al 10). Si se
    borra la física de un informe de Alto rendimiento que se había reabierto
    para sumársela (24/11/2026), el tenis ya terminado vuelve a validar."""
    from . import drive

    if inf is None:
        return
    inf = Informe.objects.filter(pk=inf.pk).first()
    if inf is None:
        return
    if (fisica and inf.tenis_id and inf.estado == Informe.Estado.EN_CURSO
            and inf.circuito == "alto_rendimiento" and inf.completo):
        parte_terminada(inf.tenis)
        return
    if inf.tenis_id or inf.fisica_id:
        return
    drive.a_la_papelera(inf.drive_file_id)
    inf.delete()


def parte_terminada(ev):
    """Se llama al terminar (o volver a terminar) una parte. Si con ella el
    informe queda completo, pasa a pendiente de validar."""
    inf = getattr(ev, "informe", None)
    if inf is None and isinstance(ev, Evaluacion) and parte_existente(ev.jugador, "tenis") is None:
        # Una de Alto rendimiento empezada antes de que entrara en el circuito
        # (10/11/2026): al terminarla se cuelga de su informe como las nuevas.
        inf = vincular(ev)
    if inf is None:
        return None
    inf.refresh_from_db()
    if not inf.completo:
        return inf
    fisica_de_ar = isinstance(ev, EvaluacionFisica) and inf.circuito == "alto_rendimiento"
    if fisica_de_ar and inf.estado == Informe.Estado.DEVUELTO and "fisico" not in inf.devuelto_partes:
        # La física no era lo devuelto: no se da por corregido el tenis.
        return inf
    if inf.estado == Informe.Estado.PENDIENTE:
        # Ya estaba pendiente y se ha retocado: se rehace el PDF, sin avisar otra vez.
        inf.save(update_fields=["actualizado"])
        guardar_en_drive(inf)
        if fisica_de_ar:
            # Alto rendimiento: la física llega después del tenis; quien valida
            # tiene que saber que el PDF ya la lleva.
            _avisar(usuarios_validan(inf), f"Informe de {inf.jugador.nombre}: parte física terminada",
                    f"{inf.fisica.nombre_evaluador} ha terminado la preparación física. "
                    f"Ya está en el PDF del informe, que sigue pendiente de validar.")
        return inf
    corregido = inf.estado == Informe.Estado.VALIDADO
    if corregido:
        inf.version += 1
    inf.estado = Informe.Estado.PENDIENTE
    inf.devuelto_partes = []
    inf.save()
    guardar_en_drive(inf)
    nombre = inf.jugador.nombre
    # Tardes: se avisa a quien coordina (decisión 11). Alto rendimiento, a
    # dirección, que es quien lo valida (12/11/2026).
    if fisica_de_ar:
        # La física que se suma a un informe reabierto para ella (24/11/2026).
        partes = (f"{inf.fisica.nombre_evaluador} ha terminado la preparación física; el tenis "
                  f"({inf.tenis.nombre_evaluador}) ya estaba. El PDF ya lleva las dos partes.")
    elif inf.circuito == "alto_rendimiento":
        partes = f"{inf.tenis.nombre_evaluador} ha terminado la evaluación de tenis."
    else:
        partes = "Tenis y preparación física están terminados."
    _avisar(usuarios_validan(inf),
            f"Informe de {nombre} {'corregido, ' if corregido else ''}listo para validar",
            f"{partes} Revísalo en Rendimiento → Informes y apruébalo o devuélvelo con una nota.")
    return inf


def aprobar(inf, usuario, destinatarios):
    if inf.estado != Informe.Estado.PENDIENTE:
        raise InformeError("Solo se aprueban informes pendientes de validar.")
    if inf.circuito == "alto_rendimiento" and inf.fisica and inf.fisica.estado != EvaluacionFisica.Estado.TERMINADA:
        # En Alto rendimiento la física es opcional, pero si se ha empezado no
        # se deja a medias en un informe aprobado (que ya no se toca).
        raise InformeError("La parte física está empezada y sin terminar: que se termine antes de aprobar el "
                           "informe (o se borra, si no va a llevarla).")
    inf.estado = Informe.Estado.VALIDADO
    inf.validado_por = usuario
    inf.validado_en = timezone.now()
    inf.destinatarios = destinatarios
    inf.save()
    guardar_correos_en_ficha(inf.jugador, destinatarios)
    aviso_drive = guardar_en_drive(inf)
    _avisar(autores(inf), f"Informe de {inf.jugador.nombre} validado",
            "Ya está validado y en la carpeta «Validados» de Drive. El siguiente toca en unos 90 días.")
    return aviso_drive


def guardar_correos_en_ficha(jugador, destinatarios):
    """Los correos que quien aprueba escribe a mano se quedan en la ficha del
    jugador (24/11/2026), para que el siguiente informe ya los proponga. Solo
    rellena lo que estaba vacío (primer correo, luego el segundo): nunca cambia
    ni quita uno que ya hubiera. Devuelve cuántos ha guardado."""
    from django.core.exceptions import ValidationError as ErrorDjango
    from django.core.validators import validate_email

    from .models import DatosInforme

    datos = DatosInforme.objects.filter(jugador=jugador).first()
    ya = {e.lower() for e in (jugador.email, datos.email_2 if datos else "") if e}
    guardados = 0
    for d in destinatarios or []:
        email = str(d.get("email", "")).strip()
        quien = str(d.get("quien", "")).strip()
        quien = "" if quien.lower() == "familia" else quien[:40]
        if not email or email.lower() in ya:
            continue
        try:
            validate_email(email)
        except ErrorDjango:
            continue
        if not jugador.email:
            jugador.email = email
            jugador.save(update_fields=["email"])
            if datos is not None and quien and not datos.quien_1:
                datos.quien_1 = quien
                datos.save(update_fields=["quien_1"])
        elif datos is None or not datos.email_2:
            if datos is None:
                datos = DatosInforme.objects.create(jugador=jugador, idioma=idioma_familia(jugador))
            datos.email_2, datos.quien_2 = email, quien
            datos.save(update_fields=["email_2", "quien_2"])
        else:
            break
        ya.add(email.lower())
        guardados += 1
    return guardados


def usuarios_envian():
    """Quien envía los informes a las familias: dirección, Administración y
    quien tenga la función «Envía informes»."""
    from django.db.models import Q

    from academy.permissions import ENVIA_INFORMES

    return _usuarios(Q(role="SUPERADMIN") | Q(is_superuser=True) | Q(role="ADMINISTRACION")
                     | Q(funciones__codigo=ENVIA_INFORMES))


def avisar_para_enviar(inf, usuario):
    """Si lo aprueba quien no puede enviarlo (el coordinador de tardes), se
    avisa a quien envía de que hay uno listo (24/11/2026): antes se quedaba en
    «Validados» sin que nadie lo supiera. El head coach envía los suyos desde
    el 25/11/2026, así que al aprobar no avisa a nadie."""
    if puede_enviar(usuario, inf):
        return
    quien = usuario.get_full_name() or usuario.username
    falta = ("" if inf.destinatarios else
             " Ojo: no tiene correo de la familia, así que aún no se puede enviar.")
    _avisar([u for u in usuarios_envian() if u.pk != usuario.pk],
            f"Informe de {inf.jugador.nombre} aprobado: listo para enviar",
            f"Lo ha aprobado {quien}. Envíalo a la familia desde Rendimiento → Informes, en «Por enviar» "
            f"(ahora o mañana a las 8:30).{falta}")


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
    inf.envio_programado = None
    inf.envio_programado_por = None
    inf.save()
    return inf


def correo_configurado():
    from django.conf import settings

    from . import gmail

    return (gmail.configurado() or bool(getattr(settings, "EMAIL_HOST", ""))
            or settings.EMAIL_BACKEND.endswith("console.EmailBackend"))


def _correo_de_la_cuenta():
    """La dirección que envía (gestion@), sin el nombre que la acompaña."""
    from email.utils import parseaddr

    from django.conf import settings

    return getattr(settings, "CORREO_GMAIL", "") or parseaddr(settings.DEFAULT_FROM_EMAIL)[1]


def head_coaches(inf):
    """Quién atiende a la familia si responde (19/11/2026): en tardes, quien
    coordina Competición de tardes; en Alto rendimiento, el head coach del
    color de su entrenador responsable."""
    from academy.scope import coaches_del_entrenador

    if inf.circuito == "alto_rendimiento":
        return [u for u in coaches_del_entrenador(inf.jugador.entrenador_responsable) if u.is_active]
    return coordinadores()


def responder_a(inf):
    """Las respuestas de la familia, a gestion@ y a su head coach (lo pidió
    Sergio el 20/10; 19/11/2026). Solo los que tienen correo en Club ›
    Personas y funciones."""
    lista = [_correo_de_la_cuenta()] + [u.email for u in head_coaches(inf) if u.email]
    vistos, out = set(), []
    for e in lista:
        if e and e.lower() not in vistos:
            vistos.add(e.lower())
            out.append(e)
    return out


def _listo_para_enviar(inf):
    if inf.estado != Informe.Estado.VALIDADO:
        raise InformeError("Solo se envían informes aprobados.")
    para = [d["email"] for d in inf.destinatarios or [] if d.get("email")]
    if not para:
        raise InformeError("Este informe no tiene a quién enviarse: añade el correo de la familia.")
    if not correo_configurado():
        raise InformeError("El envío por correo aún no está configurado en el servidor.")
    return para


def enviar(inf, usuario):
    """Envía el informe aprobado a la familia por correo, con el PDF en su
    idioma (10/11/2026, decisión 13). Deja constancia de cuándo y quién."""
    from django.conf import settings
    from django.core.mail import EmailMessage

    from .correo import correo

    para = _listo_para_enviar(inf)
    idioma = idioma_pdf(inf)
    con_fisica = bool(inf.fisica_id and inf.fisica.estado == EvaluacionFisica.Estado.TERMINADA)
    try:
        nombre_pdf, contenido = pdf_de(inf, idioma)
        asunto, texto = correo(inf.jugador.nombre, idioma, inf.circuito, con_fisica)
        mensaje = EmailMessage(asunto, texto, settings.DEFAULT_FROM_EMAIL, para, reply_to=responder_a(inf))
        mensaje.attach(nombre_pdf, contenido, "application/pdf")
        mensaje.send(fail_silently=False)
    except Exception as e:  # noqa: BLE001 — se guarda el motivo y se dice
        inf.envio_error = str(e)[:300]
        inf.save(update_fields=["envio_error", "actualizado"])
        raise InformeError(f"No se ha podido enviar: {e}")
    inf.enviado_en = timezone.now()
    inf.enviado_por = usuario
    inf.envio_error = ""
    inf.envio_programado = None
    inf.envio_programado_por = None
    inf.save(update_fields=["enviado_en", "enviado_por", "envio_error", "envio_programado",
                            "envio_programado_por", "actualizado"])
    return inf


HORA_ENVIO = (8, 30)  # 19/11/2026: lo programado sale a las 8:30 de la mañana siguiente


def proxima_salida(ahora=None):
    from datetime import datetime, time

    ahora = timezone.localtime(ahora or timezone.now())
    dia = ahora.date() + timedelta(days=1)
    return timezone.make_aware(datetime.combine(dia, time(*HORA_ENVIO)))


def programar(inf, usuario, cuando=None):
    """Deja el informe para que salga solo a las 8:30 de mañana (o a `cuando`)."""
    _listo_para_enviar(inf)
    inf.envio_programado = cuando or proxima_salida()
    inf.envio_programado_por = usuario
    inf.envio_error = ""
    inf.save(update_fields=["envio_programado", "envio_programado_por", "envio_error", "actualizado"])
    return inf


def cancelar_envio(inf):
    inf.envio_programado = None
    inf.envio_programado_por = None
    inf.save(update_fields=["envio_programado", "envio_programado_por", "actualizado"])
    return inf


def enviar_programados(ahora=None):
    """Lo llama el programador cada minuto: manda los que ya tocan. Si uno
    falla, no se reintenta solo: queda el motivo y se avisa a quien lo programó."""
    ahora = ahora or timezone.now()
    enviados = 0
    for inf in (Informe.objects.filter(estado=Informe.Estado.VALIDADO, envio_programado__lte=ahora)
                .select_related("jugador", "envio_programado_por")):
        quien = inf.envio_programado_por
        try:
            enviar(inf, quien)
            enviados += 1
        except InformeError as e:
            inf.envio_programado = None
            inf.envio_programado_por = None
            inf.save(update_fields=["envio_programado", "envio_programado_por", "actualizado"])
            if quien is not None:
                _avisar([quien], f"No se ha enviado el informe de {inf.jugador.nombre}",
                        f"{e} Puedes volver a enviarlo desde Informes.")
    return enviados


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


def circuito_de(jugador):
    """«tardes» (escuela solo informes) o «alto_rendimiento»."""
    return "tardes" if jugador.escuela_id and jugador.escuela.solo_informes else "alto_rendimiento"


def evaluadores_fisico(circuito):
    """Entre quiénes se reparte la parte física (19/11/2026): en tardes, el
    equipo de física de tardes; en Alto rendimiento, quien tenga marcada
    «Evalúa física de Alto rendimiento». Sin nadie marcado, los preparadores."""
    if circuito == "tardes":
        return preparadores()
    return _usuarios(funciones__codigo=FISICO_AR) or _usuarios(role="PREPARADOR")


def _asignar(Modelo, jugadores, evaluador, por):
    """Da (o quita, con `evaluador=None`) esos jugadores a `evaluador`.
    Devuelve los nombres de los que le llegan nuevos."""
    nuevos = []
    for j in jugadores:
        if evaluador is None:
            Modelo.objects.filter(jugador=j).delete()
            continue
        a, creada = Modelo.objects.get_or_create(jugador=j, defaults={"evaluador": evaluador, "asignado_por": por})
        if not creada and a.evaluador_id != evaluador.pk:
            a.evaluador, a.asignado_por = evaluador, por
            a.save()
            creada = True
        if creada:
            nuevos.append(j.nombre)
    return nuevos


def _lista(nombres, maximo=40):
    return ", ".join(nombres[:maximo]) + (f" y {len(nombres) - maximo} más" if len(nombres) > maximo else "")


def asignar(jugadores, evaluador, por):
    """El coordinador da (o quita, con `evaluador=None`) los informes de tenis
    de esos jugadores a un entrenador, que recibe un aviso con los nuevos."""
    nuevos = _asignar(AsignacionInforme, jugadores, evaluador, por)
    if nuevos and evaluador.pk != por.pk:
        n = len(nuevos)
        _avisar([evaluador], f"Te han asignado {n} jugador{'es' if n != 1 else ''} para los informes",
                f"Te toca hacer el informe de tenis de: {', '.join(nuevos)}. Los tienes en Informes, "
                f"en «Asignados a mí».")
    return nuevos


def asignar_fisico(jugadores, evaluador, por):
    """Quien coordina la preparación física da (o quita) la parte física de
    esos jugadores a un preparador, que recibe un aviso con los nuevos."""
    nuevos = _asignar(AsignacionFisica, jugadores, evaluador, por)
    if nuevos and evaluador.pk != por.pk:
        n = len(nuevos)
        _avisar([evaluador], f"Te han asignado {n} jugador{'es' if n != 1 else ''} para la evaluación física",
                f"Te toca la parte física del informe de: {_lista(nuevos)}. Los tienes en Evaluaciones "
                f"físicas › Jugadores, en «Asignados a mí».")
    return nuevos
