"""El fichero `clave=valor` del informe (apartado 9 de la especificación)."""
import re

from . import catalogo


def limpiar(valor):
    """Un valor en una sola línea y sin los caracteres que el formato no admite."""
    texto = re.sub(r"\s*[\r\n]+\s*", " | ", str(valor or "")).strip(" |")
    texto = re.sub(r'["“”«»\[\]]', "", texto)
    return re.sub(r"\s{2,}", " ", texto).strip()


def nombre(ev):
    """`Xu Guilin-22-07-2026-EN.txt`"""
    jugador = re.sub(r'[\\/:*?"<>|]', "", ev.jugador.nombre).strip()
    return f"{jugador}-{ev.fecha:%d-%m-%Y}-{ev.idioma}.txt"


def contenido(ev):
    sin_obs = catalogo.SIN_OBSERVACIONES[ev.idioma]
    grupos = [[
        f"player_name={limpiar(ev.jugador.nombre)}",
        f"coach_name={limpiar(ev.nombre_evaluador)}",
        f"eval_date={ev.fecha:%d-%m-%Y}",
    ]]
    for b in catalogo.BLOQUES:
        lineas = [f"{clave}={ev.puntuaciones.get(clave, '')}" for clave, _, _ in b["criterios"]]
        nota = (ev.comentarios.get(b["clave"]) or {}).get("pulido")
        lineas.append(f"{b['clave']}_notes={limpiar(nota) or sin_obs}")
        grupos.append(lineas)
    grupos.append([
        f"summary_strengths={' | '.join(limpiar(f) for f in ev.fortalezas if limpiar(f))}",
        f"summary_improvements={' | '.join(limpiar(m) for m in ev.mejoras if limpiar(m))}",
    ])
    comp = (ev.comentarios.get(catalogo.COMPETICION) or {}).get("pulido")
    grupos.append([f"competition_results={limpiar(comp) or catalogo.SIN_RESULTADOS[ev.idioma]}"])
    return "\n\n".join("\n".join(g) for g in grupos) + "\n"
