"""Avisos de lo que llega después del corte (01/10/2026).

Pasado el corte de un día, una falta nueva no cambia el cuadrante: el jugador
sale tachado y se avisa a quien puede verle —dirección, los coaches que le
tienen en su grupo y el entrenador que le tiene en pista— para que lo arreglen
a mano. Lo mismo al revés: si se quita una falta o se apunta que viene además,
alguien tiene que hacerle hueco.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from academy.models import Aviso, Coach
from users.models import User

from .corte import dias_cerrados, lunes_y_dia
from .models import Asignacion, Semana

DIAS_CORTOS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _franjas(qs, ambito):
    if not ambito or ambito == "DIA":
        return qs
    if ambito in ("MANANA", "TARDE"):
        return qs.filter(turno__bloque=ambito)
    return qs.filter(turno__codigo=ambito)


def _en_pista(jugador, fecha, ambito, ahora):
    """Sus sesiones de ese día en ese ámbito que todavía no han empezado."""
    lunes, dia = lunes_y_dia(fecha)
    semana = Semana.objects.filter(fecha_inicio=lunes).first()
    if semana is None:
        return []
    filas = _franjas(
        Asignacion.objects.filter(semana=semana, dia=dia, jugador=jugador),
        ambito,
    ).select_related("turno", "pista", "pista__sede", "entrenador",
                     "entrenador__user")
    local = timezone.localtime(ahora)
    return [a for a in filas
            if fecha > local.date() or a.turno.horas(fecha)[0] > local.time()]


def destinatarios_direccion():
    return list(User.objects.filter(is_active=True).filter(
        Q(role=User.Role.SUPERADMIN) | Q(is_superuser=True)))


def destinatarios(jugador, entrenadores=(), excepto=None):
    """Dirección, los coaches que ven al jugador y los entrenadores dados."""
    from academy.scope import puede_ver_jugador

    usuarios = {u.id: u for u in destinatarios_direccion()}
    for coach in Coach.objects.filter(activo=True, user__is_active=True).select_related("user"):
        if puede_ver_jugador(coach.user, jugador):
            usuarios[coach.user.id] = coach.user
    for ent in entrenadores:
        if ent is not None and ent.user_id and ent.user.is_active:
            usuarios[ent.user_id] = ent.user
    if excepto is not None:
        usuarios.pop(excepto.id, None)
    return list(usuarios.values())


def _quien(usuario):
    if usuario is None:
        return "alguien"
    ent = getattr(usuario, "entrenador", None)
    return ent.nombre if ent is not None else (usuario.get_full_name() or usuario.username)


def avisar(jugador, desde, hasta, ambito, accion, usuario=None, nota=""):
    """Avisa si el cambio cae en un día ya cerrado. Devuelve los avisos creados.

    `accion`: "falta" (no viene), "quita_falta" (al final sí viene) o
    "viene" (viene además).
    """
    ahora = timezone.now()
    local = timezone.localtime(ahora)
    creados = []
    for fecha in dias_cerrados(desde, hasta, ahora):
        sesiones = _en_pista(jugador, fecha, ambito, ahora)
        if accion == "falta" and not sesiones:
            continue  # no estaba en pista: no hay nada que mover
        if accion != "falta" and sesiones:
            continue  # ya tiene sitio
        dia_txt = f"{DIAS_CORTOS[fecha.weekday()]} {fecha.day}"
        franja = "" if not ambito or ambito == "DIA" else f" ({ambito.lower() if ambito in ('MANANA', 'TARDE') else ambito})"
        if accion == "falta":
            titulo = f"Falta tras el corte: {jugador.nombre} · {dia_txt}{franja}"
            detalle = "; ".join(
                f"{a.turno.codigo} pista {a.pista.numero}"
                + (f" con {a.entrenador.nombre}" if a.entrenador_id else "")
                for a in sesiones)
            mensaje = (f"Declarada por {_quien(usuario)} a las {local:%H:%M}. "
                       f"Estaba en {detalle}. El cuadrante no se ha cambiado: "
                       f"sale tachado y hay que moverlo a mano.")
        else:
            que = "Ya no falta" if accion == "quita_falta" else "Viene además"
            titulo = f"{que} tras el corte: {jugador.nombre} · {dia_txt}{franja}"
            mensaje = (f"Apuntado por {_quien(usuario)} a las {local:%H:%M}. "
                       f"No está en el cuadrante de ese día: hay que hacerle "
                       f"hueco a mano.")
        if nota:
            mensaje += f" Nota: {nota}"
        entrenadores = {a.entrenador for a in sesiones if a.entrenador_id}
        if jugador.entrenador_responsable_id and accion != "falta":
            entrenadores.add(jugador.entrenador_responsable)
        for u in destinatarios(jugador, entrenadores, excepto=usuario):
            creados.append(Aviso.objects.create(
                usuario=u, tipo=Aviso.Tipo.CORTE, titulo=titulo[:160],
                mensaje=mensaje,
            ))
    return creados


def rango_de(fila):
    """(desde, hasta) de una falta por fechas o de un parte de la semana."""
    if hasattr(fila, "fecha_inicio"):
        return fila.fecha_inicio, fila.fecha_fin
    fecha = fila.semana.fecha_inicio + timedelta(days=fila.dia)
    return fecha, fecha
