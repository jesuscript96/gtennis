"""Deshacer cambios del cuadrante.

Toda operación que cambia el cuadrante —a mano, al rehacer, la generación de
las 19:00 o un «viene además» que coloca a alguien— guarda antes una foto de la
semana (10/11/2026: antes la generación de las 19:00 y «viene además» no la
guardaban, y un Deshacer posterior se los llevaba por delante sin avisar).
Deshacer es volver a la última foto y tirarla; la interfaz enseña antes qué se
va a deshacer, cuándo y quién lo hizo.

La foto guarda las asignaciones y quién se quitó a mano (el banquillo), para
que deshacer un «rehacer desde cero» devuelva también esa memoria.
"""
from .models import Asignacion, CambioSemana, QuitadoAMano

CAMPOS = ("dia", "turno_id", "pista_id", "jugador_id", "entrenador_id",
          "estado", "manual", "forzada", "motivo_forzado")
CAMPOS_QUITADO = ("dia", "turno_id", "jugador_id")
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado"]


def foto(semana_id):
    return {
        "asignaciones": list(Asignacion.objects.filter(semana_id=semana_id).values(*CAMPOS)),
        "quitados": list(QuitadoAMano.objects.filter(semana_id=semana_id).values(*CAMPOS_QUITADO)),
    }


def registrar(semana_id, descripcion, usuario=None, request=None):
    """Guarda cómo está la semana antes de tocarla. Con `request`, la foto se
    descarta si la petición acaba en error (no deja pasos vacíos)."""
    if not semana_id:
        return None
    cambio = CambioSemana.objects.create(
        semana_id=semana_id, descripcion=descripcion[:120], foto=foto(semana_id),
        creado_por=usuario if usuario and usuario.is_authenticated else None,
    )
    if request is not None:
        request._foto_pendiente = cambio.id
    sobran = CambioSemana.objects.filter(semana_id=semana_id).values_list(
        "id", flat=True)[CambioSemana.MAXIMO:]
    if sobran:
        CambioSemana.objects.filter(id__in=list(sobran)).delete()
    return cambio


def descartar_pendiente(request):
    """La operación ha fallado con una excepción: su foto sobra."""
    pendiente = getattr(request, "_foto_pendiente", None)
    if pendiente:
        CambioSemana.objects.filter(pk=pendiente).delete()
        request._foto_pendiente = None


def descartar_si_fallo(request, response):
    """Si la operación no se hizo, su foto sobra."""
    pendiente = getattr(request, "_foto_pendiente", None)
    if pendiente and response is not None and response.status_code >= 400:
        CambioSemana.objects.filter(pk=pendiente).delete()


def deshacer(semana_id):
    """Restaura la última foto. Devuelve qué se deshizo, o None si no hay nada.

    La semana se rehace entera: borrar y volver a crear evita pelearse con el
    unique de (semana, día, turno, jugador) al cruzarse dos filas.
    """
    cambio = CambioSemana.objects.filter(semana_id=semana_id).first()
    if cambio is None:
        return None
    datos = cambio.foto
    # Fotos de antes del 10/11/2026: solo la lista de asignaciones.
    filas = datos if isinstance(datos, list) else datos.get("asignaciones", [])
    Asignacion.objects.filter(semana_id=semana_id).delete()
    Asignacion.objects.bulk_create([Asignacion(semana_id=semana_id, **f) for f in filas])
    if isinstance(datos, dict):
        QuitadoAMano.objects.filter(semana_id=semana_id).delete()
        QuitadoAMano.objects.bulk_create([
            QuitadoAMano(semana_id=semana_id, **q) for q in datos.get("quitados", [])])
    else:
        # Quien vuelve a estar en pista ya no cuenta como quitado a mano.
        for q in QuitadoAMano.objects.filter(semana_id=semana_id).select_related("turno"):
            if Asignacion.objects.filter(
                semana_id=semana_id, dia=q.dia, jugador_id=q.jugador_id,
                turno__bloque=q.turno.bloque,
            ).exists():
                q.delete()
    descripcion = cambio.descripcion
    cambio.delete()
    return descripcion


def quedan(semana_id):
    return CambioSemana.objects.filter(semana_id=semana_id).count()


def que_dias(dias=None, bloques=None):
    """«el martes», «de martes a sábado», «toda la semana» (+ «por la tarde»)."""
    if not dias:
        txt = "toda la semana"
    elif len(dias) == 1:
        txt = f"el {DIAS[dias[0]]}"
    else:
        txt = f"de {DIAS[min(dias)]} a {DIAS[max(dias)]}"
    if bloques and len(bloques) == 1:
        txt += " por la tarde" if str(bloques[0]).upper() == "TARDE" else " por la mañana"
    return txt
