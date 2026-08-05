"""Crea (o actualiza) un usuario de tipo Entrenador que puede iniciar sesión y
declarar ausencias de sus jugadores.

Modelo de acceso:
  * `--todos`  → el entrenador gestiona a TODOS los jugadores activos.
                 Es el caso de Sergio hoy (único entrenador con acceso).
  * sin `--todos` → parte sin jugadores; se le asignan luego en el admin
                 (Entrenador.jugadores_gestionados) o vía UI.

Ejemplos:
    python manage.py seed_coach --nombre Sergio --username sergio --todos
    python manage.py seed_coach --nombre Sergio --username sergio --todos \
        --password "una-clave-de-dev"

Si no se pasa `--password`, el usuario se crea sin contraseña utilizable; hay
que fijarla con:  python manage.py changepassword <username>
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from academy.models import Entrenador
from users.models import User


class Command(BaseCommand):
    help = "Crea/actualiza un usuario entrenador enlazado a su Entrenador."

    def add_arguments(self, parser):
        parser.add_argument("--nombre", required=True, help="Nombre visible.")
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", default="")
        parser.add_argument("--password", default=None)
        parser.add_argument(
            "--todos", action="store_true",
            help="Da acceso a declarar ausencias de todos los jugadores.",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        username = opts["username"].strip()
        if not username:
            raise CommandError("username vacío.")

        user, u_created = User.objects.get_or_create(
            username=username,
            defaults={
                "role": User.Role.ENTRENADOR,
                "email": opts["email"],
                "first_name": opts["nombre"].split(" ")[0],
            },
        )
        # Aseguramos rol y datos aunque ya existiera.
        user.role = User.Role.ENTRENADOR
        if opts["email"]:
            user.email = opts["email"]
        if opts["password"]:
            user.set_password(opts["password"])
        elif u_created:
            user.set_unusable_password()
        user.save()

        # Enlaza (o crea) el Entrenador. Preferimos reutilizar uno homónimo
        # ya existente (p. ej. sembrado desde la parrilla) antes que duplicar.
        entrenador = getattr(user, "entrenador", None)
        if entrenador is None:
            entrenador = (
                Entrenador.objects.filter(user__isnull=True, nombre__iexact=opts["nombre"]).first()
                or Entrenador(nombre=opts["nombre"])
            )
        entrenador.nombre = opts["nombre"]
        entrenador.user = user
        entrenador.activo = True
        if opts["todos"]:
            entrenador.gestiona_todos_jugadores = True
        entrenador.save()

        alcance = (
            "TODOS los jugadores"
            if entrenador.gestiona_todos_jugadores
            else f"{entrenador.jugadores_gestionados.count()} jugadores asignados"
        )
        self.stdout.write(self.style.SUCCESS(
            f"Entrenador '{entrenador.nombre}' "
            f"({'creado' if u_created else 'actualizado'}) · "
            f"usuario '{user.username}' · acceso: {alcance}."
        ))
        if not opts["password"] and u_created:
            self.stdout.write(self.style.WARNING(
                f"Sin contraseña. Fíjala con: "
                f"python manage.py changepassword {user.username}"
            ))
