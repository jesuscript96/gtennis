"""Los torneos de un jugador en PDF (25/11/2026): el que se descarga desde su
página y el que va adjunto en el correo mensual a la familia.

Se maqueta en HTML (`plantilla/calendario.html`) y WeasyPrint lo pasa a PDF,
con las fuentes y fotos del informe de rendimiento (`evaluaciones/informe`).
Lo que no es para la familia (las notas internas) no sale.
"""
import re
from datetime import date
from pathlib import Path

from django.template import Context, Template

from .por_jugador import _fecha, resumen

PLANTILLA = Path(__file__).parent / "plantilla" / "calendario.html"
# Fuentes e imágenes compartidas con el informe de rendimiento.
RECURSOS = Path(__file__).resolve().parent.parent / "evaluaciones" / "informe"

MESES = {
    "ES": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre"],
    "EN": ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"],
}
MES3 = {
    "ES": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
    "EN": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}

TEXTOS = {
    "ES": {
        "lang": "es", "titulo": "Calendario de torneos", "club": "G Tenis Academy",
        "entrenador": "Entrenador", "categoria": "Categoría",
        "torneos": "Torneos", "confirmados": "Confirmados", "de": "de",
        "proximo_cierre": "Próximo cierre de inscripción", "sin_cierres": "Ninguna inscripción abierta",
        "confirmado": "Confirmado", "por_confirmar": "Por confirmar",
        "inscripcion_hasta": "Inscripción hasta", "quedan": "quedan {n} días", "queda_1": "queda 1 día",
        "hoy": "cierra hoy", "inscripcion_cerrada": "Inscripción cerrada", "sin_fecha": "Inscripción: sin fecha",
        "borrado": "Retirarse sin coste hasta el", "previa": "Previa", "fines": "Solo fines de semana",
        "acompana": "Acompaña", "vacio": "No tiene torneos por delante en estas fechas.",
        "normas": "Normas de torneos de G Tenis", "generado": "Generado el",
        "leyenda": "«Por confirmar»: el club aún está revisando esa inscripción.",
        "desde": "Torneos desde el {fecha}", "meses_correo": "Torneos de {m1} y {m2}",
    },
    "EN": {
        "lang": "en", "titulo": "Tournament calendar", "club": "G Tenis Academy",
        "entrenador": "Coach", "categoria": "Category",
        "torneos": "Tournaments", "confirmados": "Confirmed", "de": "of",
        "proximo_cierre": "Next entry deadline", "sin_cierres": "No open entries",
        "confirmado": "Confirmed", "por_confirmar": "To be confirmed",
        "inscripcion_hasta": "Entries until", "quedan": "{n} days left", "queda_1": "1 day left",
        "hoy": "closes today", "inscripcion_cerrada": "Entries closed", "sin_fecha": "Entry deadline: not set",
        "borrado": "Withdraw free of charge until", "previa": "Qualifying", "fines": "Weekends only",
        "acompana": "Coach travelling", "vacio": "No upcoming tournaments for these dates.",
        "normas": "G Tenis tournament rules", "generado": "Generated on",
        "leyenda": "“To be confirmed”: the club is still reviewing that entry.",
        "desde": "Tournaments from {fecha}", "meses_correo": "Tournaments in {m1} and {m2}",
    },
}


def textos(idioma):
    return TEXTOS.get(idioma, TEXTOS["ES"])


def fecha_larga(d, idioma="ES"):
    d = _fecha(d)
    mes = MESES[idioma][d.month - 1]
    return f"{d.day} de {mes} de {d.year}" if idioma == "ES" else f"{d.day} {mes} {d.year}"


def fecha_corta(d, idioma="ES"):
    d = _fecha(d)
    return f"{d.day} {MES3[idioma][d.month - 1]}"


def rango(ini, fin, idioma="ES"):
    ini, fin = _fecha(ini), _fecha(fin)
    if not fin or fin == ini:
        return fecha_corta(ini, idioma)
    if ini.month == fin.month:
        return f"{ini.day}–{fin.day} {MES3[idioma][ini.month - 1]}"
    return f"{fecha_corta(ini, idioma)} – {fecha_corta(fin, idioma)}"


def _bloque_fecha(f, idioma):
    """El sello de la izquierda de cada torneo: días grandes y el mes."""
    ini, fin = _fecha(f["fecha_inicio"]), _fecha(f["fecha_fin"])
    if ini.month == fin.month:
        dias = str(ini.day) if ini == fin else f"{ini.day}–{fin.day}"
        return {"dias": dias, "mes": MES3[idioma][ini.month - 1], "largo": len(dias) > 5}
    return {"dias": f"{ini.day} {MES3[idioma][ini.month - 1]}", "mes": f"– {fin.day} {MES3[idioma][fin.month - 1]}",
            "largo": True}


def _cierre(f, t, idioma, hoy):
    cierre = _fecha(f["cierre_inscripcion"])
    if cierre is None:
        return {"clase": "sin", "etq": t["sin_fecha"], "fecha": "", "quedan": ""}
    if cierre < hoy:
        return {"clase": "cerrada", "etq": t["inscripcion_cerrada"], "fecha": fecha_corta(cierre, idioma), "quedan": ""}
    n = (cierre - hoy).days
    quedan = t["hoy"] if n == 0 else t["queda_1"] if n == 1 else t["quedan"].format(n=n)
    return {"clase": "abierta", "etq": t["inscripcion_hasta"], "fecha": fecha_corta(cierre, idioma), "quedan": quedan}


def normas_en_parrafos(texto):
    """Las normas tal como las escribe dirección: una línea que empieza por
    «-», «•» o «*» es un punto de una lista; lo demás, párrafos."""
    bloques, lista = [], None
    for linea in (texto or "").splitlines():
        limpia = linea.strip()
        if not limpia:
            lista = None
            continue
        m = re.match(r"^[-•*·]\s*(.+)$", limpia)
        if m:
            if lista is None:
                lista = {"lista": []}
                bloques.append(lista)
            lista["lista"].append(m.group(1))
        else:
            lista = None
            bloques.append({"texto": limpia})
    return bloques


def datos(jugador_ficha, filas, idioma="ES", subtitulo=None, normas="", foto=""):
    """Todo lo que pinta la plantilla, ya formateado."""
    t = textos(idioma)
    hoy = date.today()
    meses, actual = [], None
    for f in filas:
        ini = _fecha(f["fecha_inicio"])
        clave = (ini.year, ini.month)
        if actual is None or actual["clave"] != clave:
            actual = {"clave": clave, "nombre": f"{MESES[idioma][ini.month - 1]} {ini.year}", "torneos": []}
            meses.append(actual)
        previa = ""
        if f.get("qualy_inicio"):
            previa = f'{t["previa"]}: {rango(f["qualy_inicio"], f.get("qualy_fin") or f["qualy_inicio"], idioma)}'
        acompana = ", ".join(f.get("acompanantes") or []) or f.get("acompanante_nota") or ""
        actual["torneos"].append({
            "nombre": f["nombre"], "lugar": f.get("lugar") or "", "circuito": f.get("circuito") or "",
            "categorias": f.get("categorias") or [], "previa": previa,
            "fines": t["fines"] if f.get("solo_fines_semana") else "",
            "acompana": acompana, "fecha": _bloque_fecha(f, idioma),
            "confirmado": f["confirmado"], "cierre": _cierre(f, t, idioma, hoy),
            "borrado": (f'{t["borrado"]} {fecha_corta(f["fecha_borrado"], idioma)}'
                        if f.get("fecha_borrado") and _fecha(f["fecha_borrado"]) >= hoy else ""),
        })
    r = resumen(filas)
    return {
        "t": t, "jugador": jugador_ficha["nombre"], "foto": foto,
        "iniciales": "".join(p[0] for p in jugador_ficha["nombre"].split()[:2] if p).upper(),
        "entrenador": jugador_ficha.get("entrenador") or "", "categoria": jugador_ficha.get("categoria") or "",
        "subtitulo": subtitulo or t["desde"].format(fecha=fecha_larga(hoy, idioma)),
        "meses": meses, "r": r, "hay_pendientes": r["por_confirmar"] > 0,
        "proximo_cierre": fecha_corta(r["proximo_cierre"], idioma) if r["proximo_cierre"] else "",
        "normas": normas_en_parrafos(normas),
        "pie": f'{t["club"]} · {jugador_ficha["nombre"]} · {t["generado"]} {hoy:%d/%m/%Y}'.replace('"', "'"),
    }


class Contexto(Context):
    """Django 5.1 no sabe copiar un Context en Python 3.14 (`copy(super())`);
    lo copia el cliente de pruebas al pintar una plantilla dentro de una
    petición. Así se copia sin pasar por ahí."""

    def __copy__(self):
        nuevo = object.__new__(type(self))
        nuevo.__dict__ = self.__dict__.copy()
        nuevo.dicts = self.dicts[:]
        return nuevo


def pintar(plantilla, datos_):
    return Template(plantilla.read_text()).render(Contexto(datos_, autoescape=True))


def html(*args, **kwargs):
    return pintar(PLANTILLA, datos(*args, **kwargs))


def generar(*args, **kwargs):
    from weasyprint import HTML  # carga pango: solo cuando de verdad se genera

    return HTML(string=html(*args, **kwargs), base_url=str(RECURSOS)).write_pdf()


def nombre_fichero(jugador_nombre, sufijo=""):
    limpio = re.sub(r'[\\/:*?"<>|]', "", jugador_nombre).strip()
    return f"Torneos {limpio}{(' ' + sufijo) if sufijo else ''}.pdf"


def foto_de(jugador):
    """La foto incrustada, como en el informe; vacío si no tiene."""
    from evaluaciones.pdf import _foto, _foto_subida

    return _foto_subida(jugador) or _foto(jugador)
