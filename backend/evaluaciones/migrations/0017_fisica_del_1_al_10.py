"""La preparación física, del 1 al 10 en Alto rendimiento (25/11/2026).

Como el tenis desde el 12/11: cada evaluación física guarda su escala
(`EvaluacionFisica.escala`), Alto rendimiento puntúa del 1 al 10 y Competición
de tardes sigue del 1 al 5. Las ya hechas de Alto rendimiento pasan con una
regla de tres (lo pidió el usuario): nota × 10 / 5, así que un 3 es un 6. Su
PDF de Drive se rehace si el informe está por validar o aprobado y aún no se ha
enviado a la familia.

Todo queda en el archivo de migraciones: deshacerla (`migrate evaluaciones
0016`) devuelve las notas a como estaban y vuelve a hacer esos PDF.
"""
import logging

from django.db import migrations, models

from users import archivo_migraciones as archivo

NOMBRE = "evaluaciones.0017_fisica_del_1_al_10"
ANTES, AHORA = 5, 10

log = logging.getLogger(__name__)


def _rehacer_pdfs(informe_ids):
    """El PDF de Drive de esos informes, con el código de la app; si Drive
    falla, el informe sigue bien en la app."""
    if not informe_ids:
        return
    from evaluaciones import informes
    from evaluaciones.models import Informe

    for inf in Informe.objects.filter(pk__in=informe_ids).select_related("jugador", "tenis", "fisica"):
        try:
            informes.guardar_en_drive(inf)
        except Exception:  # noqa: BLE001
            log.exception("Drive del informe %s", inf.pk)


def _con_pdf(apps, fisica_ids):
    Informe = apps.get_model("evaluaciones", "Informe")
    return list(Informe.objects.filter(fisica_id__in=fisica_ids, fisica__estado="TERMINADA",
                                       estado__in=["PENDIENTE", "VALIDADO"], enviado_en__isnull=True)
                .values_list("pk", flat=True))


def aplicar(apps, schema_editor):
    EvaluacionFisica = apps.get_model("evaluaciones", "EvaluacionFisica")
    cambiadas = []
    for ev in (EvaluacionFisica.objects.filter(escala=ANTES)
               .exclude(jugador__escuela__solo_informes=True).order_by("id")):
        archivo.guardar(apps, NOMBRE, "cambiado", ev, campos=["puntuaciones", "escala"])
        ev.puntuaciones = {k: (v * AHORA // ANTES if isinstance(v, int) else v)
                           for k, v in (ev.puntuaciones or {}).items()}
        ev.escala = AHORA
        ev.save(update_fields=["puntuaciones", "escala"])
        cambiadas.append(ev.pk)
    _rehacer_pdfs(_con_pdf(apps, cambiadas))


def deshacer(apps, schema_editor):
    cambiadas = [int(e.pk_original) for e in archivo.entradas(apps, NOMBRE, "cambiado")]
    archivo.deshacer(apps, NOMBRE)
    _rehacer_pdfs(_con_pdf(apps, cambiadas))


class Migration(migrations.Migration):

    dependencies = [
        ("evaluaciones", "0016_fisica_tardia_y_correos"),
        ("users", "0007_funciones_preparacion_fisica"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluacionfisica",
            name="escala",
            field=models.PositiveSmallIntegerField(db_default=5, default=5),
        ),
        migrations.RunPython(aplicar, deshacer),
    ]
