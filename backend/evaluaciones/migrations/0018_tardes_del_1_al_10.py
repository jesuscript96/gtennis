"""Competición de tardes, del 1 al 10, tenis y física (25/11/2026).

Desde hoy todas las evaluaciones nuevas se puntúan del 1 al 10
(`catalogo.escala_de`). Las que quedaban del 1 al 5 (las de tenis de tardes
empezadas; la física de Alto rendimiento ya pasó en la 0017) pasan con la
misma regla de tres: nota × 10 / 5. Se rehace el PDF de Drive de los informes
por validar o aprobados sin enviar que las llevan.

Todo queda en el archivo de migraciones: deshacerla (`migrate evaluaciones
0017`) devuelve las notas a como estaban.
"""
import logging

from django.db import migrations

from users import archivo_migraciones as archivo

NOMBRE = "evaluaciones.0018_tardes_del_1_al_10"
ANTES, AHORA = 5, 10

log = logging.getLogger(__name__)


def _rehacer_pdfs(apps, tenis_ids, fisica_ids):
    """El PDF de Drive de los informes que las llevan, con el código de la app;
    si Drive falla, el informe sigue bien en la app."""
    from django.db.models import Q

    Informe = apps.get_model("evaluaciones", "Informe")
    ids = list(Informe.objects.filter(Q(tenis_id__in=tenis_ids) | Q(fisica_id__in=fisica_ids))
               .filter(estado__in=["PENDIENTE", "VALIDADO"], enviado_en__isnull=True)
               .values_list("pk", flat=True))
    if not ids:
        return
    from evaluaciones import informes
    from evaluaciones.models import Informe as InformeReal

    for inf in InformeReal.objects.filter(pk__in=ids).select_related("jugador", "tenis", "fisica"):
        try:
            informes.guardar_en_drive(inf)
        except Exception:  # noqa: BLE001
            log.exception("Drive del informe %s", inf.pk)


def _pasar(apps, modelo):
    Modelo = apps.get_model("evaluaciones", modelo)
    cambiadas = []
    for ev in Modelo.objects.filter(escala=ANTES).order_by("id"):
        archivo.guardar(apps, NOMBRE, "cambiado", ev, campos=["puntuaciones", "escala"])
        ev.puntuaciones = {k: (v * AHORA // ANTES if isinstance(v, int) else v)
                           for k, v in (ev.puntuaciones or {}).items()}
        ev.escala = AHORA
        ev.save(update_fields=["puntuaciones", "escala"])
        cambiadas.append(ev.pk)
    return cambiadas


def aplicar(apps, schema_editor):
    tenis = _pasar(apps, "Evaluacion")
    fisica = _pasar(apps, "EvaluacionFisica")
    _rehacer_pdfs(apps, tenis, fisica)


def deshacer(apps, schema_editor):
    entradas = list(archivo.entradas(apps, NOMBRE, "cambiado"))
    tenis = [int(e.pk_original) for e in entradas if e.modelo == "evaluaciones.evaluacion"]
    fisica = [int(e.pk_original) for e in entradas if e.modelo == "evaluaciones.evaluacionfisica"]
    archivo.deshacer(apps, NOMBRE)
    _rehacer_pdfs(apps, tenis, fisica)


class Migration(migrations.Migration):

    dependencies = [
        ("evaluaciones", "0017_fisica_del_1_al_10"),
        ("users", "0007_funciones_preparacion_fisica"),
    ]

    operations = [migrations.RunPython(aplicar, deshacer)]
