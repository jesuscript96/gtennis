"""El correo del día 1 a las familias con sus torneos (25/11/2026).

Cada mes, el día 1, se prepara un correo por jugador que tenga torneos ese mes
o el siguiente: los torneos (confirmados y por confirmar, cada uno marcado),
con la fecha de cierre de inscripción destacada si aún no ha pasado, y al
final las normas de torneos de G Tenis. Sale cuando lo valida su head coach o
dirección; hasta entonces se enseña con los datos del momento, y al validarlo
se guarda tal cual y eso es lo que se envía (el programador lo manda en el
minuto siguiente, con el PDF del jugador adjunto).

Destinatarios e idioma, los mismos que los informes: el correo de la ficha y
el segundo de «Datos de la familia»; si la familia es de inglés, en inglés.
Las respuestas van a gestion@ y a su head coach.
"""
import logging
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from django.db.models import Q

from academy.models import Aviso, Jugador
from academy.permissions import es_coach, es_direccion

from . import circuito, pdf
from .models import CorreoTorneos, NormasTorneos, Participante, Torneo
from .por_jugador import _fecha, ficha, resumen, torneos_de

log = logging.getLogger(__name__)

PLANTILLA = pdf.PLANTILLA.parent / "correo.html"
HORA_GENERAR = 8  # el día 1, a partir de las 8:00


class CorreoError(Exception):
    """Algo que el usuario tiene que saber (se devuelve como 400)."""


def primero_de_mes(d):
    return d.replace(day=1)


def mes_siguiente(d):
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def fin_del_tramo(mes):
    """Último día del mes siguiente a `mes`: el correo cubre los dos."""
    return mes_siguiente(mes_siguiente(mes)) - timedelta(days=1)


def _desde(mes):
    """El día 1 es el propio mes; si se prepara o valida más tarde, desde hoy:
    a la familia no se le cuentan torneos que ya han terminado."""
    return max(mes, timezone.localdate())


def _torneos(jugador, mes):
    return torneos_de(jugador, desde=_desde(mes), hasta=fin_del_tramo(mes))


def jugadores_con_torneos(mes):
    """Los que tienen algún torneo ese mes o el siguiente y siguen entrenando."""
    fin = fin_del_tramo(mes)
    ids = (Participante.objects.filter(jugador__isnull=False, torneo__fecha_fin__gte=_desde(mes))
           .exclude(torneo__estado=Torneo.Estado.CANCELADO)
           .values_list("jugador_id", "torneo__fecha_inicio", "torneo__qualy_inicio"))
    con = {j for j, ini, q in ids if min(d for d in (ini, q) if d) <= fin}
    # Los de Competición de tardes tienen la ficha inactiva, pero juegan torneos.
    return (Jugador.objects.filter(Q(activo=True) | Q(escuela__solo_informes=True), pk__in=con)
            .exclude(fecha_baja__lt=_desde(mes)).order_by("nombre"))


# ---------------------------------------------------------------- quién valida

def puede_validar(user, correo):
    """Su head coach (el de su grupo en torneos; en Competición de tardes,
    quien la coordina) o dirección."""
    from .views import es_de_mi_grupo

    if es_direccion(user):
        return True
    return circuito.hace_de_head_coach(user) and es_de_mi_grupo(user, correo.jugador)


def visibles(user):
    """Los correos que ve cada uno: dirección todos; el head coach (y quien
    coordina tardes), los de su grupo."""
    from .views import _q_de_mi_grupo

    qs = CorreoTorneos.objects.select_related("jugador", "validado_por__entrenador")
    if es_direccion(user):
        return qs
    if not circuito.hace_de_head_coach(user):
        return qs.none()
    q = _q_de_mi_grupo(user)
    return qs if q is None else qs.filter(jugador__in=Jugador.objects.filter(q))


def head_coaches(jugador):
    """Quién atiende a la familia si responde: su head coach; en Competición
    de tardes, quien la coordina (como en los informes)."""
    from academy.scope import coaches_del_entrenador

    from .serializers import es_de_tardes

    if es_de_tardes(jugador):
        from evaluaciones.informes import coordinadores

        return [u for u in coordinadores() if u.is_active]
    return [u for u in coaches_del_entrenador(jugador.entrenador_responsable) if u.is_active]


# ---------------------------------------------------------------- contenido

def idioma_de(jugador):
    from evaluaciones.informes import idioma_familia

    return idioma_familia(jugador)


def destinatarios_de(jugador):
    from evaluaciones.informes import destinatarios_propuestos

    return destinatarios_propuestos(jugador)


def normas(idioma):
    n = NormasTorneos.actuales()
    return (n.texto_en if idioma == "EN" and n.texto_en.strip() else n.texto) or ""


def contenido(correo):
    """Lo que dice el correo: lo guardado si ya está validado; si no, los
    datos de ahora mismo."""
    if correo.estado != CorreoTorneos.Estado.PENDIENTE and correo.contenido:
        return correo.contenido
    idioma = idioma_de(correo.jugador)
    return {
        "idioma": idioma, "jugador": ficha(correo.jugador), "mes": correo.mes.isoformat(),
        "torneos": _torneos(correo.jugador, correo.mes), "normas": normas(idioma),
    }


ASUNTO = {
    "ES": "Torneos de {m1} y {m2} · {nombre} · G Tenis",
    "EN": "{nombre}'s tournaments in {m1} and {m2} · G Tenis",
}
TEXTOS = {
    "ES": {
        "hola": "Hola:",
        "intro": "Estos son los torneos de {m1} y {m2} a los que está apuntado {nombre}.",
        "intro_pend": "Los marcados «Por confirmar» aún los está revisando el club; os avisaremos si cambia algo.",
        "inscripcion": "Fijaos en la fecha de inscripción de cada torneo: las que siguen abiertas van destacadas.",
        "adjunto": "Os adjuntamos también el calendario en PDF.",
        "dudas": "Si tenéis cualquier duda, responded a este correo: le llegará a su head coach y a la dirección deportiva.",
        "firma": "Un saludo,\nDirección deportiva · G Tenis",
        "lugar": "Lugar", "fechas": "Fechas", "acompana": "Acompaña",
    },
    "EN": {
        "hola": "Hello,",
        "intro": "These are the tournaments in {m1} and {m2} that {nombre} is entered in.",
        "intro_pend": "Those marked “To be confirmed” are still being reviewed by the club; we will let you know if anything changes.",
        "inscripcion": "Please check the entry deadlines: the ones still open are highlighted.",
        "adjunto": "The calendar is also attached as a PDF.",
        "dudas": "If you have any questions, just reply to this email: it will reach their head coach and our sports management team.",
        "firma": "Kind regards,\nSports management · G Tenis",
        "lugar": "Venue", "fechas": "Dates", "acompana": "Coach travelling",
    },
}


def _meses(mes, idioma):
    m = pdf.MESES[idioma]
    return m[mes.month - 1], m[mes_siguiente(mes).month - 1]


def mensaje(correo):
    """(asunto, texto, html) del correo, sin enviarlo. El PDF va aparte (`pdf_de`)."""
    c = contenido(correo)
    idioma = c.get("idioma") or "ES"
    mes = _fecha(c["mes"])
    m1, m2 = _meses(mes, idioma)
    nombre = c["jugador"]["nombre"]
    tx = TEXTOS[idioma]
    t = pdf.textos(idioma)
    r = resumen(c["torneos"])
    asunto = ASUNTO[idioma].format(m1=m1, m2=m2, nombre=nombre)
    hoy = date.today()
    filas = []
    for f in c["torneos"]:
        cierre = pdf._cierre(f, t, idioma, hoy)
        filas.append({
            "nombre": f["nombre"], "lugar": f.get("lugar") or "", "circuito": f.get("circuito") or "",
            "fechas": pdf.rango(f["fecha_inicio"], f["fecha_fin"], idioma),
            "previa": (f'{t["previa"]}: {pdf.rango(f["qualy_inicio"], f.get("qualy_fin") or f["qualy_inicio"], idioma)}'
                       if f.get("qualy_inicio") else ""),
            "acompana": ", ".join(f.get("acompanantes") or []) or f.get("acompanante_nota") or "",
            "confirmado": f["confirmado"], "cierre": cierre,
            "borrado": (f'{t["borrado"]} {pdf.fecha_corta(f["fecha_borrado"], idioma)}'
                        if f.get("fecha_borrado") and _fecha(f["fecha_borrado"]) >= hoy else ""),
        })
    datos = {
        "tx": tx, "t": t, "asunto": asunto, "torneos": filas,
        "intro": tx["intro"].format(m1=m1, m2=m2, nombre=nombre),
        "hay_pendientes": r["por_confirmar"] > 0, "hay_abiertas": r["inscripciones_abiertas"] > 0,
        "normas": pdf.normas_en_parrafos(c.get("normas") or ""), "firma": tx["firma"].split("\n"),
    }
    html = pdf.pintar(PLANTILLA, datos)
    texto = _texto_plano(datos, tx, t)
    return asunto, texto, html


def _texto_plano(d, tx, t):
    lineas = [tx["hola"], "", d["intro"]]
    if d["hay_pendientes"]:
        lineas.append(tx["intro_pend"])
    lineas.append("")
    for f in d["torneos"]:
        estado = t["confirmado"] if f["confirmado"] else t["por_confirmar"]
        lineas.append(f"• {f['fechas']} · {f['nombre']} ({estado})")
        if f["lugar"]:
            lineas.append(f"  {tx['lugar']}: {f['lugar']}")
        if f["previa"]:
            lineas.append(f"  {f['previa']}")
        c = f["cierre"]
        lineas.append(f"  {c['etq']}{(' ' + c['fecha']) if c['fecha'] else ''}"
                      f"{(' (' + c['quedan'] + ')') if c['quedan'] else ''}"
                      + ("  ◀" if c["clase"] == "abierta" else ""))
        if f["borrado"]:
            lineas.append(f"  {f['borrado']}")
        if f["acompana"]:
            lineas.append(f"  {tx['acompana']}: {f['acompana']}")
        lineas.append("")
    if d["normas"]:
        lineas += [t["normas"].upper(), ""]
        for b in d["normas"]:
            lineas += [f"- {i}" for i in b["lista"]] if "lista" in b else [b["texto"]]
        lineas.append("")
    lineas += [tx["adjunto"], tx["dudas"], "", *d["firma"]]
    return "\n".join(lineas)


def pdf_de(correo):
    """El calendario de esos dos meses en PDF, para adjuntar."""
    c = contenido(correo)
    idioma = c.get("idioma") or "ES"
    mes = _fecha(c["mes"])
    m1, m2 = _meses(mes, idioma)
    t = pdf.textos(idioma)
    jugador = c["jugador"]
    contenido_pdf = pdf.generar(jugador, c["torneos"], idioma=idioma,
                                subtitulo=t["meses_correo"].format(m1=m1, m2=m2),
                                normas=c.get("normas") or "", foto=pdf.foto_de(correo.jugador))
    return pdf.nombre_fichero(jugador["nombre"], f"{m1} {m2}" if idioma == "EN" else f"{m1} y {m2}"), contenido_pdf


def resumen_de(correo):
    """Para la lista: cuántos torneos, cuántos por confirmar, inscripciones abiertas."""
    return resumen(contenido(correo)["torneos"])


# ---------------------------------------------------------------- el circuito

def _avisar(usuarios, titulo, mensaje_):
    for u in {u.id: u for u in usuarios if u is not None}.values():
        Aviso.objects.create(usuario=u, tipo=Aviso.Tipo.GENERAL, titulo=titulo[:160], mensaje=mensaje_)


def generar(mes=None, usuario=None):
    """Prepara los correos de `mes` (el actual si no se dice) que falten. Se
    puede repetir: no duplica ni toca los que ya hay. Avisa a cada head coach
    de los de su grupo y a dirección. Devuelve cuántos ha creado."""
    from .views import es_de_mi_grupo

    mes = primero_de_mes(mes or timezone.localdate())
    ya = set(CorreoTorneos.objects.filter(mes=mes).values_list("jugador_id", flat=True))
    nuevos = [CorreoTorneos(jugador=j, mes=mes, idioma=idioma_de(j))
              for j in jugadores_con_torneos(mes) if j.id not in ya]
    CorreoTorneos.objects.bulk_create(nuevos)
    if nuevos:
        m1 = pdf.MESES["ES"][mes.month - 1]
        titulo = f"Correos de torneos de {m1}: {len(nuevos)} por validar"
        texto = ("Cada familia recibe sus torneos de este mes y del siguiente con las normas de torneos. "
                 "Salen en cuanto los valida su head coach o dirección: en Torneos › Correos a familias.")
        Aviso.objects.create(para_direccion=True, tipo=Aviso.Tipo.GENERAL, titulo=titulo, mensaje=texto)
        from academy.models import Coach

        from evaluaciones.informes import coordinadores

        quienes = [c.user for c in Coach.objects.filter(activo=True, user__isnull=False).select_related("user")
                   if es_coach(c.user)]
        # Quien coordina Competición de tardes, por los de tardes.
        quienes += [u for u in coordinadores() if u.is_active and circuito.hace_de_head_coach(u)]
        for u in {u.id: u for u in quienes}.values():
            n = sum(1 for x in nuevos if es_de_mi_grupo(u, x.jugador))
            if n:
                _avisar([u], f"Correos de torneos de {m1}: {n} de tu grupo por validar", texto)
    return len(nuevos)


def revisar(ahora=None):
    """Lo llama el programador: el día 1, desde las 8:00, prepara los del mes."""
    ahora = timezone.localtime(ahora or timezone.now())
    if ahora.day != 1 or ahora.hour < HORA_GENERAR:
        return 0
    return generar(ahora.date())


def validar(correo, usuario, destinatarios=None):
    """Lo deja listo para salir con lo que dice ahora mismo. `destinatarios`
    (lista de {email, quien}) sustituye a los de la ficha y se guarda en ella."""
    if correo.estado != CorreoTorneos.Estado.PENDIENTE:
        raise CorreoError(f"El correo de {correo.jugador.nombre} ya está {correo.get_estado_display().lower()}.")
    if not puede_validar(usuario, correo):
        raise CorreoError(f"{correo.jugador.nombre} no es de tu grupo: lo valida su head coach o dirección.")
    if destinatarios is not None:
        from django.core.exceptions import ValidationError as ErrorDjango
        from django.core.validators import validate_email

        from evaluaciones.informes import guardar_correos_en_ficha

        limpios = []
        for d in destinatarios:
            email = str(d.get("email") or "").strip()
            if not email:
                continue
            try:
                validate_email(email)
            except ErrorDjango:
                raise CorreoError(f"«{email}» no es un correo válido.")
            limpios.append({"email": email, "quien": str(d.get("quien") or "Familia").strip()[:40]})
        destinatarios = limpios

        guardar_correos_en_ficha(correo.jugador, destinatarios)
    else:
        destinatarios = destinatarios_de(correo.jugador)
    if not destinatarios:
        raise CorreoError(f"{correo.jugador.nombre} no tiene correo de la familia: añádelo antes de validar.")
    c = contenido(correo)
    if not c["torneos"]:
        raise CorreoError(f"{correo.jugador.nombre} ya no tiene torneos estos dos meses: márcalo como «No se envía».")
    correo.contenido = c
    correo.idioma = c["idioma"]
    correo.destinatarios = destinatarios
    correo.estado = CorreoTorneos.Estado.VALIDADO
    correo.validado_por = usuario
    correo.validado_en = timezone.now()
    correo.envio_error = ""
    correo.save()
    return correo


def descartar(correo, usuario):
    if correo.estado not in (CorreoTorneos.Estado.PENDIENTE, CorreoTorneos.Estado.VALIDADO):
        raise CorreoError("Ese correo ya ha salido.")
    if not puede_validar(usuario, correo):
        raise CorreoError(f"{correo.jugador.nombre} no es de tu grupo.")
    correo.estado = CorreoTorneos.Estado.DESCARTADO
    correo.validado_por, correo.validado_en = usuario, timezone.now()
    correo.save(update_fields=["estado", "validado_por", "validado_en"])
    return correo


def recuperar(correo, usuario):
    """Vuelve a «Por validar» uno descartado, o uno validado que no ha salido
    (por ejemplo, porque falló el envío)."""
    if correo.estado == CorreoTorneos.Estado.ENVIADO:
        raise CorreoError("Ese correo ya ha salido.")
    if not puede_validar(usuario, correo):
        raise CorreoError(f"{correo.jugador.nombre} no es de tu grupo.")
    correo.estado = CorreoTorneos.Estado.PENDIENTE
    correo.contenido = {}
    correo.validado_por, correo.validado_en = None, None
    correo.envio_error = ""
    correo.save(update_fields=["estado", "contenido", "validado_por", "validado_en", "envio_error"])
    return correo


def reintentar(correo, usuario):
    """Un validado cuyo envío falló: que el programador lo vuelva a intentar."""
    if correo.estado != CorreoTorneos.Estado.VALIDADO:
        raise CorreoError("Solo se reintenta un correo validado que no ha salido.")
    if not puede_validar(usuario, correo):
        raise CorreoError(f"{correo.jugador.nombre} no es de tu grupo.")
    correo.envio_error = ""
    correo.save(update_fields=["envio_error"])
    return correo


def responder_a(jugador):
    """gestion@ y su head coach (los que tienen correo en Club › Personas)."""
    from evaluaciones.informes import _correo_de_la_cuenta

    lista = [_correo_de_la_cuenta()] + [u.email for u in head_coaches(jugador) if u.email]
    vistos, out = set(), []
    for e in lista:
        if e and e.lower() not in vistos:
            vistos.add(e.lower())
            out.append(e)
    return out


def enviar(correo):
    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives

    from evaluaciones.informes import correo_configurado

    if correo.estado != CorreoTorneos.Estado.VALIDADO:
        raise CorreoError("Solo salen los correos validados.")
    if not correo_configurado():
        raise CorreoError("El envío por correo aún no está configurado en el servidor.")
    para = [d["email"] for d in correo.destinatarios if d.get("email")]
    try:
        asunto, texto, html = mensaje(correo)
        m = EmailMultiAlternatives(asunto, texto, settings.DEFAULT_FROM_EMAIL, para,
                                   reply_to=responder_a(correo.jugador))
        m.attach_alternative(html, "text/html")
        nombre_pdf, contenido_pdf = pdf_de(correo)
        m.attach(nombre_pdf, contenido_pdf, "application/pdf")
        m.send(fail_silently=False)
    except Exception as e:  # noqa: BLE001 — se guarda el motivo y se avisa
        log.warning("No sale el correo de torneos de %s", correo.jugador, exc_info=True)
        correo.envio_error = str(e)[:300] or e.__class__.__name__
        correo.save(update_fields=["envio_error"])
        raise CorreoError(f"No se ha podido enviar: {e}")
    correo.estado = CorreoTorneos.Estado.ENVIADO
    correo.enviado_en = timezone.now()
    correo.envio_error = ""
    correo.save(update_fields=["estado", "enviado_en", "envio_error"])
    return correo


def enviar_validados():
    """Lo llama el programador cada minuto: manda los validados que aún no han
    salido. Si uno falla no se reintenta solo (queda el motivo, y se avisa a
    quien lo validó, que puede volver a intentarlo). Si el servidor no tiene el
    correo configurado, esperan sin hacer nada (y sin avisar cada minuto)."""
    from evaluaciones.informes import correo_configurado

    if not correo_configurado():
        return 0
    enviados = 0
    for correo in (CorreoTorneos.objects.filter(estado=CorreoTorneos.Estado.VALIDADO, envio_error="")
                   .select_related("jugador", "validado_por")):
        with transaction.atomic():
            # Que dos programadores no manden el mismo dos veces.
            fresco = CorreoTorneos.objects.select_for_update().filter(
                pk=correo.pk, estado=CorreoTorneos.Estado.VALIDADO, envio_error="").first()
            if fresco is None:
                continue
            try:
                enviar(fresco)
                enviados += 1
            except CorreoError as e:
                _avisar([correo.validado_por], f"No ha salido el correo de torneos de {correo.jugador.nombre}",
                        f"{e} En Torneos › Correos a familias puedes revisarlo y volver a validarlo.")
    return enviados
