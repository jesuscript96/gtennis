"""Lo evaluado antes de «empezar de cero» (19/11/2026), para consultarlo al rehacer.

La migración 0015 borró las evaluaciones y los informes de entonces, pero las
dejó enteras en `ArchivoMigracion`. Los entrenadores echaron de menos esa
información (sus comentarios, sus notas, sus fortalezas): aquí se lee de ese
archivo, solo para enseñarla mientras se hace la evaluación nueva. No se
restaura nada ni se mezcla con las evaluaciones de ahora.
"""
from users.models import ArchivoMigracion

MIGRACION = "evaluaciones.0015_empezar_de_cero"


def _ultima(jugador_id, modelo):
    """La fila archivada más reciente (por fecha de evaluación) de ese jugador."""
    filas = ArchivoMigracion.objects.filter(migracion=MIGRACION, accion="borrado", modelo=modelo,
                                            datos__jugador_id=jugador_id)
    return max(filas, key=lambda e: (e.datos.get("fecha") or "", int(e.pk_original)), default=None)


def tenis(jugador_id):
    """La última evaluación de tenis archivada de ese jugador, o None."""
    e = _ultima(jugador_id, "evaluaciones.evaluacion")
    if e is None:
        return None
    d = e.datos
    return {
        "fecha": d.get("fecha"), "evaluador": d.get("nombre_evaluador") or "", "escala": d.get("escala") or 5,
        "terminada": d.get("estado") == "TERMINADA",
        "puntuaciones": d.get("puntuaciones") or {},
        "comentarios": {k: {"original": (v or {}).get("original", ""), "pulido": (v or {}).get("pulido", "")}
                        for k, v in (d.get("comentarios") or {}).items()},
        "fortalezas": d.get("fortalezas") or [], "mejoras": d.get("mejoras") or [],
        "fortalezas_original": d.get("fortalezas_original") or [], "mejoras_original": d.get("mejoras_original") or [],
    }


def fisica(jugador_id):
    """La última evaluación física archivada de ese jugador, o None."""
    e = _ultima(jugador_id, "evaluaciones.evaluacionfisica")
    if e is None:
        return None
    d = e.datos
    return {
        "fecha": d.get("fecha"), "evaluador": d.get("nombre_evaluador") or "", "escala": d.get("escala") or 5,
        "terminada": d.get("estado") == "TERMINADA",
        "puntuaciones": d.get("puntuaciones") or {}, "textos": d.get("textos") or {},
    }
