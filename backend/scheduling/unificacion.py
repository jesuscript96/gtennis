"""Un solo registro de faltas y un solo calendario del entrenador (orden de la
aplicación, 10/11/2026). Lo usan la migración `scheduling.0034` y el comando
`unificar_faltas` (repaso tras el despliegue): no cambiar sin mirar las dos.

  * Las faltas del parte semanal (`Disponibilidad`, todo lo que no es EXTRA)
    pasan a las faltas por fechas (`AusenciaJugador`), una por día y ámbito, con
    su nota, su subtipo y si fue tardía. «Disponible» suelto (sin falta que
    anular ese día) no dice nada y no se convierte.
  * «Disp. entrenadores» (`DisponibilidadEntrenador`) pasa al calendario del
    entrenador (`VacacionesEntrenador`): «no está» → el día entero; «disponible
    de X a Y» → no está antes de X ni después de Y ese día.
  * Quien tenía «Disponible esta semana» apagado pasa a tener en su calendario
    «No disponible» un año desde hoy, visible y editable.

Nada se pierde (11/11/2026): cada fila borrada se guarda entera en el archivo
de migraciones, cada cambio con su valor anterior y cada fila nueva con su
clave, de modo que `users.archivo_migraciones.deshacer` lo deja todo como
estaba.
"""
from datetime import date, time, timedelta

from users import archivo_migraciones as archivo

EXTRA = "EXTRA"
INICIO_DIA, FIN_DIA = time(0, 0), time(23, 59)
MOTIVO_INTERRUPTOR = "No disponible (estaba marcado en su ficha)"


def unificar(apps, nombre):
    """Hace la conversión con los modelos de `apps` (los de la migración o los
    de la aplicación) y lo archiva bajo `nombre`. Devuelve un resumen."""
    Disponibilidad = apps.get_model("scheduling", "Disponibilidad")
    AusenciaJugador = apps.get_model("scheduling", "AusenciaJugador")
    DisponibilidadEntrenador = apps.get_model("scheduling", "DisponibilidadEntrenador")
    Vacaciones = apps.get_model("academy", "VacacionesEntrenador")
    Entrenador = apps.get_model("academy", "Entrenador")
    resumen = {"faltas": 0, "disponible_suelto": 0, "entrenador_filas": 0,
               "entrenador_ausencias": 0, "interruptor": 0}

    for d in Disponibilidad.objects.exclude(estado=EXTRA).select_related("semana").order_by("pk"):
        fecha = d.semana.fecha_inicio + timedelta(days=d.dia)
        archivo.guardar(apps, nombre, "borrado", d)
        # «Disponible» en el parte solo servía para anular, ese día, una falta
        # por fechas (el parte mandaba). Sin falta que anular no se convierte;
        # con ella se conserva, para que el motor decida igual.
        if d.estado == "DISPONIBLE" and not AusenciaJugador.objects.filter(
                jugador_id=d.jugador_id, fecha_inicio__lte=fecha, fecha_fin__gte=fecha).exists():
            resumen["disponible_suelto"] += 1
        else:
            nueva = AusenciaJugador.objects.create(
                jugador_id=d.jugador_id, fecha_inicio=fecha, fecha_fin=fecha,
                ambito=d.ambito, estado=d.estado, subtipo=d.subtipo,
                nota=(d.nota or "")[:200], tardia=d.tardia,
            )
            archivo.guardar(apps, nombre, "creado", nueva)
            resumen["faltas"] += 1
        Disponibilidad.objects.filter(pk=d.pk).delete()

    for d in DisponibilidadEntrenador.objects.select_related("semana").order_by("pk"):
        fecha = d.semana.fecha_inicio + timedelta(days=d.dia)
        base = dict(entrenador_id=d.entrenador_id, fecha_inicio=fecha, fecha_fin=fecha, ambito="DIA")
        nuevas = []
        if d.estado == "AUSENTE":
            nuevas.append(dict(motivo=(d.nota or "No disponible")[:200], **base))
        elif d.hora_desde or d.hora_hasta:
            ventana = f"{(d.hora_desde or INICIO_DIA):%H:%M}–{(d.hora_hasta or FIN_DIA):%H:%M}"
            motivo = (d.nota or ("Torneo" if d.estado == "TORNEO" else "Solo disponible")) + f" ({ventana})"
            if d.hora_desde and d.hora_desde > INICIO_DIA:
                nuevas.append(dict(motivo=motivo[:200], hora_desde=INICIO_DIA, hora_hasta=d.hora_desde, **base))
            if d.hora_hasta and d.hora_hasta < FIN_DIA:
                nuevas.append(dict(motivo=motivo[:200], hora_desde=d.hora_hasta, hora_hasta=FIN_DIA, **base))
        # Disponible todo el día (o torneo sin horas): no había nada que quitar.
        archivo.guardar(apps, nombre, "borrado", d)
        for datos in nuevas:
            archivo.guardar(apps, nombre, "creado", Vacaciones.objects.create(**datos))
            resumen["entrenador_ausencias"] += 1
        DisponibilidadEntrenador.objects.filter(pk=d.pk).delete()
        resumen["entrenador_filas"] += 1

    hoy = date.today()
    for e in Entrenador.objects.filter(disponible_semana=False).order_by("pk"):
        archivo.guardar(apps, nombre, "cambiado", e, campos=["disponible_semana"])
        v = Vacaciones.objects.create(
            entrenador_id=e.pk, fecha_inicio=hoy, fecha_fin=hoy + timedelta(days=365), ambito="DIA",
            motivo=MOTIVO_INTERRUPTOR)
        archivo.guardar(apps, nombre, "creado", v)
        Entrenador.objects.filter(pk=e.pk).update(disponible_semana=True)
        resumen["interruptor"] += 1
    return resumen
