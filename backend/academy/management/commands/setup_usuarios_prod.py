"""Provisión de usuarios en PRODUCCIÓN según el organigrama real.

A diferencia de `setup_usuarios` (que usa nombres cortos de parrilla y fusiona
duplicados de dev), prod usa nombres completos y NO tiene duplicados que
fusionar, así que este comando solo provisiona (aditivo, sin borrar):

  1. Crea un usuario (rol ENTRENADOR) por cada entrenador del organigrama.
  2. Crea los 3 coaches con usuario y les asigna su equipo.
  3. Coach con jugadores propios (Pablo Gil, Santi Panzarassa): su propia ficha
     de entrenador entra en su equipo, así sigue viendo/gestionando a esos
     jugadores. Coach sin jugadores (Daniel Gimeno): su ficha se desactiva.
  4. Normaliza `admin` a SUPERADMIN.

Independientes (Alvaro Mantoan, Jorge Garcia, Ivan Gallego, Jorge Milla, Miquel
Romero, Ricardo Moscardo, Javier Sebastian) quedan activos, sin coach ni login.

Idempotente. Uso:
    python manage.py setup_usuarios_prod
    python manage.py setup_usuarios_prod --password XXXX
"""
import unicodedata

from django.core.management.base import BaseCommand
from django.db import transaction

from academy.models import Coach, Entrenador
from users.models import User

ORGANIGRAMA = {
    "Daniel Gimeno": ["Victor Redondo", "Sergio Gallego", "Javier Gimenez", "Emilio Sorio"],
    "Pablo Gil": ["Blas Gallego", "Mario Muniesa", "Jorge Ibañez", "Salva Barcala"],
    "Santi Panzarassa": ["Patricio Rodriguez", "Nacho Calvo"],
}
PASSWORD_DEFAULT = "gtennis2026"


def _slug(nombre):
    s = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    s = "".join(c if c.isalnum() else "." for c in s.strip().lower())
    while ".." in s:
        s = s.replace("..", ".")
    return s.strip(".")


def _ent(nombre):
    return Entrenador.objects.filter(nombre__iexact=nombre).first()


class Command(BaseCommand):
    help = "Provisiona coaches y usuarios de entrenador en producción (nombres completos)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default=PASSWORD_DEFAULT)
        parser.add_argument("--reset-passwords", action="store_true")

    def _ensure_user(self, nombre, role, password, reset):
        username = _slug(nombre)
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"role": role, "first_name": nombre.split(" ")[0]},
        )
        user.role = role
        if not user.first_name:
            user.first_name = nombre.split(" ")[0]
        if created or reset:
            user.set_password(password)
            self._creds.append((role, nombre, username, password))
        user.save()
        return user, created

    @transaction.atomic
    def handle(self, *args, **opts):
        password = opts["password"]
        reset = opts["reset_passwords"]
        self._creds = []

        self.stdout.write(self.style.MIGRATE_HEADING("1) Usuarios de entrenadores"))
        for nombre in [n for lst in ORGANIGRAMA.values() for n in lst]:
            ent = _ent(nombre)
            if ent is None:
                self.stdout.write(self.style.WARNING(f"  ¡no existe entrenador «{nombre}»!"))
                continue
            if ent.user_id:
                self.stdout.write(f"  ya tiene usuario: {nombre} ({ent.user.username})")
                continue
            user, _ = self._ensure_user(nombre, User.Role.ENTRENADOR, password, reset)
            ent.user = user
            ent.activo = True
            ent.save()
            self.stdout.write(self.style.SUCCESS(f"  {nombre} → {user.username}"))

        self.stdout.write(self.style.MIGRATE_HEADING("2) Coaches y equipos"))
        for coach_name, members in ORGANIGRAMA.items():
            user, _ = self._ensure_user(coach_name, User.Role.COACH, password, reset)
            coach, _ = Coach.objects.get_or_create(nombre=coach_name, defaults={"user": user})
            coach.user = user
            coach.activo = True
            coach.save()
            equipo = [e for e in (_ent(n) for n in members) if e is not None]
            # Coach con jugadores propios: incluir su ficha en el equipo; sin
            # jugadores: desactivar la ficha (coach puro).
            propia = _ent(coach_name)
            nota = ""
            if propia is not None:
                if propia.jugadores_responsable.exists():
                    equipo.append(propia)
                    propia.activo = True
                    propia.save()
                    nota = f" (+ su ficha con {propia.jugadores_responsable.count()} jug.)"
                else:
                    propia.activo = False
                    propia.user = None
                    propia.save()
                    nota = " (ficha propia sin jugadores → desactivada)"
            coach.entrenadores.set(equipo)
            nombres = ", ".join(e.nombre for e in equipo)
            self.stdout.write(self.style.SUCCESS(
                f"  {coach_name} → {user.username}  [{nombres}]{nota}"
            ))

        self.stdout.write(self.style.MIGRATE_HEADING("3) Normalizar admin"))
        admin = User.objects.filter(username="admin").first()
        if admin is not None:
            admin.role = User.Role.SUPERADMIN
            admin.save(update_fields=["role"])
            self.stdout.write("  admin → SUPERADMIN")

        if self._creds:
            self.stdout.write(self.style.MIGRATE_HEADING("Credenciales (CÁMBIALAS)"))
            for role, nombre, username, pwd in self._creds:
                self.stdout.write(f"  {role:10s} {nombre:18s} usuario={username:20s} contraseña={pwd}")
        else:
            self.stdout.write("\nSin usuarios nuevos (idempotente).")
        self.stdout.write(self.style.SUCCESS("\n✔ Provisión de usuarios en prod completada."))
