"""Trae a esta base los datos de jugadores que se han tocado en producción.

En producción se edita la ficha de los alumnos a diario —fechas de nacimiento,
teléfonos, consentimientos, cambios de escuela, altas nuevas— y ese es el dato
bueno. Aquí, en cambio, se prueban cosas contra la base del curso. Sin una
forma de traerse lo de allí, el desarrollo va contra datos viejos y cualquier
importación de Excel pisa el trabajo de dirección.

Este comando solo LEE de producción y solo ESCRIBE aquí. No borra a nadie, no
da de baja a nadie y no toca nada que producción no traiga: si un alumno existe
allí y aquí, se actualiza campo a campo; si solo existe allí, se crea; si solo
existe aquí (los alumnos del curso de septiembre que no están en producción),
se deja como está.

El emparejamiento va por `codigo_cliente`, que es la clave del software de
gestión de la escuela y no cambia. Solo si no hay código se prueba por nombre
normalizado.

Uso:
    python manage.py traer_jugadores_prod --token <token> --dry-run
    python manage.py traer_jugadores_prod --token <token>
    python manage.py traer_jugadores_prod --fichero prod.json

El token es el de un usuario de dirección en producción; se saca con
    curl -X POST https://<api>/api/auth/token/ -d '{"username":..,"password":..}'
"""
import json
import unicodedata
import urllib.request

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from academy.models import Division, Escuela, Jugador

API_PROD = "https://gtennis-api-jesus.fly.dev/api"

# Lo que se trae de producción. El resto de la ficha (turnos, horario, dosis de
# entrenamiento) es de aquí y no se toca: producción no lo usa.
CAMPOS = [
    "nombre", "fecha_nacimiento", "edad", "email", "telefono",
    "consentimiento_rgpd", "categoria", "foto_url", "notas",
    "fecha_alta", "fecha_baja",
]


def clave(nombre):
    """Nombre normalizado para comparar: sin acentos, sin mayúsculas, sin
    espacios de más."""
    txt = unicodedata.normalize("NFKD", nombre or "")
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return " ".join(txt.lower().split())


class Command(BaseCommand):
    help = "Trae de producción los datos de ficha de los jugadores."

    def add_arguments(self, parser):
        parser.add_argument("--url", default=API_PROD, help="API de producción.")
        parser.add_argument("--token", help="Token DRF de un usuario de dirección.")
        parser.add_argument(
            "--fichero",
            help="JSON ya descargado (lo que devuelve /api/jugadores/).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Enseña lo que cambiaría sin escribir nada.",
        )
        parser.add_argument(
            "--crear", action="store_true",
            help="Da de alta aquí a los alumnos que solo existen en producción.",
        )

    # -- lectura de producción -------------------------------------------
    def _descargar(self, url, token):
        filas, siguiente = [], f"{url.rstrip('/')}/jugadores/?limit=200"
        while siguiente:
            pet = urllib.request.Request(
                siguiente, headers={"Authorization": f"Token {token}"}
            )
            with urllib.request.urlopen(pet, timeout=60) as r:
                datos = json.loads(r.read().decode())
            if isinstance(datos, list):
                return datos
            filas.extend(datos.get("results", []))
            siguiente = datos.get("next")
        return filas

    @staticmethod
    def _parecidos(nombre, por_nombre):
        """Quién de aquí puede ser esta persona.

        Producción guarda el nombre completo ("Arrow Meister") y aquí quedó el
        de la lista de Iván ("Arrow 12"). Emparejarlos a ojo es peligroso, así
        que no se hace solo: se enseñan los candidatos y decide una persona.
        """
        partes = set(clave(nombre).split())
        candidatos = [
            n for n in por_nombre
            if partes & set(n.split()) and len(partes & set(n.split())) >= 1
        ]
        if not candidatos:
            return "no creado (usa --crear)"
        return "¿es " + " / ".join(
            por_nombre[c].nombre for c in sorted(candidatos)[:3]
        ) + "?"

    def handle(self, *args, **op):
        seco = op["dry_run"]
        if op["fichero"]:
            with open(op["fichero"], encoding="utf-8") as f:
                datos = json.load(f)
            prod = datos["results"] if isinstance(datos, dict) else datos
        else:
            if not op["token"]:
                raise CommandError("Hace falta --token o --fichero.")
            prod = self._descargar(op["url"], op["token"])

        w = self.stdout.write
        w(f"Producción: {len(prod)} jugadores activos.")

        locales = list(Jugador.objects.select_related("escuela", "division"))
        por_codigo = {j.codigo_cliente: j for j in locales if j.codigo_cliente}
        por_nombre = {}
        for j in locales:
            por_nombre.setdefault(clave(j.nombre), j)
        escuelas = {clave(e.nombre): e for e in Escuela.objects.all()}
        divisiones = {d.nivel: d for d in Division.objects.all()}

        cambios, altas, sin_escuela = [], [], set()

        with transaction.atomic():
            for p in prod:
                jug = por_codigo.get(p.get("codigo_cliente")) or \
                    por_nombre.get(clave(p.get("nombre")))
                nuevo = jug is None
                if nuevo:
                    if not op["crear"]:
                        altas.append((p.get("nombre"), self._parecidos(
                            p.get("nombre"), por_nombre
                        )))
                        continue
                    jug = Jugador(nombre=p["nombre"], activo=True)
                    altas.append((p.get("nombre"), "alta"))

                tocados = []
                for campo in CAMPOS:
                    if campo not in p:
                        continue  # producción todavía no tiene ese campo
                    valor = p[campo]
                    if campo in ("email", "telefono", "foto_url", "notas"):
                        valor = valor or ""
                        # Un vacío en producción no borra lo que haya aquí.
                        if not valor:
                            continue
                    if valor is None:
                        continue
                    actual = getattr(jug, campo, None)
                    if campo in ("fecha_nacimiento", "fecha_alta", "fecha_baja"):
                        actual = actual.isoformat() if actual else None
                    if actual != valor:
                        tocados.append(f"{campo}: {actual!r} → {valor!r}")
                        setattr(jug, campo, valor)

                # Escuela y división viajan por nombre/nivel, no por id: los ids
                # de producción y los de aquí no tienen por qué coincidir.
                nombre_escuela = p.get("escuela_nombre")
                if nombre_escuela:
                    escuela = escuelas.get(clave(nombre_escuela))
                    if escuela is None:
                        sin_escuela.add(nombre_escuela)
                    elif jug.escuela_id != escuela.id:
                        tocados.append(
                            f"escuela: {jug.escuela.nombre if jug.escuela_id else None!r}"
                            f" → {escuela.nombre!r}"
                        )
                        jug.escuela = escuela
                nivel = p.get("division_nivel")
                if nivel and divisiones.get(nivel) and jug.division_id != divisiones[nivel].id:
                    tocados.append(f"división: {jug.division_id and jug.division.nivel} → {nivel}")
                    jug.division = divisiones[nivel]
                if p.get("codigo_cliente") and not jug.codigo_cliente:
                    jug.codigo_cliente = p["codigo_cliente"]
                    tocados.append(f"codigo_cliente: → {p['codigo_cliente']}")

                if tocados and not seco:
                    jug.save()
                if tocados:
                    cambios.append((p.get("nombre"), tocados))
            if seco:
                transaction.set_rollback(True)

        w(self.style.MIGRATE_HEADING(f"\nFICHAS ACTUALIZADAS ({len(cambios)})"))
        for nombre, tocados in cambios:
            w(f"  {nombre}")
            for t in tocados:
                w(f"      {t}")
        if altas:
            w(self.style.MIGRATE_HEADING(f"\nSOLO EN PRODUCCIÓN ({len(altas)})"))
            w("  No se crean solos: casi siempre son el mismo alumno con el")
            w("  nombre más completo. Ponles el código de cliente aquí y")
            w("  volverán a emparejar, o créalos con --crear.")
            for nombre, que in altas:
                w(f"  {nombre}  [{que}]")
        if sin_escuela:
            w(self.style.WARNING(
                f"\nEscuelas de producción que aquí no existen: {', '.join(sin_escuela)}"
            ))
        if seco:
            w(self.style.WARNING("\n(dry-run: no se ha escrito nada)"))
