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


# --- Preparación física (21/10/2026) ---------------------------------------
# «Informe trimestral de preparación física y cuidado corporal» del club: 11
# criterios del 1 al 5 en tres bloques y tres textos del preparador. Lo
# rellena el preparador físico (o gestión deportiva) y va en el mismo PDF que
# el de tenis.

ESCALA_FISICO = {
    1: "Muy deficiente", 2: "Insuficiente", 3: "Aceptable / En desarrollo", 4: "Bueno", 5: "Excelente",
}

BLOQUES_FISICO = [
    {
        "clave": "desplazamiento", "titulo": "Desplazamiento y rendimiento físico específico",
        "criterios": [
            ("fis_aceleracion", "Aceleración y frenado (footwork específico)",
             "¿Muestra explosividad en los primeros 2-3 pasos de arranque y un control eficiente al frenar y transferir el peso antes de golpear?"),
            ("fis_apoyos", "Resistencia a la fuerza en apoyos",
             "¿Mantiene la profundidad y estabilidad en las piernas en apoyos abiertos y flexión durante series largas o partidos?"),
            ("fis_agilidad", "Agilidad reactiva y cambios de dirección",
             "¿Responde con rapidez visual y motora ante cambios de trayectoria inesperados sin perder el equilibrio?"),
            ("fis_resistencia", "Resistencia específica y recuperación entre puntos",
             "¿Mantiene la intensidad en intercambios largos y se recupera bien en los 25 segundos de descanso entre puntos?"),
            ("fis_potencia", "Potencia en la cadena cinética",
             "¿Transfiere eficientemente la fuerza desde los pies hasta la raqueta en saques y golpes de ataque?"),
        ],
    },
    {
        "clave": "prevencion", "titulo": "Prevención, fisioterapia y cuidado físico",
        "criterios": [
            ("fis_fisioterapia", "Fisioterapia preventiva semanal",
             "¿Cumple con la sesión semanal de fisioterapia descargativa o preventiva y aplica las pautas del fisioterapeuta en su día a día?"),
            ("fis_rutinas", "Rutinas autónomas de prevención y movilidad",
             "¿Hace con rigor los ejercicios de fortalecimiento y movilidad (manguito rotador, cadera, tobillos) fuera de la pista?"),
            ("fis_dolor", "Comunicación y conciencia corporal ante el dolor",
             "¿Comunica con honestidad y antelación cualquier molestia física antes de que derive en una lesión, con responsabilidad sobre su salud?"),
        ],
    },
    {
        "clave": "actitud", "titulo": "Actitud, compromiso y hábitos de trabajo",
        "criterios": [
            ("fis_intensidad", "Intensidad, foco y cultura de esfuerzo",
             "¿Muestra una actitud proactiva, máxima concentración y máxima entrega durante las sesiones físicas?"),
            ("fis_autonomia", "Autonomía y hábitos (calentamiento y vuelta a la calma)",
             "¿Hace por su cuenta el calentamiento previo y la rutina de descarga y estiramiento al terminar, sin necesidad de supervisión constante?"),
            ("fis_fatiga", "Rendimiento y actitud bajo fatiga",
             "¿Mantiene el nivel de exigencia física y una mentalidad positiva al final de la sesión o cuando el cansancio es alto?"),
        ],
    },
]
CRITERIOS_FISICO = [c[0] for b in BLOQUES_FISICO for c in b["criterios"]]  # las 11 claves

TEXTOS_FISICO = [
    ("puntos_fuertes", "Puntos fuertes del trimestre"),
    ("a_mejorar", "Aspectos físicos prioritarios a mejorar en el siguiente ciclo"),
    ("notas_fisio", "Notas de prevención y fisioterapia"),
]


def fisico_para_api():
    return {
        "escala": [{"valor": k, "etiqueta": v} for k, v in ESCALA_FISICO.items()],
        "bloques": [
            {"clave": b["clave"], "titulo": b["titulo"],
             "criterios": [{"clave": k, "etiqueta": e, "pregunta": p} for k, e, p in b["criterios"]]}
            for b in BLOQUES_FISICO
        ],
        "textos": [{"clave": k, "etiqueta": e} for k, e in TEXTOS_FISICO],
    }

# Nombres en inglés de la parte física, para los informes que van en inglés.
FISICO_EN = {
    "desplazamiento": "Movement and specific physical performance",
    "prevencion": "Prevention, physiotherapy and body care",
    "actitud": "Attitude, commitment and work habits",
    "fis_aceleracion": "Acceleration and braking (specific footwork)",
    "fis_apoyos": "Strength endurance in stances",
    "fis_agilidad": "Reactive agility and changes of direction",
    "fis_resistencia": "Specific endurance and recovery between points",
    "fis_potencia": "Power through the kinetic chain",
    "fis_fisioterapia": "Weekly preventive physiotherapy",
    "fis_rutinas": "Independent prevention and mobility routines",
    "fis_dolor": "Communication and body awareness of pain",
    "fis_intensidad": "Intensity, focus and work ethic",
    "fis_autonomia": "Autonomy and habits (warm-up and cool-down)",
    "fis_fatiga": "Performance and attitude under fatigue",
    "puntos_fuertes": "Strengths this term",
    "a_mejorar": "Physical priorities for the next cycle",
    "notas_fisio": "Prevention and physiotherapy notes",
}
CORTO_FISICO = {
    "desplazamiento": ("Desplazamiento", "Movement"),
    "prevencion": ("Prevención", "Prevention"),
    "actitud": ("Actitud", "Attitude"),
}
