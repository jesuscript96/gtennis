"""El informe en PDF: lo que se guarda en Drive y lo que se enviará a las familias.

Se maqueta en HTML (`informe/informe.html`) y WeasyPrint lo pasa a PDF. Los
textos fijos van en el idioma del informe; los nombres de bloque y criterio
salen del catálogo.
"""
import base64
import logging
import math
import re
from pathlib import Path

from django.template import Context, Template
from django.utils import timezone

from . import catalogo

log = logging.getLogger(__name__)

CARPETA = Path(__file__).parent / "informe"
# Perímetro del anillo de cada bloque en la portada (r = 26 en la plantilla).
PERIMETRO = 2 * math.pi * 26

TEXTOS = {
    "ES": {
        "lang": "es", "informe": "Informe de rendimiento", "academia": "Alto rendimiento",
        "evaluado": "Evaluado por", "media": "Media global", "sobre": "sobre 5",
        "nota_media": "Media de las 34 notas, del 1 al 5, que ha puesto el entrenador.",
        "por_bloque": "Rendimiento por bloque", "punto_fuerte": "Punto fuerte", "a_trabajar": "A trabajar",
        "escala_corta": "34 aspectos puntuados del 1 al 5 por su entrenador.", "fortalezas": "Fortalezas", "mejoras": "Áreas de mejora",
        "competicion": "Competición", "detalle": "Detalle por bloque",
        "escala": "Cada aspecto se puntúa del 1 al 5. Debajo, el comentario del entrenador.",
        "sin_observaciones": "Sin observaciones", "sin_resultados": "Sin resultados registrados",
        "fisico_titulo": "Preparación física", "fisico_sub": "Evaluación trimestral del preparador físico. Cada aspecto del 1 al 5.",
        "tenis": "Tenis", "preparador": "Preparación física", "vs_anterior": "vs. informe anterior",
        "academia_tardes": "Competición de tardes",
        "meses": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                  "septiembre", "octubre", "noviembre", "diciembre"],
    },
    "EN": {
        "lang": "en", "informe": "Performance report", "academia": "High performance",
        "evaluado": "Assessed by", "media": "Overall average", "sobre": "out of 5",
        "nota_media": "Average of the 34 scores, from 1 to 5, given by the coach.",
        "por_bloque": "Performance by area", "punto_fuerte": "Strongest area", "a_trabajar": "Focus area",
        "escala_corta": "34 aspects scored from 1 to 5 by the coach.", "fortalezas": "Strengths", "mejoras": "Areas to improve",
        "competicion": "Competition", "detalle": "Detail by area",
        "escala": "Each aspect is scored from 1 to 5. Below, the coach's comment.",
        "sin_observaciones": "No observations", "sin_resultados": "No results recorded",
        "fisico_titulo": "Physical preparation", "fisico_sub": "Quarterly assessment by the strength and conditioning coach. Each aspect from 1 to 5.",
        "tenis": "Tennis", "preparador": "Physical preparation", "vs_anterior": "vs. previous report",
        "academia_tardes": "Afternoon competition",
        "meses": ["January", "February", "March", "April", "May", "June", "July", "August",
                  "September", "October", "November", "December"],
    },
}


def _num(valor, idioma):
    if valor is None:
        return "—"
    texto = f"{valor:.1f}"
    return texto.replace(".", ",") if idioma == "ES" else texto


def _fecha(d, t):
    mes = t["meses"][d.month - 1]
    return f"{d.day} de {mes} de {d.year}" if t["lang"] == "es" else f"{d.day} {mes} {d.year}"


def nombre(ev):
    """`Xu Guilin-22-07-2026-EN.pdf`"""
    jugador = re.sub(r'[\\/:*?"<>|]', "", ev.jugador.nombre).strip()
    return f"{jugador}-{ev.fecha:%d-%m-%Y}-{ev.idioma}.pdf"


def _iniciales(nombre):
    """Las dos primeras letras de nombre y apellido, sin comillas ni signos."""
    palabras = [p for p in nombre.split() if any(c.isalpha() for c in p)]
    return "".join(next(c for c in p if c.isalpha()) for p in palabras[:2]).upper()


def _foto(jugador):
    """La foto del jugador incrustada (data URI). Si no tiene o no se puede
    bajar, la plantilla pone sus iniciales en el mismo hueco."""
    url = getattr(jugador, "foto_url", "")
    if not url:
        return ""
    try:
        import requests

        r = requests.get(url, timeout=6)
        tipo = r.headers.get("Content-Type", "").split(";")[0]
        if r.ok and tipo.startswith("image/") and len(r.content) < 8_000_000:
            return f"data:{tipo};base64,{base64.b64encode(r.content).decode()}"
    except Exception:
        log.warning("No se ha podido bajar la foto de %s", jugador, exc_info=True)
    return ""


def datos(ev):
    """Todo lo que pinta la plantilla, ya calculado y formateado."""
    t = TEXTOS[ev.idioma]
    en = ev.idioma == "EN"
    bloques = []
    for i, b in enumerate(catalogo.BLOQUES, 1):
        notas = [ev.puntuaciones.get(k) for k, _, _ in b["criterios"]]
        puestas = [n for n in notas if n]
        media = sum(puestas) / len(puestas) if puestas else None
        bloques.append({
            "n": i,
            "titulo": b["titulo_en"] if en else b["titulo"],
            "corto": b["corto_en"] if en else b["corto"],
            "media_num": media,
            "media": _num(media, ev.idioma),
            # Como texto: Django pintaría los decimales con coma y el SVG/CSS no lo entiende.
            "ancho": f"{(media or 0) / 5 * 100:.1f}",
            "arco": f"{(media or 0) / 5 * PERIMETRO:.2f}",
            "comentario": (ev.comentarios.get(b["clave"]) or {}).get("pulido", ""),
            "criterios": [{
                "etiqueta": en_ if en else es,
                "nota": n or "—",
                "segmentos": [bool(n) and i < n for i in range(5)],
            } for (_, es, en_), n in zip(b["criterios"], notas)],
        })
    todas = [n for n in ev.puntuaciones.values() if n]
    ordenados = sorted(bloques, key=lambda b: -(b["media_num"] or 0))
    # El pie va dentro de una regla CSS: se escapa como CSS, no como HTML.
    pie = f"G Tenis · {t['informe']} · {ev.jugador.nombre}"
    pie = re.sub(r"[<>]", "", pie).replace("\\", "\\\\").replace('"', '\\"')
    return {
        "t": t,
        "pie": pie,
        "jugador": ev.jugador.nombre,
        "entrenador": ev.nombre_evaluador,
        "fecha": _fecha(ev.fecha, t),
        "media": _num(sum(todas) / len(todas) if todas else None, ev.idioma),
        "bloques": bloques,
        "pares": [bloques[i:i + 2] for i in range(0, len(bloques), 2)],
        "filas_anillos": [bloques[:4], bloques[4:]],
        "mejor": ordenados[0],
        "peor": ordenados[-1],
        "ordenados": ordenados,
        "iniciales": _iniciales(ev.jugador.nombre),
        "foto": _foto(ev.jugador),
        "fortalezas": [f for f in ev.fortalezas if f.strip()],
        "mejoras": [m for m in ev.mejoras if m.strip()],
        "competicion": (ev.comentarios.get(catalogo.COMPETICION) or {}).get("pulido", ""),
    }


def html(ev):
    plantilla = Template((CARPETA / "informe.html").read_text(encoding="utf-8"))
    return plantilla.render(Context(datos(ev)))


def generar(ev):
    """Los bytes del PDF."""
    from weasyprint import HTML  # carga pango: solo cuando de verdad se genera

    return HTML(string=html(ev), base_url=str(CARPETA)).write_pdf()


# --- Informe conjunto de Competición de tardes (27/10/2026) -----------------

def _foto_subida(jugador):
    from .models import FotoJugador

    f = FotoJugador.objects.filter(jugador=jugador).first()
    if f is None:
        return ""
    return f"data:{f.tipo};base64,{base64.b64encode(bytes(f.imagen)).decode()}"


def _media(puntuaciones, claves):
    notas = [puntuaciones.get(k) for k in claves if puntuaciones.get(k)]
    return sum(notas) / len(notas) if notas else None


def _evol(actual, anterior, idioma):
    """Flecha y diferencia respecto al informe anterior («▲ 0,5»)."""
    if actual is None or anterior is None:
        return None
    d = actual - anterior
    if abs(d) < 0.05:
        return {"dir": "igual", "txt": "="}
    return {"dir": "sube" if d > 0 else "baja", "txt": f"{'▲' if d > 0 else '▼'} {_num(abs(d), idioma)}"}


def anterior(inf):
    """El último informe validado del jugador antes de este."""
    from .models import Informe

    qs = inf.jugador.informes.filter(estado=Informe.Estado.VALIDADO, validado_en__isnull=False).exclude(pk=inf.pk)
    if inf.validado_en:
        qs = qs.filter(validado_en__lt=inf.validado_en)
    return qs.order_by("-validado_en").select_related("tenis", "fisica").first()


def datos_fisico(inf, idioma):
    ev = inf.fisica
    en = idioma == "EN"
    previo = anterior(inf)
    prev_p = previo.fisica.puntuaciones if previo and previo.fisica else None
    bloques = []
    for b in catalogo.BLOQUES_FISICO:
        claves = [c[0] for c in b["criterios"]]
        media = _media(ev.puntuaciones, claves)
        bloques.append({
            "titulo": catalogo.FISICO_EN[b["clave"]] if en else b["titulo"],
            "corto": catalogo.CORTO_FISICO[b["clave"]][1 if en else 0],
            "media": _num(media, idioma),
            "arco": f"{(media or 0) / 5 * PERIMETRO:.2f}",
            "evol": _evol(media, _media(prev_p, claves) if prev_p else None, idioma),
            "criterios": [{
                "etiqueta": catalogo.FISICO_EN[k] if en else e,
                "nota": ev.puntuaciones.get(k) or "—",
                "segmentos": [bool(ev.puntuaciones.get(k)) and i < ev.puntuaciones.get(k) for i in range(5)],
            } for k, e, _ in b["criterios"]],
        })
    textos = inf.textos_fisico_traducidos if en and inf.textos_fisico_traducidos else ev.textos
    t = TEXTOS[idioma]
    return {
        "evaluador": ev.nombre_evaluador,
        "bloques": bloques,
        "textos": [{"etiqueta": catalogo.FISICO_EN[k] if en else e, "texto": textos.get(k, "")}
                   for k, e in catalogo.TEXTOS_FISICO],
        "sin_observaciones": t["sin_observaciones"],
    }


def datos_informe(inf):
    d = datos(inf.tenis)
    idioma = inf.tenis.idioma
    d["t"] = {**d["t"], "academia": d["t"]["academia_tardes"]}
    previo = anterior(inf)
    if previo and previo.tenis:
        for b, cat in zip(d["bloques"], catalogo.BLOQUES):
            claves = [c[0] for c in cat["criterios"]]
            b["evol"] = _evol(b["media_num"], _media(previo.tenis.puntuaciones, claves), idioma)
        actual = _media(inf.tenis.puntuaciones, catalogo.CRITERIOS)
        d["evol_media"] = _evol(actual, _media(previo.tenis.puntuaciones, catalogo.CRITERIOS), idioma)
    d["fisico"] = datos_fisico(inf, idioma) if inf.fisica else None
    d["foto"] = _foto_subida(inf.jugador) or d["foto"]
    if inf.validado_en:
        d["fecha"] = _fecha(timezone.localtime(inf.validado_en).date(), d["t"])
    return d


def nombre_informe(inf):
    jugador = re.sub(r'[\\/:*?"<>|]', "", inf.jugador.nombre).strip()
    fecha = timezone.localtime(inf.validado_en).date() if inf.validado_en else timezone.localdate()
    return f"{jugador}-{fecha:%d-%m-%Y}-{inf.tenis.idioma}.pdf"


def html_informe(inf):
    plantilla = Template((CARPETA / "informe.html").read_text(encoding="utf-8"))
    return plantilla.render(Context(datos_informe(inf)))


def generar_informe(inf):
    from weasyprint import HTML

    return HTML(string=html_informe(inf), base_url=str(CARPETA)).write_pdf()
