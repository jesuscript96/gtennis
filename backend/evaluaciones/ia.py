"""Las dos cosas del informe que hace Claude (apartados 7 y 10 de la especificación).

Todo lo demás —orden de los bloques, notas, validación, fichero— es código. Aquí
solo se pule la redacción de lo que dice el entrenador (sin cambiarle el
sentido): sus comentarios por bloque y, desde el 02/11/2026, las fortalezas y
mejoras que escribe él (antes las proponía Claude a partir de las notas). Si no hay clave de API o Claude falla, quien llama recibe
`IANoDisponible` y el informe sigue con el texto del entrenador tal cual.
"""
import json
import logging

import anthropic
from django.conf import settings

log = logging.getLogger(__name__)

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
        return _cliente().messages.create(model=settings.ANTHROPIC_MODEL, output_config=config, **kwargs)
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


SISTEMA_FRASES = """Pasas a limpio las fortalezas y las áreas de mejora que un entrenador de una academia de tenis ha escrito sobre su jugador, para el informe que recibe la familia.

- Corrige ortografía y gramática y deja cada una como una frase breve (una línea), clara y profesional.
- Respeta lo que dice el entrenador: no añadas ideas, causas, consejos ni valoraciones, no juntes ni separes frases y no cambies su orden.
- Devuelve exactamente tantas fortalezas y tantas mejoras como recibes.
- Sin comillas, corchetes, viñetas ni saltos de línea.
- Escribe en el idioma que se te indique; si el entrenador escribió en otro, traduce fielmente."""

_ESQUEMA_FRASES = {
    "type": "object",
    "properties": {"fortalezas": {"type": "array", "items": {"type": "string"}},
                   "mejoras": {"type": "array", "items": {"type": "string"}}},
    "required": ["fortalezas", "mejoras"],
    "additionalProperties": False,
}


def pulir_frases(fortalezas, mejoras, idioma):
    """(fortalezas, mejoras) que escribió el entrenador, pasadas a limpio en `idioma`."""
    lista = lambda xs: "\n".join(f"- {x}" for x in xs) or "(ninguna)"
    respuesta = _llamar(
        max_tokens=4000,
        system=SISTEMA_FRASES,
        output_config={"format": {"type": "json_schema", "schema": _ESQUEMA_FRASES}},
        messages=[{
            "role": "user",
            "content": (f"Idioma del informe: {IDIOMA[idioma]}.\n\nFortalezas:\n{lista(fortalezas)}\n\n"
                        f"Áreas de mejora:\n{lista(mejoras)}"),
        }],
    )
    try:
        datos = json.loads(_texto(respuesta))
    except json.JSONDecodeError as e:
        raise IANoDisponible("Claude ha devuelto unas frases que no se pueden leer.") from e
    f = [x.strip() for x in datos.get("fortalezas", [])]
    m = [x.strip() for x in datos.get("mejoras", [])]
    if len(f) != len(fortalezas) or len(m) != len(mejoras) or not all(f + m):
        raise IANoDisponible("Claude no ha devuelto las mismas frases que escribiste.")
    return f, m


SISTEMA_TRADUCIR = """Traduces los textos del informe trimestral de un jugador de una academia de tenis, para enviárselo a su familia.

- Traducción fiel y natural, con el mismo tono claro y profesional. No añadas, quites ni reinterpretes nada.
- Usa el vocabulario habitual del tenis en el idioma de destino.
- Devuelve cada texto con su misma clave, sin comillas, corchetes, viñetas ni saltos de línea."""


SEXO = {"CHICO": "es un chico (en inglés, he/him)", "CHICA": "es una chica (en inglés, she/her)"}


def traducir(textos, idioma, jugador=None, sexo=""):
    """{clave: texto} traducido a `idioma` (ES/EN), con las mismas claves.
    `jugador` y `sexo` sirven para acertar con los pronombres."""
    esquema = {"type": "object", "properties": {k: {"type": "string"} for k in textos},
               "required": list(textos), "additionalProperties": False}
    respuesta = _llamar(
        max_tokens=8000,
        system=SISTEMA_TRADUCIR,
        output_config={"format": {"type": "json_schema", "schema": esquema}},
        messages=[{"role": "user", "content": (
            f"Idioma de destino: {IDIOMA[idioma]}.\n"
            + (f"Jugador: {jugador}, que {SEXO.get(sexo, 'no sabemos si es chico o chica: no uses he ni she, usa su nombre o they')}.\n"
               if jugador else "")
            + "\n" + json.dumps(textos, ensure_ascii=False, indent=1))}],
    )
    try:
        datos = json.loads(_texto(respuesta))
    except json.JSONDecodeError as e:
        raise IANoDisponible("Claude ha devuelto una traducción que no se puede leer.") from e
    if set(datos) != set(textos) or not all(str(v).strip() for v in datos.values()):
        raise IANoDisponible("La traducción ha llegado incompleta.")
    return {k: str(v).strip() for k, v in datos.items()}
