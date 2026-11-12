"""Ayuda para que las migraciones de datos guarden en `ArchivoMigracion` lo
que cambian o borran y lo restauren exactamente al deshacerse (11/11/2026).

Lo usan migraciones ya escritas: no cambiar el formato de lo guardado.
"""
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID


def _json(v):
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, (Decimal, UUID)):
        return str(v)
    return v


def fila(obj, campos=None):
    """Los campos de la fila (por su nombre de columna: `jugador_id`…), listos
    para JSON. `campos` limita a unos cuantos (para «cambiado»)."""
    out = {}
    for f in obj._meta.concrete_fields:
        if campos is None or f.name in campos or f.attname in campos:
            out[f.attname] = _json(getattr(obj, f.attname))
    return out


def modelo_de(obj):
    return f"{obj._meta.app_label}.{obj._meta.model_name}"


def guardar(apps, migracion, accion, obj, campos=None):
    Archivo = apps.get_model("users", "ArchivoMigracion")
    return Archivo.objects.create(
        migracion=migracion, modelo=modelo_de(obj), pk_original=str(obj.pk), accion=accion,
        datos={} if accion == "creado" else fila(obj, campos))


def entradas(apps, migracion, accion=None):
    Archivo = apps.get_model("users", "ArchivoMigracion")
    qs = Archivo.objects.filter(migracion=migracion).order_by("id")
    return qs.filter(accion=accion) if accion else qs


def deshacer(apps, migracion):
    """Deshace lo archivado por `migracion`, en orden inverso: quita lo que
    creó, devuelve lo cambiado a como estaba y vuelve a poner lo borrado con su
    misma clave. Después borra sus entradas del archivo."""
    for e in reversed(list(entradas(apps, migracion))):
        Modelo = apps.get_model(*e.modelo.split("."))
        if e.accion == "creado":
            Modelo.objects.filter(pk=e.pk_original).delete()
        elif e.accion == "cambiado":
            Modelo.objects.filter(pk=e.pk_original).update(
                **{k: v for k, v in e.datos.items() if k != Modelo._meta.pk.attname})
        elif e.accion == "borrado":
            if not Modelo.objects.filter(pk=e.pk_original).exists():
                Modelo.objects.create(**e.datos)
                # `create` pone la hora de ahora en los campos automáticos
                # (creado, actualizado): se vuelven a dejar como estaban.
                Modelo.objects.filter(pk=e.pk_original).update(
                    **{k: v for k, v in e.datos.items() if k != Modelo._meta.pk.attname})
    entradas(apps, migracion).delete()
