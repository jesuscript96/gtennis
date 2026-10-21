"""Genera cada día de entreno en su corte (01/10/2026).

A las 19:00 se rehace el día siguiente —el viernes a las 16:30, el sábado—
(si la semana aún está vacía, se genera entera desde ese día hasta el sábado),
respetando lo puesto a mano. Lo que llegue después ya no cambia el cuadrante
(ver `scheduling.corte`). Si el proceso estaba parado a esa hora, lo hace en
cuanto arranca, mientras ese día no haya empezado.

Corre en su propia máquina de Fly (`programador` en fly.toml): se despierta
cada minuto y mira si toca. Uso:
    python manage.py programador            # en bucle
    python manage.py programador --una-vez  # mira una vez y sale
"""
import time
import traceback

from django.core.management.base import BaseCommand
from django.db import IntegrityError, close_old_connections, transaction
from django.utils import timezone

from academy.models import Aviso
from scheduling.corte import dia_a_generar, lunes_y_dia
from scheduling.models import Asignacion, GeneracionProgramada, Semana

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def generar_dia(fecha):
    """Rehace `fecha` una sola vez. Devuelve la fila, o None si ya se hizo."""
    from engine.service import generate
    from scheduling.avisos_corte import destinatarios_direccion

    try:
        with transaction.atomic():
            fila = GeneracionProgramada.objects.create(fecha=fecha)
    except IntegrityError:
        return None
    lunes, dia = lunes_y_dia(fecha)
    nombre = f"{DIAS[dia]} {fecha.day}"
    try:
        semana, _ = Semana.objects.get_or_create(fecha_inicio=lunes)
        # Una semana que aún no tiene nada se genera entera, de este día al
        # sábado (21/10/2026): el domingo a las 19:00 salía solo el lunes y la
        # semana, ya creada y publicada, parecía hecha con el resto vacío.
        # Luego cada tarde se rehace el día siguiente, como siempre.
        entera = not Asignacion.objects.filter(semana=semana).exists()
        informe = generate(semana, dias=list(range(dia, 6)) if entera else [dia])
        fuera = sum(len(u["jugadores"]) for u in informe.get("unassigned", []))
        fila.ok = True
        fila.detalle = f"{fuera} sin pista" + (" (semana entera)" if entera else "")
        titulo = f"Listo el cuadrante del {nombre}"
        mensaje = ("Generado en el corte, respetando lo puesto a mano. Desde "
                   "ahora los cambios de ese día no lo tocan: llegan como aviso.")
        if entera:
            titulo = f"Lista la semana del {lunes.day}/{lunes.month}"
            mensaje = (f"Generada entera, del {nombre} al sábado. Cada día se "
                       "vuelve a rehacer a las 19:00 del día anterior con las "
                       "faltas que haya entonces. " + mensaje)
        if fuera:
            mensaje += f" {fuera} jugador(es) se han quedado sin pista."
        forzadas = len(informe.get("forzadas", []))
        if forzadas:
            mensaje += (f" {forzadas} jugador(es) se han metido en una pista "
                        "saltándose reglas base para que entrenen: salen marcados "
                        "como «forzada» en el cuadrante.")
    except Exception:  # noqa: BLE001 — cualquier fallo se avisa
        fila.detalle = traceback.format_exc()[-4000:]
        titulo = f"Ha fallado la generación del {nombre}"
        mensaje = ("El cuadrante de ese día no se ha rehecho. Hay que generarlo "
                   "a mano desde la semana.")
    fila.terminada_at = timezone.now()
    fila.save()
    for u in destinatarios_direccion():
        Aviso.objects.create(usuario=u, tipo=Aviso.Tipo.GENERACION,
                             titulo=titulo, mensaje=mensaje)
    return fila


class Command(BaseCommand):
    help = "Genera cada día de entreno a la hora de su corte."

    def add_arguments(self, parser):
        parser.add_argument("--una-vez", action="store_true")

    def handle(self, *args, una_vez=False, **opts):
        self.stdout.write("Programador en marcha.")
        while True:
            close_old_connections()
            fecha = dia_a_generar()
            if fecha is not None:
                fila = generar_dia(fecha)
                if fila is not None:
                    self.stdout.write(
                        f"{timezone.localtime():%Y-%m-%d %H:%M} {fecha}: "
                        f"{'ok' if fila.ok else 'FALLO'} {fila.detalle[:200]}")
            if una_vez:
                return
            time.sleep(60)
