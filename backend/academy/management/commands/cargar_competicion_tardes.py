"""Carga los alumnos de Competición de tardes (21/10/2026).

Son alumnos que solo existen para los informes de rendimiento: van a la
escuela «Competición de tardes» (marcada `solo_informes`) y sus fichas se
quedan INACTIVAS, así que no entran al cuadrante, ni a faltas ni a grupos.

Lee un JSON (fuera del repositorio: lleva datos personales) con esta forma:

    {"jugadores": [{"codigo": 12105, "nombre": "…", "nacimiento": "03/12/2014",
                    "email": "…", "movil": "…", "alta": "01/09/2026",
                    "app_id": 126 | null}, …],
     "fusionar": [[152, 151]]}

`app_id` es la ficha que ya había (inactiva) y se reutiliza; sin él se busca
por código de cliente y, si no hay, se crea. Nunca toca una ficha activa: si
el emparejamiento apunta a un alumno que entrena, lo avisa y lo salta.
`fusionar` borra la primera ficha (duplicada) solo si no tiene nada colgando.

Uso:
    python manage.py cargar_competicion_tardes datos.json            # solo enseña qué haría
    python manage.py cargar_competicion_tardes datos.json --aplicar
"""
import json
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.deletion import Collector

from academy.models import Escuela, Jugador

ESCUELA = "Competición de tardes"


def _fecha(texto):
    return datetime.strptime(texto, "%d/%m/%Y").date() if texto else None


class Command(BaseCommand):
    help = "Carga los alumnos de Competición de tardes (solo informes) desde un JSON."

    def add_arguments(self, parser):
        parser.add_argument("fichero")
        parser.add_argument("--aplicar", action="store_true", help="Escribe los cambios (si no, solo los enseña).")

    def handle(self, fichero, aplicar=False, **opts):
        try:
            datos = json.load(open(fichero, encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise CommandError(f"No se puede leer {fichero}: {e}")
        with transaction.atomic():
            resumen = self._cargar(datos)
            if not aplicar:
                transaction.set_rollback(True)
        for linea in resumen:
            self.stdout.write(linea)
        self.stdout.write(self.style.SUCCESS("Aplicado.") if aplicar
                          else self.style.WARNING("Simulación: no se ha guardado nada (usa --aplicar)."))

    def _cargar(self, datos):
        out = []
        escuela, creada = Escuela.objects.get_or_create(
            nombre=ESCUELA, defaults={"solo_informes": True, "orden": 90})
        if not escuela.solo_informes:
            escuela.solo_informes = True
            escuela.save(update_fields=["solo_informes"])
        out.append(f"Escuela «{ESCUELA}»: {'creada' if creada else 'ya existía'} (solo informes).")

        # Primero las fusiones, para que el duplicado no estorbe al emparejar.
        for duplicado_id, queda_id in datos.get("fusionar", []):
            dup = Jugador.objects.filter(pk=duplicado_id).first()
            if dup is None:
                out.append(f"  Fusión #{duplicado_id}→#{queda_id}: el duplicado ya no existe.")
                continue
            if dup.activo:
                out.append(f"  ¡OJO! #{duplicado_id} «{dup.nombre}» está activo: no se borra.")
                continue
            col = Collector(using="default")
            col.collect([dup])
            colgando = sum(len(objs) for model, objs in col.data.items() if model is not Jugador)
            colgando += sum(qs.count() for qs in col.fast_deletes)
            if colgando:
                out.append(f"  ¡OJO! #{duplicado_id} «{dup.nombre}» tiene {colgando} registros asociados: no se borra.")
                continue
            dup.delete()
            out.append(f"  Fusión: borrada la ficha duplicada #{duplicado_id} «{dup.nombre}» (queda #{queda_id}).")

        creados = actualizados = saltados = 0
        for d in datos["jugadores"]:
            j = Jugador.objects.filter(codigo_cliente=d["codigo"]).first()
            if j is None and d.get("app_id"):
                j = Jugador.objects.filter(pk=d["app_id"]).first()
            if j is not None and j.activo:
                out.append(f"  ¡OJO! «{j.nombre}» (#{j.id}) está ACTIVO en el cuadrante: no se toca.")
                saltados += 1
                continue
            otro = Jugador.objects.filter(codigo_cliente=d["codigo"]).exclude(pk=getattr(j, "pk", None)).first()
            if otro is not None:
                out.append(f"  ¡OJO! El código {d['codigo']} ya lo tiene «{otro.nombre}» (#{otro.id}): se salta.")
                saltados += 1
                continue
            nuevo = j is None
            if nuevo:
                j = Jugador(activo=False)
            antes = j.nombre
            j.nombre = d["nombre"]
            j.codigo_cliente = d["codigo"]
            j.fecha_nacimiento = _fecha(d.get("nacimiento")) or j.fecha_nacimiento
            j.email = d.get("email") or j.email
            j.telefono = str(d.get("movil") or j.telefono or "")
            j.fecha_alta = _fecha(d.get("alta")) or j.fecha_alta
            j.escuela = escuela
            j.activo = False
            j.save()
            if nuevo:
                creados += 1
                out.append(f"  + Nuevo: «{j.nombre}» (#{j.id}).")
            else:
                actualizados += 1
                if antes != j.nombre:
                    out.append(f"  ~ #{j.id}: «{antes}» → «{j.nombre}».")
        out.append(f"Total: {creados} nuevos, {actualizados} fichas reutilizadas, {saltados} saltados. "
                   f"En la escuela: {Jugador.objects.filter(escuela=escuela).count()}, "
                   f"activos entre ellos: {Jugador.objects.filter(escuela=escuela, activo=True).count()}.")
        return out
