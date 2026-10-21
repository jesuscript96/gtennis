"""Mide cuánto tarda el motor en generar, sin tocar la base de datos.

Genera los días pedidos dentro de una transacción que se deshace al final, y
saca por pantalla cada llamada al solver (tiempo, estado, objetivo y cuántos
se quedan fuera) y el total. Uso:
    python manage.py medir_motor --semana 2026-09-28 --dias 1
    python manage.py medir_motor --semana 2026-09-28            # semana entera
    python manage.py medir_motor --semana 2026-09-28 --sin-mejora 0 --tope 30
"""
import os
import time

from django.core.management.base import BaseCommand
from django.db import transaction

from scheduling.models import ConfiguracionMotor, Semana


class _Deshacer(Exception):
    pass


class Command(BaseCommand):
    help = "Mide el tiempo de cada llamada al solver al generar (sin guardar nada)."

    def add_arguments(self, parser):
        parser.add_argument("--semana", required=True, help="Lunes de la semana (AAAA-MM-DD).")
        parser.add_argument("--dias", default="", help="Índices de día separados por comas (0 = lunes). Por defecto, toda la semana.")
        parser.add_argument("--sin-mejora", type=float, default=None,
                            help="Segundos sin mejorar para parar (0 = hasta el tope). Por defecto, MOTOR_SIN_MEJORA_S o 1.")
        parser.add_argument("--tope", type=int, default=None,
                            help="Tope del solver por franja en segundos (por defecto, el de la configuración).")
        parser.add_argument("--workers", type=int, default=None, help="Hilos del solver (por defecto, los procesadores).")

    def handle(self, *args, **opts):
        import engine.service as svc
        from engine.pairing import num_workers

        if opts["sin_mejora"] is not None:
            os.environ["MOTOR_SIN_MEJORA_S"] = str(opts["sin_mejora"])
        if opts["workers"] is not None:
            os.environ["MOTOR_WORKERS"] = str(opts["workers"])
        semana = Semana.objects.get(fecha_inicio=opts["semana"])
        dias = [int(d) for d in opts["dias"].split(",") if d.strip()] or None

        llamadas = []
        original = svc.solve_pairing

        def medido(data):
            t = time.monotonic()
            r = original(data)
            dt = time.monotonic() - t
            llamadas.append(dt)
            self.stdout.write(
                f"  {dt:6.2f} s  tope {data.time_limit_s:4.0f}  {r.status:8}  "
                f"franjas {len(data.franjas or [1])}  jugadores {len(data.players):3}  "
                f"{'forzar ' if data.forzar else '       '}"
                f"objetivo {r.objective:12.0f}  fuera {len(r.unassigned)}"
            )
            return r

        self.stdout.write(f"semana {semana.fecha_inicio}  días {dias or 'todos'}  "
                          f"hilos {num_workers()}  sin mejora "
                          f"{os.environ.get('MOTOR_SIN_MEJORA_S', '1')} s")
        svc.solve_pairing = medido
        t0 = time.monotonic()
        try:
            with transaction.atomic():
                if opts["tope"] is not None:
                    cfg = ConfiguracionMotor.get_solo()
                    cfg.time_limit_s = opts["tope"]
                    cfg.save()
                report = svc.generate(semana, dias=dias)
                raise _Deshacer
        except _Deshacer:
            pass
        finally:
            svc.solve_pairing = original
        total = time.monotonic() - t0
        fuera = sum(len(u["jugadores"]) for u in report.get("unassigned", []))
        self.stdout.write(
            f"total {total:.1f} s  solver {sum(llamadas):.1f} s en {len(llamadas)} llamadas  "
            f"banquillo {fuera}  sin entrenador {sum(len(s['pistas']) for s in report.get('sin_entrenador', []))}"
        )
