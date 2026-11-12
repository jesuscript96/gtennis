"""La lista antigua de acceso (`Entrenador.jugadores_gestionados`) dejó de dar
acceso el 10/11/2026 (orden de la aplicación). Este comando enseña qué
entrenadores, y qué head coaches a través de los entrenadores de su bloque,
veían a algún jugador SOLO por esa lista, para que dirección decida si ponerlo
en su grupo (Grupos) o con porcentaje (ficha). Solo lee.

    python manage.py lista_antigua_acceso
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from academy.models import Coach, Entrenador, Jugador


class Command(BaseCommand):
    help = "Jugadores que un entrenador o head coach veía solo por la lista antigua de acceso."

    def handle(self, *args, **opts):
        total = 0
        self.stdout.write("Entrenadores:")
        for e in Entrenador.objects.filter(activo=True).order_by("nombre"):
            antiguos = Jugador.objects.filter(activo=True, entrenadores_gestores=e)
            perdidos = antiguos.exclude(pk__in=Jugador.objects.filter(e.q_jugadores())).distinct()
            nombres = sorted(perdidos.values_list("nombre", flat=True))
            if nombres:
                total += len(nombres)
                self.stdout.write(f"  {e.nombre}: {', '.join(nombres)}")
        # Head coaches (11/11/2026): antes también veían a los jugadores de la
        # lista antigua de cualquier entrenador de su bloque.
        self.stdout.write("Head coaches:")
        for c in Coach.objects.filter(activo=True).select_related("user").order_by("nombre"):
            if c.user_id and (c.user.is_superadmin or not c.user.is_active):
                continue  # dirección ve a todos
            ents = c.entrenadores.all()
            ahora = Jugador.objects.filter(
                Q(entrenador_responsable__isnull=True) | Q(entrenador_responsable__in=ents)
                | Q(cogestores__in=ents) | Q(responsables__entrenador__in=ents))
            perdidos = (Jugador.objects.filter(activo=True, entrenadores_gestores__in=ents)
                        .exclude(pk__in=ahora).distinct())
            nombres = sorted(perdidos.values_list("nombre", flat=True))
            if nombres:
                total += len(nombres)
                self.stdout.write(f"  {c.nombre}: {', '.join(nombres)}")
        self.stdout.write(f"Total: {total}")
