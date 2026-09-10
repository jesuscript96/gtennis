"""Fusiona fichas duplicadas de la misma persona.

Producción acumuló dos formas de nombrar a la gente: `setup_usuarios_prod` usa
el nombre completo del organigrama ("Daniel Gimeno", "Patricio Rodriguez") y el
cuadrante de la dirección usa el corto ("DANI GIMENO", "PATRICIO"). Al cargar
el organigrama de septiembre quedaron las dos, partidas por la mitad: el login
en una y los jugadores en la otra.

La fusión conserva SIEMPRE el registro con usuario —para no romper el acceso a
la app— y le arrastra todo lo del otro: divisiones, jugadores a su cargo,
contratos, asignaciones y equipos de coach. Después borra el vacío.

Las parejas van escritas a mano a propósito: emparejar por parecido de nombre
se equivocaría con "Jorge García" y "Jorge Milla", o con los dos Peñaranda.

Uso:
    python manage.py fusionar_duplicados --dry-run
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from academy.models import Coach, Entrenador, Jugador

# (se queda, se absorbe...) — el primero es el nombre que debe sobrevivir si
# ninguno de los dos tiene usuario.
ENTRENADORES = [
    ("JAVI GIMENEZ", ["Javier Gimenez"]),
    ("PATRICIO", ["Patricio Rodriguez"]),
    ("SANTI PANZARASA", ["Santi Panzarassa"]),
    ("MIKEL ROMERO", ["Miquel Romero"]),
]
COACHES = [
    ("DANI GIMENO", ["Daniel Gimeno"]),
    ("PABLO GIL", ["Pablo Gil", "PABLO"]),
    ("SANTI PANZARASA", ["Santi Panzarassa", "SANTI"]),
]
JUGADORES = [
    ("Dani Martins", ["Daniel Martins"]),
    ("Elina Avanesian", ["Elina Avanesyan"]),
    ("Ia Teporoca", ["Ia Teporaca"]),
    ("Yushuo Li 14 (chico)", ["Yushuo Li"]),
]
COACHES_A_BORRAR = ["Coach Demo"]


def _mover(origen, destino):
    """Reapunta a `destino` todo lo que colgaba de `origen`."""
    movidos = []
    # Primero los M2M PROPIOS del objeto (Coach.entrenadores,
    # Entrenador.divisiones_habilitadas, jugadores_gestionados). No aparecen
    # en `related_objects`, que solo trae lo que apunta hacia aquí, así que
    # sin esto se perdían: Patricio se quedó sin sus divisiones al fusionarlo.
    for campo in origen._meta.many_to_many:
        propios = set(getattr(destino, campo.name).all())
        ajenos = set(getattr(origen, campo.name).all())
        nuevos = ajenos - propios
        if nuevos:
            getattr(destino, campo.name).add(*nuevos)
            movidos.append(f"{campo.name}(+{len(nuevos)})")
    for rel in origen._meta.related_objects:
        acc = rel.get_accessor_name()
        campo = rel.field.name
        if rel.many_to_many:
            for obj in getattr(origen, acc).all():
                getattr(obj, campo).add(destino)
                getattr(obj, campo).remove(origen)
                movidos.append(f"{rel.related_model.__name__}(m2m)")
            continue
        qs = getattr(origen, acc).all() if hasattr(origen, acc) else []
        for obj in list(qs):
            # Evita chocar con los unique_together (jugador+entrenador, etc.).
            setattr(obj, campo, destino)
            try:
                with transaction.atomic():
                    obj.save()
                movidos.append(rel.related_model.__name__)
            except Exception:
                obj.delete()
                movidos.append(f"{rel.related_model.__name__}(dup)")
    return movidos


class Command(BaseCommand):
    help = "Fusiona fichas duplicadas de entrenadores, coaches y jugadores."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        with transaction.atomic():
            self._run(**opts)

    def _run(self, **opts):
        w = self.stdout.write
        seco = opts["dry_run"]

        for Modelo, parejas, etiqueta in (
            (Entrenador, ENTRENADORES, "ENTRENADORES"),
            (Coach, COACHES, "COACHES"),
            (Jugador, JUGADORES, "JUGADORES"),
        ):
            w(self.style.MIGRATE_HEADING(f"\n{etiqueta}"))
            for principal, absorbidos in parejas:
                # Comparación EXACTA, no `iexact`: "PABLO GIL" y "Pablo Gil"
                # son dos registros distintos en producción y con iexact se
                # colapsaban en uno, eligiendo mal cuál sobrevive.
                cands, vistos = [], set()
                for n in [principal] + absorbidos:
                    for c in Modelo.objects.filter(nombre=n):
                        if c.pk not in vistos:
                            vistos.add(c.pk)
                            cands.append(c)
                if len(cands) < 2:
                    w(f"  {principal:24s} nada que fusionar")
                    continue
                # Manda quien tenga usuario: romper el login sería peor que
                # tener el nombre en un formato u otro. Si ninguno lo tiene,
                # se queda el que encabeza la pareja.
                con_user = [c for c in cands if getattr(c, "user_id", None)]
                queda = con_user[0] if con_user else cands[0]
                otros = [c for c in cands if c.pk != queda.pk]
                login = getattr(getattr(queda, "user", None), "username", None)
                w(f"  {principal:24s} ← {', '.join(o.nombre for o in otros)}"
                  f"   (se queda la ficha de {queda.nombre}"
                  + (f", login {login}" if login else ", sin login") + ")")
                if seco:
                    continue
                for o in otros:
                    if getattr(queda, "user_id", None) is None and \
                            getattr(o, "user_id", None):
                        queda.user_id, o.user_id = o.user_id, None
                        o.save(update_fields=["user"])
                        queda.save(update_fields=["user"])
                    detalle = _mover(o, queda)
                    o.delete()
                    w(f"      absorbido, movido: {sorted(set(detalle))}")
                # El registro que sobrevive es el del login, pero el nombre
                # que se queda es el del organigrama: si no, el siguiente
                # `aplicar_grupos` volvería a crear la ficha duplicada.
                queda.nombre = principal
                queda.activo = True
                queda.save()

        for nombre in COACHES_A_BORRAR:
            c = Coach.objects.filter(nombre__iexact=nombre).first()
            if c and c.entrenadores.count() == 0:
                w(f"\n  borrado coach vacío: {c.nombre}")
                if not seco:
                    c.delete()

        w(self.style.MIGRATE_HEADING("\nRESULTADO"))
        w(f"  entrenadores: {Entrenador.objects.count()} "
          f"(activos {Entrenador.objects.filter(activo=True).count()})")
        w(f"  coaches: {Coach.objects.count()}")
        w(f"  jugadores activos: {Jugador.objects.filter(activo=True).count()}")
        if seco:
            w(self.style.WARNING("\n(dry-run: no se ha escrito nada)"))
            transaction.set_rollback(True)
