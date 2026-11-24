"""Arreglos de los informes del 24/11/2026.

1. La física que llegó tarde. A tres jugadores de Alto rendimiento (Xu Guilin,
   Huaqi Li y Mario Veselinov) les aprobaron el tenis el 21-22/11 sin física; la
   física, hecha el 23/11, se colgó de un informe nuevo (el del trimestre
   siguiente) que esperaba otra evaluación de tenis. Como ninguno se había
   enviado, la física pasa al informe aprobado, que vuelve a validar como
   versión nueva y con el PDF completo; el informe vacío se borra. Lo mismo que
   hace la app desde hoy cuando la física llega después de aprobar.
2. Los correos que quien aprobó escribió a mano se guardan en la ficha del
   jugador, solo donde estaba vacío (lo mismo que hace la app desde hoy).
3. Aviso a quien envía de los informes aprobados que siguen sin enviar.

Todo queda en el archivo de migraciones: deshacerla (`migrate evaluaciones
0015`) devuelve los informes, las fichas y los avisos a como estaban y vuelve a
dejar el PDF en «Validados» de Drive.
"""
import logging
from datetime import timedelta

from django.db import migrations
from django.utils import timezone

from users import archivo_migraciones as archivo

NOMBRE = "evaluaciones.0016_fisica_tardia_y_correos"
CICLO_PRONTO = 75

log = logging.getLogger(__name__)


def _ultimo_validado(Informe, jugador_id):
    return (Informe.objects.filter(jugador_id=jugador_id, estado="VALIDADO", validado_en__isnull=False)
            .order_by("-validado_en").first())


def _aviso(apps, usuarios, titulo, mensaje):
    Aviso = apps.get_model("academy", "Aviso")
    vistos = set()
    for u in usuarios:
        if u is None or u.pk in vistos:
            continue
        vistos.add(u.pk)
        a = Aviso.objects.create(usuario_id=u.pk, tipo="GENERAL", titulo=titulo, mensaje=mensaje)
        archivo.guardar(apps, NOMBRE, "creado", a)


def _fisica_tardia(apps):
    """Devuelve los ids de los informes aprobados a los que se suma la física."""
    Informe = apps.get_model("evaluaciones", "Informe")
    limite = timezone.now() - timedelta(days=CICLO_PRONTO)
    cambiados = []
    vacios = (Informe.objects.filter(estado="EN_CURSO", tenis__isnull=True, fisica__isnull=False)
              .exclude(jugador__escuela__solo_informes=True).order_by("id"))
    for vacio in vacios:
        validado = _ultimo_validado(Informe, vacio.jugador_id)
        if (validado is None or validado.fisica_id or validado.enviado_en
                or validado.validado_en < limite):
            continue
        fisica = vacio.fisica
        # Para deshacer en orden inverso: primero vuelve el aprobado sin física
        # y después el informe vacío con ella (la física es única por informe).
        archivo.guardar(apps, NOMBRE, "borrado", vacio)
        archivo.guardar(apps, NOMBRE, "cambiado", validado)
        vacio.delete()
        validado.fisica = fisica
        validado.estado = "PENDIENTE" if fisica.estado == "TERMINADA" else "EN_CURSO"
        validado.version += 1
        validado.validado_por = None
        validado.validado_en = None
        validado.envio_programado = None
        validado.envio_programado_por = None
        validado.devuelto_partes = []
        validado.save()
        cambiados.append(validado.pk)
    return cambiados


def _correos_a_la_ficha(apps):
    from evaluaciones import informes

    Informe = apps.get_model("evaluaciones", "Informe")
    Jugador = apps.get_model("academy", "Jugador")
    DatosInforme = apps.get_model("evaluaciones", "DatosInforme")
    from academy.models import Jugador as JugadorReal

    for inf in Informe.objects.filter(estado="VALIDADO").order_by("validado_en"):
        if not inf.destinatarios:
            continue
        jugador = Jugador.objects.get(pk=inf.jugador_id)
        datos = DatosInforme.objects.filter(jugador_id=inf.jugador_id).first()
        antes_j = archivo.guardar(apps, NOMBRE, "cambiado", jugador, campos=["email"])
        antes_d = archivo.guardar(apps, NOMBRE, "cambiado", datos, campos=["quien_1", "email_2", "quien_2"]) if datos else None
        guardados = informes.guardar_correos_en_ficha(JugadorReal.objects.get(pk=inf.jugador_id), inf.destinatarios)
        jugador.refresh_from_db()
        if jugador.email == antes_j.datos["email"]:
            antes_j.delete()
        if datos is not None:
            datos.refresh_from_db()
            if all(getattr(datos, k) == antes_d.datos[k] for k in ("quien_1", "email_2", "quien_2")):
                antes_d.delete()
        else:
            nuevo = DatosInforme.objects.filter(jugador_id=inf.jugador_id).first()
            if nuevo is not None:
                archivo.guardar(apps, NOMBRE, "creado", nuevo)
        if guardados:
            log.info("Correo guardado en la ficha de %s", jugador.nombre)


def aplicar(apps, schema_editor):
    # Primero los correos: el de Mario Veselinov solo está en su informe
    # aprobado, que después vuelve a validar.
    _correos_a_la_ficha(apps)
    cambiados = _fisica_tardia(apps)
    if not cambiados and not apps.get_model("evaluaciones", "Informe").objects.filter(
            estado="VALIDADO", enviado_en__isnull=True).exists():
        return
    # Lo que toca fuera de la base de datos (PDF en Drive, a quién avisar), con
    # el código de la app; si Drive falla, el informe sigue bien en la app.
    from evaluaciones import informes
    from evaluaciones.models import Informe

    for inf in Informe.objects.filter(pk__in=cambiados).select_related("jugador", "tenis", "fisica"):
        try:
            informes.guardar_en_drive(inf)
        except Exception:  # noqa: BLE001
            log.exception("Drive del informe %s", inf.pk)
        _aviso(apps, informes.usuarios_validan(inf),
               f"Informe de {inf.jugador.nombre}: se le ha sumado la parte física",
               f"La preparación física de {inf.fisica.nombre_evaluador} se hizo después de aprobar el tenis y "
               f"se había quedado para el informe del trimestre siguiente. Ya está en este informe, que vuelve "
               f"a validar con el PDF completo (versión {inf.version}). Aún no se había enviado a la familia.")
    sin_enviar = list(Informe.objects.filter(estado="VALIDADO", enviado_en__isnull=True)
                      .select_related("jugador").order_by("jugador__nombre"))
    if sin_enviar:
        nombres = ", ".join(i.jugador.nombre for i in sin_enviar)
        n = len(sin_enviar)
        _aviso(apps, informes.usuarios_envian(),
               f"{n} informe{'s' if n != 1 else ''} aprobado{'s' if n != 1 else ''} sin enviar",
               f"Esperan a enviarse a la familia: {nombres}. Los tienes en Rendimiento → Informes, en "
               f"«Por enviar» (ahora o mañana a las 8:30).")


def deshacer(apps, schema_editor):
    cambiados = [int(e.pk_original) for e in archivo.entradas(apps, NOMBRE, "cambiado")
                 if e.modelo == "evaluaciones.informe"]
    archivo.deshacer(apps, NOMBRE)
    if not cambiados:
        return
    from evaluaciones import informes
    from evaluaciones.models import Informe

    for inf in Informe.objects.filter(pk__in=cambiados).select_related("jugador", "tenis", "fisica"):
        try:
            informes.guardar_en_drive(inf)
        except Exception:  # noqa: BLE001
            log.exception("Drive del informe %s", inf.pk)


class Migration(migrations.Migration):

    dependencies = [
        ("evaluaciones", "0015_empezar_de_cero"),
        ("academy", "0067_puesto_a_quien_volvio_de_baja"),
        ("users", "0007_funciones_preparacion_fisica"),
    ]

    operations = [migrations.RunPython(aplicar, deshacer)]
