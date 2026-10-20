"""Bloques y criterios del Informe de Rendimiento de Alto Rendimiento.

Sale de la especificación del club (apartado 4.2): ocho bloques técnicos, 34
criterios del 1 al 5 y un comentario por bloque. El orden de cada lista es el
orden en que se puntúa y en que sale en el fichero. Las claves (`drive_impact`…)
van siempre en inglés y en minúsculas, sea cual sea el idioma del informe.
"""

BLOQUES = [
    {
        "clave": "drive", "corto": "Drive", "corto_en": "Forehand", "titulo": "Drive (Derecha)", "titulo_en": "Forehand",
        "habilidad": "el Drive", "confirmacion": "Drive guardado.",
        "criterios": [
            ("drive_preparation", "Preparación", "Preparation"),
            ("drive_impact", "Impacto", "Impact"),
            ("drive_control", "Control", "Control"),
            ("drive_direction", "Dirección", "Direction"),
        ],
    },
    {
        "clave": "backhand", "corto": "Revés", "corto_en": "Backhand", "titulo": "Revés", "titulo_en": "Backhand",
        "habilidad": "el Revés", "confirmacion": "Revés guardado.",
        "criterios": [
            ("backhand_preparation", "Preparación", "Preparation"),
            ("backhand_impact", "Impacto", "Impact"),
            ("backhand_control", "Control", "Control"),
            ("backhand_direction", "Dirección", "Direction"),
        ],
    },
    {
        "clave": "serve", "corto": "Saque", "corto_en": "Serve", "titulo": "Saque", "titulo_en": "Serve",
        "habilidad": "el Saque", "confirmacion": "Saque guardado.",
        "criterios": [
            ("serve_posture", "Postura", "Posture"),
            ("serve_toss", "Lanzamiento", "Toss"),
            ("serve_power", "Potencia", "Power"),
            ("serve_precision", "Precisión", "Precision"),
            ("serve_rhythm", "Ritmo", "Rhythm"),
        ],
    },
    {
        "clave": "volley", "corto": "Volea", "corto_en": "Volley", "titulo": "Volea", "titulo_en": "Volley",
        "habilidad": "la Volea", "confirmacion": "Volea guardada.",
        "criterios": [
            ("volley_technique", "Técnica", "Technique"),
            ("volley_reaction", "Reacción", "Reaction"),
            ("volley_control", "Control", "Control"),
            ("volley_power", "Potencia", "Power"),
        ],
    },
    {
        "clave": "smash", "corto": "Smash", "corto_en": "Smash", "titulo": "Smash", "titulo_en": "Smash",
        "habilidad": "el Smash", "confirmacion": "Smash guardado.",
        "criterios": [
            ("smash_technique", "Técnica", "Technique"),
            ("smash_control", "Control", "Control"),
            ("smash_power", "Potencia", "Power"),
            ("smash_precision", "Precisión", "Precision"),
        ],
    },
    {
        "clave": "tactic", "corto": "Táctica", "corto_en": "Tactics", "titulo": "Táctica", "titulo_en": "Tactics",
        "habilidad": "la Táctica", "confirmacion": "Táctica guardada.",
        "criterios": [
            ("tactic_decisions", "Toma de Decisiones", "Decision Making"),
            ("tactic_positioning", "Posicionamiento en Pista", "Court Positioning"),
            ("tactic_variety", "Variedad de Juego", "Game Variety"),
            ("tactic_adaptation", "Adaptación al Rival", "Adapting to the Opponent"),
        ],
    },
    {
        "clave": "fitness", "corto": "Condición física", "corto_en": "Fitness", "titulo": "Condición Física", "titulo_en": "Fitness",
        "habilidad": "la Condición Física", "confirmacion": "Condición física guardada.",
        "criterios": [
            ("fitness_speed", "Velocidad", "Speed"),
            ("fitness_strength", "Fuerza", "Strength"),
            ("fitness_coordination", "Coordinación", "Coordination"),
            ("fitness_agility", "Agilidad", "Agility"),
        ],
    },
    {
        "clave": "psych", "corto": "Psicológico", "corto_en": "Mental", "titulo": "Aspecto Psicológico y Actitudinal",
        "titulo_en": "Mental and Attitude",
        "habilidad": "el Aspecto Psicológico", "confirmacion": "Aspecto psicológico guardado.",
        "criterios": [
            ("psych_concentration", "Concentración", "Concentration"),
            ("psych_emotional_control", "Control Emocional", "Emotional Control"),
            ("psych_motivation", "Motivación", "Motivation"),
            ("psych_competitive_attitude", "Actitud Competitiva", "Competitive Attitude"),
            ("psych_resilience", "Resiliencia", "Resilience"),
        ],
    },
]

POR_CLAVE = {b["clave"]: b for b in BLOQUES}
CRITERIOS = [c[0] for b in BLOQUES for c in b["criterios"]]  # las 34 claves, en orden
COMPETICION = "competicion"  # el texto libre del final se pule igual que un comentario

SIN_OBSERVACIONES = {"ES": "Sin observaciones", "EN": "No observations"}
SIN_RESULTADOS = {"ES": "Sin resultados registrados", "EN": "No results recorded"}

# Lo que un entrenador escribe o dicta cuando no quiere comentar nada.
_NADA = {"no", "nada", "ninguno", "ninguna", "sin comentarios", "sin observaciones",
         "no hay", "nothing", "none", "n/a", "-", "—", "no gracias"}


def es_nada(texto):
    t = (texto or "").strip().strip(".!¡").strip().lower()
    return not t or t in _NADA


def para_api():
    """El catálogo tal y como lo pinta el asistente del frontend."""
    return [
        {
            "clave": b["clave"], "titulo": b["titulo"], "titulo_en": b["titulo_en"],
            "habilidad": b["habilidad"], "confirmacion": b["confirmacion"],
            "criterios": [{"clave": k, "etiqueta": es, "etiqueta_en": en} for k, es, en in b["criterios"]],
        }
        for b in BLOQUES
    ]
