"""Prepara un escenario de DEMO en local para probar las features del feedback:
un coach con login, jugadores en Junior Program y una preferencia de superficie.
Idempotente. Con --revert deshace los cambios de datos.

    python manage.py seed_demo_pruebas
    python manage.py seed_demo_pruebas --revert
"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from academy.models import Coach, Entrenador, Escuela, Jugador, PreferenciaSuperficie
from users.models import User


class Command(BaseCommand):
    help = "Datos de demo para probar el feedback (coach, Junior Program, superficie)."

    def add_arguments(self, parser):
        parser.add_argument("--revert", action="store_true")

    def handle(self, *args, **opts):
        jp = Escuela.objects.filter(nombre__icontains="junior").first()
        ar = Escuela.objects.filter(nombre__icontains="alto").first()

        if opts["revert"]:
            n = Jugador.objects.filter(escuela=jp).update(escuela=ar)
            Coach.objects.filter(nombre="Coach Demo").delete()
            User.objects.filter(username="coach").delete()
            PreferenciaSuperficie.objects.filter(jugador__nombre="__demo__").delete()
            self.stdout.write(self.style.WARNING(
                f"Demo revertido: {n} jugadores devueltos a {ar.nombre}, coach demo borrado."
            ))
            return

        # 1) Coach con login: coach / demo1234, con sus 2 entrenadores más cargados.
        cu, _ = User.objects.get_or_create(username="coach", defaults={"first_name": "Coach Demo"})
        cu.role = User.Role.COACH
        cu.set_password("demo1234")
        cu.save()
        coach, _ = Coach.objects.get_or_create(user=cu, defaults={"nombre": "Coach Demo"})
        coach.nombre, coach.activo = "Coach Demo", True
        coach.save()
        ents = list(
            Entrenador.objects.annotate(n=Count("jugadores_responsable"))
            .filter(n__gt=0).order_by("-n")[:2]
        )
        coach.entrenadores.set(ents)

        # 2) Junior Program: 6 jugadores (para ver la columna JP aislada).
        ids = list(
            Jugador.objects.filter(activo=True).order_by("nombre").values_list("id", flat=True)[:6]
        )
        Jugador.objects.filter(id__in=ids).update(escuela=jp)

        # 3) Preferencia de superficie estricta en un jugador visible.
        j = Jugador.objects.exclude(id__in=ids).filter(activo=True).order_by("nombre").first()
        PreferenciaSuperficie.objects.get_or_create(
            jugador=j, superficie="RESINA", defaults={"estricta": True}
        )

        self.stdout.write(self.style.SUCCESS(
            "Demo listo:\n"
            f"  · Login coach / demo1234  (entrenadores: {', '.join(e.nombre for e in ents)})\n"
            f"  · {len(ids)} jugadores movidos a Junior Program\n"
            f"  · Preferencia RESINA estricta en {j.nombre}\n"
            "Regenera el cuadrante para ver los efectos."
        ))
