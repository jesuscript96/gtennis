"""Categorías de edad de los torneos (03/11/2026).

Las oficiales en España: cuentan los años que el jugador cumple en el año del
torneo, no los que tiene el día que juega. Un torneo puede ser de varias, y a
él se apuntan los de esas categorías y los de cualquiera más pequeña: un
alevín puede jugar un torneo infantil, no al revés.
"""

# (código, nombre en España, equivalente internacional, edad máxima que se
# cumple en el año; None = sin tope).
CATEGORIAS = [
    ("SUB8", "Pre-benjamín", "Sub-8", 8),
    ("SUB10", "Benjamín", "Sub-10", 10),
    ("SUB12", "Alevín", "Sub-12", 12),
    ("SUB14", "Infantil", "Sub-14", 14),
    ("SUB16", "Cadete", "Sub-16", 16),
    ("SUB18", "Júnior", "Sub-18", 18),
    ("ABSOLUTA", "Absoluta", "Senior", None),
]
CODIGOS = [c[0] for c in CATEGORIAS]
NOMBRE = {c[0]: c[1] for c in CATEGORIAS}


def ordenar(codigos):
    """Sin repetidos y de la más pequeña a la mayor."""
    return sorted(set(codigos), key=CODIGOS.index)


def categoria_de(jugador, anio):
    """Código de la categoría del jugador en el año `anio`. Sin fecha de
    nacimiento, la que se le haya fijado (`CategoriaJugador`) o None."""
    nacimiento = getattr(jugador, "fecha_nacimiento", None)
    if nacimiento is None:
        fija = getattr(jugador, "categoria_torneos", None) if jugador.pk else None
        return fija.categoria if fija is not None else None
    cumple = anio - nacimiento.year
    for codigo, _, _, tope in CATEGORIAS:
        if tope is None or cumple <= tope:
            return codigo
    return CODIGOS[-1]


def puede_jugar(jugador, torneo):
    """¿Entra por edad? Sí si el torneo no tiene categorías, si no se sabe su
    categoría (sin fecha de nacimiento ni categoría fijada: no se le cierra la
    puerta por un dato que falta) o si es la del torneo o una más pequeña."""
    if not torneo.categorias or jugador is None:
        return True
    cat = categoria_de(jugador, torneo.fecha_inicio.year)
    if cat is None:
        return True
    return CODIGOS.index(cat) <= max(CODIGOS.index(c) for c in torneo.categorias)


def motivo(jugador, torneo):
    """Por qué no puede apuntarse, para el mensaje de error."""
    cat = categoria_de(jugador, torneo.fecha_inicio.year)
    del_torneo = ", ".join(NOMBRE[c] for c in torneo.categorias)
    return (f"{jugador.nombre} es {NOMBRE[cat].lower()} en {torneo.fecha_inicio.year} y «{torneo.nombre}» "
            f"es {del_torneo.lower()}: solo se apuntan los de esa categoría o una más pequeña.")
