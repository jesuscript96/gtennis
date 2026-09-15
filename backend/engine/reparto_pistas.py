"""Qué pistas llevan entrenador cuando no hay uno para cada pista.

Con menos entrenadores que pistas ocupadas, los jugadores siguen repartidos en
todas las pistas y los entrenadores se colocan de forma que cada pista sin
entrenador tenga al lado una pista con entrenador: así cada uno abarca la suya
y la contigua. Con las ocho pistas del Resort y cinco entrenadores, Iván los
pone en las pistas 1-3-4-6-7.

Esto solo decide QUÉ pistas se cubren. Quién va a cada una lo decide
`service._emparejar_entrenadores` con los porcentajes de sus alumnos, que
además descarta los repartos que no puede cubrir enteros.
"""
from itertools import combinations


def opciones_de_pistas(numeros, k, fijas=()):
    """Todas las formas de poner `k` entrenadores, de la mejor a la peor.

    `numeros` son las pistas OCUPADAS de una sede y `k` los entrenadores que
    tiene. Dos pistas son contiguas si sus números se llevan uno; una pista vacía
    en medio corta la contigüidad. `fijas` llevan entrenador sí o sí (un contrato
    duro): cuentan para cubrir a sus vecinas y el resto se elige alrededor.

    Se prueban todas las combinaciones (en una sede hay como mucho una docena de
    pistas) y se ordenan según, por este orden:

      1. Que no quede ninguna pista sin entrenador y sin vecina que lo tenga.
      2. Que ningún entrenador tenga que vigilar dos pistas además de la suya:
         con 1-3-4-6-8 la pista 6 vigilaría la 5 y la 7.
      3. Que las pistas sin entrenador lo tengan a ambos lados.
      4. Que la pista más baja lleve entrenador, y que las que se quedan sin él
         sean las de número más bajo. Es el desempate que reproduce el
         1-3-4-6-7 de Iván; cualquier otra que empate en 1-3 vale igual.

    Se devuelven todas y no solo la primera porque la geométricamente mejor
    puede no cubrirse entera, y entonces esa pista se queda sin entrenador y su
    vecina, huérfana.
    """
    numeros = sorted(set(numeros))
    fijas = set(fijas) & set(numeros)
    if k >= len(numeros):
        return [set(numeros)]
    if len(fijas) >= k:
        return [fijas]
    if k <= 0:
        return [set()]

    libres = [n for n in numeros if n not in fijas]
    puntuadas = []
    for extra in combinations(libres, k - len(fijas)):
        con = fijas | set(extra)
        sin = [n for n in numeros if n not in con]
        huerfanas = 0
        dobles = 0
        for n in sin:
            vecinos = (n - 1 in con) + (n + 1 in con)
            huerfanas += vecinos == 0
            dobles += vecinos == 2
        # Pistas sin entrenador que le tocan vigilar a cada entrenador.
        carga = max(
            (sum(1 for m in (c - 1, c + 1) if m in sin) for c in con),
            default=0,
        )
        clave = (huerfanas, carga, -dobles, numeros[0] not in con, sin)
        puntuadas.append((clave, con))
    puntuadas.sort(key=lambda par: par[0])
    return [con for _clave, con in puntuadas]


def pistas_con_entrenador(numeros, k, fijas=()):
    """El mejor reparto de `opciones_de_pistas`, sin mirar divisiones."""
    return opciones_de_pistas(numeros, k, fijas)[0]


def repartir_entre_sedes(ocupadas_por_sede, k, orden_sedes):
    """Cuántos entrenadores le tocan a cada sede.

    Una sede no puede vigilar las pistas de otra, así que primero cada una
    recibe los mínimos para que ninguna de sus pistas quede huérfana (una de
    cada tres pistas), en el orden de llenado del club; y lo que sobre, también
    por ese orden, hasta cubrir cada sede entera.
    """
    reparto = {sede: 0 for sede in ocupadas_por_sede}
    quedan = k
    for sede in orden_sedes:
        if sede not in ocupadas_por_sede or quedan <= 0:
            continue
        minimo = min(-(-len(ocupadas_por_sede[sede]) // 3), quedan)
        reparto[sede] = minimo
        quedan -= minimo
    for sede in orden_sedes:
        if sede not in ocupadas_por_sede or quedan <= 0:
            continue
        extra = min(len(ocupadas_por_sede[sede]) - reparto[sede], quedan)
        reparto[sede] += extra
        quedan -= extra
    return reparto
