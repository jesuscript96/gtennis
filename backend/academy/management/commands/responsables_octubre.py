"""Accesos y responsables según la foto del club del 01/10/2026.

  1. Jorge García pasa a dirección (SUPERADMIN); conserva su ficha.
  2. Tres coaches, cada uno solo de su grupo (Dani, Pablo y Santi). Sergio e
     Iván Gallego siguen con los 18.
  3. Gestión: Nik Guilin, Huaqi Li y Valentina pasan de Nacho a Santi, y
     Tomkin Deng vuelve a la lista con Santi. Valentina y Tomkin «no
     entrenan»: siguen en la lista pero con fecha de baja, así que el motor no
     les pone.
  4. Carlos López pierde los porcentajes repartidos entre 17 entrenadores:
     sin porcentajes entrena con su responsable (Víctor).

Idempotente. Uso:
    python manage.py responsables_octubre            # ensayo, no guarda
    python manage.py responsables_octubre --aplicar
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from academy.models import Coach, Entrenador, Jugador, ResponsableJugador
from users.models import User

GRUPOS = {
    "daniel.gimeno": ("Daniel Gimeno", ["Daniel Gimeno", "Victor Redondo",
                      "Blas Gallego", "Javi Gimenez", "Emilio Sorio"]),
    "pablo.gil": ("Pablo Gil", ["Pablo Gil", "Mario Muniesa", "Jorge Ibañez",
                  "Salva Barcala"]),
    "santi.panzarassa": ("Santi Panzarasa", ["Santi Panzarasa",
                         "Patricio rodriguez", "Nacho Calvo"]),
}
A_SANTI = ["Xu Guilin (Yu) Nik", "Huaqi Li (Yu)", "Valentina Andrea"]
NO_ENTRENAN = ["Valentina Andrea", "Tomkin Deng"]
BAJA = date(2026, 10, 1)


def _ent(nombre):
    try:
        return Entrenador.objects.get(nombre__iexact=nombre)
    except Entrenador.DoesNotExist:
        raise CommandError(f"No encuentro al entrenador «{nombre}»")


def _jug(nombre):
    qs = Jugador.objects.filter(nombre__iexact=nombre)
    if nombre == "Tomkin Deng":
        qs = qs.filter(codigo_cliente__isnull=False)
    if qs.count() != 1:
        raise CommandError(f"«{nombre}»: {qs.count()} fichas")
    return qs.get()


class Command(BaseCommand):
    help = "Accesos y responsables según la foto del 01/10/2026."

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true")

    def handle(self, *args, aplicar=False, **opts):
        with transaction.atomic():
            self._cambios()
            if not aplicar:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Ensayo: no se ha guardado nada."))

    def _cambios(self):
        w = self.stdout.write

        jorge = User.objects.get(username="jorge.garcia")
        if jorge.role != User.Role.SUPERADMIN:
            jorge.role = User.Role.SUPERADMIN
            jorge.save(update_fields=["role"])
        w(f"jorge.garcia → {jorge.role}")

        for username, (nombre, miembros) in GRUPOS.items():
            user = User.objects.get(username=username)
            if user.role != User.Role.COACH:
                user.role = User.Role.COACH
                user.save(update_fields=["role"])
            coach = getattr(user, "coach", None) or Coach.objects.create(
                user=user, nombre=nombre)
            coach.activo = True
            coach.save(update_fields=["activo"])
            coach.entrenadores.set([_ent(n) for n in miembros])
            # Ve a su grupo, no a toda la academia.
            ficha = getattr(user, "entrenador", None)
            if ficha is not None and ficha.gestiona_todos_jugadores:
                ficha.gestiona_todos_jugadores = False
                ficha.save(update_fields=["gestiona_todos_jugadores"])
            w(f"{username} → coach de {', '.join(miembros)}")

        santi = _ent("Santi Panzarasa")
        for nombre in A_SANTI:
            j = _jug(nombre)
            j.entrenador_responsable = santi
            j.save(update_fields=["entrenador_responsable"])
            w(f"{j.nombre} → gestiona Santi")

        for nombre in NO_ENTRENAN:
            j = _jug(nombre)
            j.activo = True
            j.entrenador_responsable = santi
            if j.fecha_baja is None or j.fecha_baja >= date.today():
                j.fecha_baja = BAJA
            j.save(update_fields=["activo", "entrenador_responsable", "fecha_baja"])
            w(f"{j.nombre} → en la lista, no entrena (baja {j.fecha_baja})")

        carlos = _jug("Carlos López Montagud")
        n, _ = ResponsableJugador.objects.filter(jugador=carlos).delete()
        w(f"Carlos López: {n} porcentajes fuera; entrena con "
          f"{carlos.entrenador_responsable}")
