"""Los torneos que tiene por delante un jugador (25/11/2026): para su página
en la app, su PDF y el correo mensual a la familia.

Entran todos a los que está apuntado, confirmados y por confirmar; cada uno
dice en qué punto del circuito está (`circuito.espera_a`).
"""
from datetime import date

from . import categorias as cats
from . import circuito
from .models import Participante, Torneo
from .serializers import de_baja, entrenador_de


def _fecha(x):
    """Las fechas guardadas en un correo validado vuelven como texto."""
    if x is None or isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


def fila(p, hoy=None):
    """Una participación como la pinta todo el mundo (página, PDF, correo)."""
    hoy = hoy or date.today()
    t = p.torneo
    cierre = t.cierre_inscripcion
    return {
        "participante": p.id, "id": t.id, "nombre": t.nombre, "circuito": t.circuito, "lugar": t.lugar,
        "fecha_inicio": t.fecha_inicio, "fecha_fin": t.fecha_fin,
        "qualy_inicio": t.qualy_inicio, "qualy_fin": t.qualy_fin,
        "solo_fines_semana": t.solo_fines_semana,
        "cierre_inscripcion": cierre, "fecha_borrado": t.fecha_borrado,
        "inscripcion_abierta": bool(cierre and cierre >= hoy),
        "dias_cierre": (cierre - hoy).days if cierre else None,
        "categorias": [cats.NOMBRE.get(c, c) for c in t.categorias or []],
        "acompanantes": [e.nombre for e in t.acompanantes.all()],
        "acompanante_nota": t.acompanante_nota,
        "cancelado": t.estado == Torneo.Estado.CANCELADO,
        "certeza": p.certeza, "certeza_display": p.get_certeza_display(),
        "espera": circuito.espera_a(p.certeza),
        "confirmado": p.certeza == Participante.Certeza.CONFIRMADO,
        "detalle": p.detalle,
    }


def torneos_de(jugador, desde=None, hasta=None, con_cancelados=False):
    """Sus torneos que acaban `desde` en adelante (hoy, si no se dice) y, con
    `hasta`, empiezan como muy tarde ese día (la previa cuenta)."""
    hoy = date.today()
    desde = desde or hoy
    qs = (Participante.objects.filter(jugador=jugador, torneo__fecha_fin__gte=desde)
          .select_related("torneo").prefetch_related("torneo__acompanantes")
          .order_by("torneo__fecha_inicio", "torneo__nombre"))
    if not con_cancelados:
        qs = qs.exclude(torneo__estado=Torneo.Estado.CANCELADO)
    filas = [fila(p, hoy) for p in qs]
    if hasta is not None:
        filas = [f for f in filas if min(d for d in (f["qualy_inicio"], f["fecha_inicio"]) if d) <= hasta]
    return filas


def ficha(jugador):
    """Lo que la página y el PDF dicen del jugador arriba."""
    cat = cats.categoria_de(jugador, date.today().year)
    return {
        "id": jugador.id, "nombre": jugador.nombre, "entrenador": entrenador_de(jugador),
        "categoria": cats.NOMBRE[cat] if cat else None, "de_baja": de_baja(jugador),
        "foto_url": getattr(jugador, "foto_url", "") or "",
    }


def resumen(filas):
    """Cifras de cabecera: cuántos, cuántos confirmados y el próximo cierre."""
    abiertos = sorted((f for f in filas if f["inscripcion_abierta"]), key=lambda f: _fecha(f["cierre_inscripcion"]))
    return {
        "total": len(filas),
        "confirmados": sum(1 for f in filas if f["confirmado"]),
        "por_confirmar": sum(1 for f in filas if not f["confirmado"]),
        "inscripciones_abiertas": len(abiertos),
        "proximo_cierre": abiertos[0]["cierre_inscripcion"] if abiertos else None,
        "proximo_cierre_torneo": abiertos[0]["nombre"] if abiertos else None,
    }
