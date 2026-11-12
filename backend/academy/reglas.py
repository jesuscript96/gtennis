"""Las reglas de un jugador, juntas (orden de la aplicación, 10/11/2026).

Antes estaban repartidas: rencillas y contratos en la tuerca, la superficie en
Datos, y el veto de entrenador, la pareja y el entrenador por franja solo se
podían cargar con el Excel. Ahora se leen y se cambian todas desde la ficha del
jugador, en el apartado Reglas. Las ven y las cambian dirección y los head
coaches (decisión 7); el entrenador, no.
"""
from django.db.models import Q

from .models import (
    Contrato, Entrenador, Jugador, PreferenciaEntrenadorFranja, PreferenciaPareja,
    PreferenciaSuperficie, Rencilla, Turno, VetoEntrenador,
)

TIPOS = ("rencilla", "contrato", "veto", "pareja", "franja", "superficie")


def leer(j):
    return {
        "rencillas": [
            {"id": r.id, "jugador": otro.id, "nombre": otro.nombre, "motivo": r.motivo}
            for r in Rencilla.objects.filter(Q(jugador_a=j) | Q(jugador_b=j)).select_related("jugador_a", "jugador_b")
            for otro in [r.jugador_b if r.jugador_a_id == j.id else r.jugador_a]
        ],
        "contratos": [
            {"id": c.id, "entrenador": c.entrenador_id, "nombre": c.entrenador.nombre,
             "tipo": c.tipo, "tipo_display": c.get_tipo_display(), "activo": c.activo}
            for c in j.contratos.select_related("entrenador")
        ],
        "vetos": [
            {"id": v.id, "entrenador": v.entrenador_id, "nombre": v.entrenador.nombre, "nota": v.nota}
            for v in j.vetos_entrenador.filter(activo=True).select_related("entrenador")
        ],
        "parejas": [
            {"id": p.id, "jugador": p.jugador_objetivo_id, "nombre": p.jugador_objetivo.nombre,
             "tipo": p.tipo, "tipo_display": p.get_tipo_display()}
            for p in j.parejas_pref.filter(activa=True).select_related("jugador_objetivo")
        ],
        "franjas": [
            {"id": f.id, "turno": f.turno_id, "turno_codigo": f.turno.codigo,
             "entrenador": f.entrenador_id, "nombre": f.entrenador.nombre,
             "tipo": f.tipo, "tipo_display": f.get_tipo_display()}
            for f in j.preferencias_franja.filter(activa=True).select_related("turno", "entrenador")
        ],
        # La superficie fija (sin fechas). La de unas fechas va en su calendario.
        "superficie": next((
            {"id": s.id, "superficie": s.superficie, "estricta": s.estricta}
            for s in j.preferencias_superficie.filter(fecha_desde__isnull=True, fecha_hasta__isnull=True)
        ), None),
    }


def _num(datos, campo):
    try:
        return int(datos.get(campo))
    except (TypeError, ValueError):
        raise ValueError("Falta elegir a quién.")


def anadir(j, datos):
    tipo = datos.get("tipo")
    if tipo == "rencilla":
        otro = Jugador.objects.get(pk=_num(datos, "jugador"))
        if otro.pk == j.pk:
            raise ValueError("Una rencilla necesita dos jugadores distintos.")
        a, b = sorted([j, otro], key=lambda x: x.pk)
        Rencilla.objects.get_or_create(jugador_a=a, jugador_b=b,
                                       defaults={"motivo": (datos.get("motivo") or "")[:200]})
    elif tipo == "contrato":
        Contrato.objects.update_or_create(
            jugador=j, entrenador=Entrenador.objects.get(pk=_num(datos, "entrenador")),
            defaults={"tipo": datos.get("tipo_contrato") or Contrato.Tipo.DURO, "activo": True})
    elif tipo == "veto":
        VetoEntrenador.objects.update_or_create(
            jugador=j, entrenador=Entrenador.objects.get(pk=_num(datos, "entrenador")),
            defaults={"activo": True, "nota": (datos.get("nota") or "")[:200]})
    elif tipo == "pareja":
        otro = Jugador.objects.get(pk=_num(datos, "jugador"))
        if otro.pk == j.pk:
            raise ValueError("La pareja tiene que ser otro jugador.")
        PreferenciaPareja.objects.update_or_create(
            jugador=j, jugador_objetivo=otro,
            defaults={"tipo": datos.get("tipo_pareja") or PreferenciaPareja.Tipo.SOFT, "activa": True})
    elif tipo == "franja":
        PreferenciaEntrenadorFranja.objects.update_or_create(
            jugador=j, turno=Turno.objects.get(pk=_num(datos, "turno")),
            entrenador=Entrenador.objects.get(pk=_num(datos, "entrenador")),
            defaults={"tipo": datos.get("tipo_franja") or PreferenciaEntrenadorFranja.Tipo.DURO, "activa": True})
    elif tipo == "superficie":
        PreferenciaSuperficie.objects.filter(jugador=j, fecha_desde__isnull=True, fecha_hasta__isnull=True).delete()
        if datos.get("superficie"):
            PreferenciaSuperficie.objects.create(
                jugador=j, superficie=datos["superficie"], estricta=bool(datos.get("estricta")))
    else:
        raise ValueError("Tipo de regla desconocido.")


def quitar(j, tipo, pk):
    modelos = {
        "rencilla": Rencilla.objects.filter(Q(jugador_a=j) | Q(jugador_b=j)),
        "contrato": Contrato.objects.filter(jugador=j),
        "veto": VetoEntrenador.objects.filter(jugador=j),
        "pareja": PreferenciaPareja.objects.filter(jugador=j),
        "franja": PreferenciaEntrenadorFranja.objects.filter(jugador=j),
        "superficie": PreferenciaSuperficie.objects.filter(jugador=j),
    }
    if tipo not in modelos:
        raise ValueError("Tipo de regla desconocido.")
    modelos[tipo].filter(pk=pk).delete()
