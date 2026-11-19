"""Correo que acompaña al informe en PDF, con el texto que dio el club para
Competición de tardes (29/10/2026) y uno para Alto rendimiento (19/11/2026),
donde la parte física es opcional. `{nombre}` es el nombre del jugador.
Las respuestas de la familia van a gestion@ y a su head coach (en tardes, a
quien coordina): ver `informes.responder_a`."""

REMITENTE = "gestion@gtennis.com"

ASUNTO = {
    "ES": "Informe trimestral de {nombre} · G Tenis",
    "EN": "{nombre}'s quarterly report · G Tenis",
}

TEXTO = {
    "ES": (
        "Hola:\n\n"
        "Os enviamos adjunto el informe técnico de {nombre}, con la valoración de su entrenador de tenis "
        "y de su preparador físico.\n\n"
        "El coordinador se pondrá en contacto con vosotros para realizar una tutoría.\n\n"
        "Un saludo,\nDirección deportiva · G Tenis"
    ),
    "EN": (
        "Hello,\n\n"
        "Please find attached {nombre}'s technical report, with the assessment of their tennis coach "
        "and their fitness coach.\n\n"
        "The coordinator will get in touch with you to arrange a one-to-one meeting.\n\n"
        "Kind regards,\nSports management · G Tenis"
    ),
}


# Alto rendimiento (19/11/2026): sin coordinador ni tutoría; si la familia
# quiere comentarlo, responde y le llega a su head coach y a gestion@.
TEXTO_AR = {
    "ES": (
        "Hola:\n\n"
        "Os enviamos adjunto el informe trimestral de {nombre}, con la valoración de su entrenador{fisico}.\n\n"
        "Si queréis comentar algo, podéis responder a este correo: le llegará a su head coach y a la "
        "dirección deportiva.\n\n"
        "Un saludo,\nDirección deportiva · G Tenis"
    ),
    "EN": (
        "Hello,\n\n"
        "Please find attached {nombre}'s quarterly report, with the assessment of their coach{fisico}.\n\n"
        "If you would like to discuss anything, just reply to this email: it will reach their head coach "
        "and our sports management team.\n\n"
        "Kind regards,\nSports management · G Tenis"
    ),
}
FISICO_AR = {"ES": " y de su preparador físico", "EN": " and their fitness coach"}


def correo(nombre, idioma="ES", circuito="tardes", con_fisica=True):
    """(asunto, texto) del correo de un informe."""
    idioma = idioma if idioma in TEXTO else "ES"
    if circuito == "alto_rendimiento":
        texto = TEXTO_AR[idioma].format(nombre=nombre, fisico=FISICO_AR[idioma] if con_fisica else "")
    else:
        texto = TEXTO[idioma].format(nombre=nombre)
    return ASUNTO[idioma].format(nombre=nombre), texto
