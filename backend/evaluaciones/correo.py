"""Correo que acompaña al informe en PDF, con el texto que dio el club
(29/10/2026). Aún no se envía: queda preparado para cuando se active.
`{nombre}` es el nombre del jugador."""

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


def correo(nombre, idioma="ES"):
    """(asunto, texto) del correo de un informe."""
    idioma = idioma if idioma in TEXTO else "ES"
    return ASUNTO[idioma].format(nombre=nombre), TEXTO[idioma].format(nombre=nombre)
