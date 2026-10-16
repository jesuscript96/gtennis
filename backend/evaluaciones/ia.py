"""Las dos cosas del informe que hace Claude (apartados 7 y 10 de la especificación).

Todo lo demás —orden de los bloques, notas, validación, fichero— es código. Aquí
solo se pule la redacción de lo que dice el entrenador (sin cambiarle el
sentido) y se resumen tres fortalezas y tres mejoras a partir de sus notas y
comentarios. Si no hay clave de API o Claude falla, quien llama recibe
`IANoDisponible` y el informe sigue con el texto del entrenador tal cual.
"""
import json
import logging

import anthropic
from django.conf import settings

from . import catalogo

log = logging.getLogger(__name__)

MODELO = "claude-sonnet-5-5"

IDIOMA = {"ES": "español", "EN": "inglés"}


class IANoDisponible(Exception):
    pass


def _cliente():
    if not settings.ANTHROPIC_API_KEY:
        raise IANoDisponible("La IA no está activada.")
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=60, max_retries=2)


def _texto(respuesta):
    if respuesta.stop_reason == "refusal":
        raise IANoDisponible("Claude no ha querido procesar este texto.")
    texto = "".join(b.text for b in respuesta.content if b.type == "text").strip()
    if not texto:
        raise IANoDisponible("Claude no ha devuelto texto.")
    return texto


def _llamar(output_config=None, **kwargs):
    # Esfuerzo bajo: es pulir un párrafo o resumir una ficha, no hace falta pensar más.
    config = {"effort": "low", **(output_config or {})}
    try:
        return _cliente().messages.create(model=MODELO, output_config=config, **kwargs)
    except anthropic.AuthenticationError as e:
        log.error("Clave de la API de Claude rechazada: %s", e)
        raise IANoDisponible("La clave de la API de Claude no es válida. Se guarda el texto tal cual.") from e
    except anthropic.APIError as e:
        log.warning("Fallo de la API de Claude: %s", e)
        raise IANoDisponible("No se ha podido contactar con Claude. Se guarda el texto tal cual.") from e


SISTEMA_PULIR = """Eres el corrector de estilo de los informes de rendimiento de una academia de tenis de alta competición.

Un entrenador ha escrito o dictado un comentario sobre un jugador. Tu única tarea es dejarlo bien redactado para el informe:
- Corrige ortografía y gramática, ordena las frases y quita muletillas, repeticiones y titubeos del dictado.
- Respeta exactamente lo que dice el entrenador: sus ideas, sus matices y sus ejemplos concretos. No añadas información, valoraciones ni conclusiones que él no haya dicho, y no quites nada de lo que sí ha dicho.
- Si el dictado tiene una palabra mal transcrita y el contexto de tenis deja claro cuál era, corrígela (por ejemplo, «parece redacción» por «carece de reacción»).
- Escribe en tercera persona sobre el jugador, con un tono claro y profesional.
- Escribe el resultado en el idioma que se te indique; si el entrenador habló en otro, traduce fielmente sin reinterpretar.
- Devuelve un único párrafo, sin saltos de línea, sin comillas, sin corchetes y sin viñetas.

Responde solo con el texto final, sin presentaciones ni explicaciones."""


def pulir(texto, idioma, habilidad):
    """Redacción limpia del comentario del entrenador sobre `habilidad`, en `idioma` (ES/EN)."""
    respuesta = _llamar(
        max_tokens=4000,
        system=SISTEMA_PULIR,
        messages=[{
            "role": "user",
            "content": (f"Idioma del informe: {IDIOMA[idioma]}.\n"
                        f"Habilidad: {habilidad}.\n\n"
                        f"Comentario del entrenador:\n{texto}"),
        }],
    )
    return _texto(respuesta)


SISTEMA_RESUMIR = """Resumes evaluaciones de jugadores de una academia de tenis de alta competición.

Recibirás las notas (del 1 al 5) que un entrenador ha puesto en cada criterio y sus comentarios por bloque. Escribe exactamente tres fortalezas y tres áreas de mejora del jugador.
- Apóyate solo en lo que el entrenador ha indicado: los criterios con nota alta o elogiados en sus comentarios son candidatos a fortaleza; los de nota baja o con un fallo señalado, a mejora.
- No añadas juicios, causas, consejos ni conclusiones que el entrenador no haya expresado.
- Cada frase es breve (una línea), concreta y sin comillas, corchetes ni saltos de línea.
- Escribe en el idioma que se te indique."""

_ESQUEMA_RESUMEN = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in
                   ("fortaleza_1", "fortaleza_2", "fortaleza_3", "mejora_1", "mejora_2", "mejora_3")},
    "required": ["fortaleza_1", "fortaleza_2", "fortaleza_3", "mejora_1", "mejora_2", "mejora_3"],
    "additionalProperties": False,
}


def _volcado(ev):
    """La evaluación en texto llano para que Claude la lea."""
    lineas = []
    for b in catalogo.BLOQUES:
        lineas.append(f"## {b['titulo']}")
        for clave, etiqueta, _ in b["criterios"]:
            lineas.append(f"- {etiqueta}: {ev.puntuaciones.get(clave, '—')}")
        com = (ev.comentarios.get(b["clave"]) or {}).get("pulido")
        lineas.append(f"Comentario del entrenador: {com or 'ninguno'}")
        lineas.append("")
    comp = (ev.comentarios.get(catalogo.COMPETICION) or {}).get("pulido")
    lineas.append(f"## Resultados en competición\n{comp or 'ninguno'}")
    return "\n".join(lineas)


def resumir(ev):
    """(fortalezas, mejoras): tres frases cada una, en el idioma del informe."""
    respuesta = _llamar(
        max_tokens=8000,
        system=SISTEMA_RESUMIR,
        output_config={"format": {"type": "json_schema", "schema": _ESQUEMA_RESUMEN}},
        messages=[{
            "role": "user",
            "content": f"Idioma del informe: {IDIOMA[ev.idioma]}.\n\n{_volcado(ev)}",
        }],
    )
    try:
        datos = json.loads(_texto(respuesta))
    except json.JSONDecodeError as e:
        raise IANoDisponible("Claude ha devuelto un resumen que no se puede leer.") from e
    return ([datos[f"fortaleza_{i}"].strip() for i in (1, 2, 3)],
            [datos[f"mejora_{i}"].strip() for i in (1, 2, 3)])
