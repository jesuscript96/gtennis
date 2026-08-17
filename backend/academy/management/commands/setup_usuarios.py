"""Reconcilia el roster de entrenadores y provisiona los usuarios de la
academia según el organigrama real (dirección → coaches → entrenadores).

Qué hace (idempotente):
  1. Fusiona los entrenadores duplicados de la parrilla cuyo canónico está en
     el organigrama (p. ej. EMILIO S → EMILIO), reasignando sus referencias y
     desactivando el duplicado.
  2. Fusiona el login histórico `Sergio` (gestiona_todos) sobre `SERGIO G`
     (su cluster real) y lo convierte en un entrenador normal.
  3. Crea los 3 coaches (DANI GIMENO, PABLO, SANTI) con usuario y les asigna
     sus entrenadores. Desactiva el Coach Demo y las fichas de entrenador que
     en realidad son coaches (PABLO, SANTI y sus duplicados).
  4. Crea un usuario por cada entrenador del organigrama que no tenga.
  5. Normaliza la cuenta `admin` a rol SUPERADMIN.

Los entrenadores fuera del organigrama (ANNA, MIKEL, RICARDO, ALVARO/ALVARO M,
VICTOR M) quedan activos e independientes, sin coach ni usuario.

Uso:
    python manage.py setup_usuarios                 # contraseña temporal por defecto
    python manage.py setup_usuarios --password XXXX # fija esa contraseña a los nuevos
    python manage.py setup_usuarios --reset-passwords  # además resetea las ya existentes
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from academy.models import Coach, Contrato, Entrenador, Jugador, ResponsableJugador
from users.models import User

# Organigrama: coach → entrenadores (nombres canónicos, tal cual en la BD).
ORGANIGRAMA = {
    "DANI GIMENO": ["VICTOR R", "SERGIO G", "JAVI", "EMILIO"],
    "PABLO": ["BLAS", "MARIO", "JORGE I", "SALVA"],
    "SANTI": ["PATRICIO", "NACHO C"],
}

# Duplicados de parrilla a fusionar: duplicado (vacío) → canónico (con cluster).
# Solo los que tienen el canónico confirmado por el organigrama.
FUSIONES = {
    "EMILIO S": "EMILIO",
    "JAVI G": "JAVI",
    "JORGE": "JORGE I",
    "MARIO M": "MARIO",
    "SALVA B": "SALVA",
}

# Fichas de Entrenador que en realidad son coaches (o su duplicado): desactivar.
ENTRENADORES_QUE_SON_COACH = ["PABLO", "PABLO G", "SANTI", "SANTI P"]

PASSWORD_DEFAULT = "gtennis2026"


def _slug_username(nombre):
    base = "".join(c if c.isalnum() else "." for c in nombre.strip().lower())
    while ".." in base:
        base = base.replace("..", ".")
    return base.strip(".")


def _ent(nombre):
    return Entrenador.objects.filter(nombre__iexact=nombre).first()


class Command(BaseCommand):
    help = "Reconcilia entrenadores y provisiona usuarios (coaches/entrenadores)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default=PASSWORD_DEFAULT,
                            help="Contraseña temporal para los usuarios NUEVOS.")
        parser.add_argument("--reset-passwords", action="store_true",
                            help="También resetea la contraseña de usuarios existentes.")

    # --- helpers ---------------------------------------------------------
    def _merge(self, src, dst, *, clear_gestiona_todos=False):
        """Reasigna todas las referencias de `src` a `dst` y desactiva `src`."""
        from scheduling.models import Asignacion, DisponibilidadEntrenador

        if src is None or dst is None or src.pk == dst.pk:
            return
        # ResponsableJugador / Contrato: unique (jugador, entrenador).
        for Model in (ResponsableJugador, Contrato):
            for row in Model.objects.filter(entrenador=src):
                if Model.objects.filter(jugador=row.jugador, entrenador=dst).exists():
                    row.delete()
                else:
                    row.entrenador = dst
                    row.save(update_fields=["entrenador"])
        # FKs simples.
        Jugador.objects.filter(entrenador_responsable=src).update(entrenador_responsable=dst)
        src.vacaciones.update(entrenador=dst)
        src.invitados.update(entrenador_solicitante=dst)
        Asignacion.objects.filter(entrenador=src).update(entrenador=dst)
        for de in DisponibilidadEntrenador.objects.filter(entrenador=src):
            if DisponibilidadEntrenador.objects.filter(
                entrenador=dst, semana_id=de.semana_id, dia=de.dia
            ).exists():
                de.delete()
            else:
                de.entrenador = dst
                de.save(update_fields=["entrenador"])
        # M2M.
        for coach in src.coaches.all():
            coach.entrenadores.remove(src)
            coach.entrenadores.add(dst)
        for jug in src.jugadores_gestionados.all():
            dst.jugadores_gestionados.add(jug)
        for div in src.divisiones_habilitadas.all():
            dst.divisiones_habilitadas.add(div)
        # Usuario: mover el login si el destino no tiene.
        if src.user_id and not dst.user_id:
            u = src.user
            src.user = None
            src.save(update_fields=["user"])
            dst.user = u
            dst.save(update_fields=["user"])
        if clear_gestiona_todos:
            dst.gestiona_todos_jugadores = False
        dst.activo = True
        dst.save()
        # Desactivar el origen.
        src.user = None
        src.activo = False
        src.save()
        self.stdout.write(f"  fusionado: {src.nombre} → {dst.nombre}")

    def _ensure_user(self, *, nombre, role, password, reset):
        username = _slug_username(nombre)
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"role": role, "first_name": nombre.split(" ")[0]},
        )
        user.role = role
        if not user.first_name:
            user.first_name = nombre.split(" ")[0]
        if created or reset:
            user.set_password(password)
            self._creds.append((nombre, username, password, role))
        user.save()
        return user, created

    @transaction.atomic
    def handle(self, *args, **opts):
        password = opts["password"]
        reset = opts["reset_passwords"]
        self._creds = []

        self.stdout.write(self.style.MIGRATE_HEADING("1) Fusiones de duplicados"))
        for src_name, dst_name in FUSIONES.items():
            self._merge(_ent(src_name), _ent(dst_name))
        # Sergio (login gestiona_todos) → SERGIO G (cluster real), como normal.
        self._merge(_ent("Sergio"), _ent("SERGIO G"), clear_gestiona_todos=True)

        self.stdout.write(self.style.MIGRATE_HEADING("2) Fichas de entrenador que son coach"))
        for nombre in ENTRENADORES_QUE_SON_COACH:
            e = _ent(nombre)
            if e is not None and e.activo:
                e.activo = False
                e.user = None
                e.save()
                self.stdout.write(f"  desactivado como entrenador: {nombre}")

        self.stdout.write(self.style.MIGRATE_HEADING("3) Usuarios de entrenadores del organigrama"))
        entrenadores_org = [n for lst in ORGANIGRAMA.values() for n in lst]
        for nombre in entrenadores_org:
            ent = _ent(nombre)
            if ent is None:
                self.stdout.write(self.style.WARNING(f"  ¡no existe entrenador «{nombre}»!"))
                continue
            if ent.user_id:
                self.stdout.write(f"  ya tiene usuario: {nombre} ({ent.user.username})")
                continue
            user, _ = self._ensure_user(
                nombre=nombre, role=User.Role.ENTRENADOR, password=password, reset=reset
            )
            ent.user = user
            ent.activo = True
            ent.save()
            self.stdout.write(self.style.SUCCESS(f"  usuario entrenador: {nombre} → {user.username}"))

        self.stdout.write(self.style.MIGRATE_HEADING("4) Coaches y sus equipos"))
        # Desactivar coaches previos que no estén en el organigrama (p. ej. demo).
        for c in Coach.objects.exclude(nombre__in=ORGANIGRAMA.keys()):
            c.activo = False
            c.entrenadores.clear()
            c.save()
            self.stdout.write(f"  coach desactivado: {c.nombre}")
        for coach_name, ent_names in ORGANIGRAMA.items():
            user, _ = self._ensure_user(
                nombre=coach_name, role=User.Role.COACH, password=password, reset=reset
            )
            coach, _ = Coach.objects.get_or_create(
                nombre=coach_name, defaults={"user": user}
            )
            coach.user = user
            coach.activo = True
            coach.save()
            ents = [e for e in (_ent(n) for n in ent_names) if e is not None]
            coach.entrenadores.set(ents)
            self.stdout.write(self.style.SUCCESS(
                f"  coach: {coach_name} → {user.username}  [{', '.join(e.nombre for e in ents)}]"
            ))

        self.stdout.write(self.style.MIGRATE_HEADING("5) Normalizar cuenta admin"))
        admin = User.objects.filter(username="admin").first()
        if admin is not None:
            admin.role = User.Role.SUPERADMIN
            admin.save(update_fields=["role"])
            self.stdout.write("  admin → SUPERADMIN")

        # --- Reporte de credenciales -------------------------------------
        if self._creds:
            self.stdout.write(self.style.MIGRATE_HEADING("Credenciales (CÁMBIALAS)"))
            for nombre, username, pwd, role in self._creds:
                self.stdout.write(f"  {role:10s} {nombre:14s} usuario={username:14s} contraseña={pwd}")
        else:
            self.stdout.write("\nSin usuarios nuevos (idempotente).")

        self.stdout.write(self.style.SUCCESS("\n✔ Setup de usuarios completado."))
