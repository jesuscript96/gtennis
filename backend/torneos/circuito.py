"""Quién da el visto bueno a cada jugador apuntado a un torneo (25/11/2026).

El circuito que pidió el club:

1. Head coaches (y dirección) dan de alta los torneos.
2. Los entrenadores apuntan a sus jugadores → PENDIENTE (del head coach).
3. El head coach del grupo lo valida o lo mueve a otro torneo → VALIDADO_COACH.
4. Dirección lo valida todo (o lo mueve) → CONFIRMADO.

Cada uno entra en el circuito a su altura: lo que apunta o mueve un head coach
ya va validado por él y espera a dirección; lo que apunta o mueve dirección
queda confirmado. Lo «deducido» del Excel viejo cuenta como pendiente del
head coach.
"""
from django.utils import timezone

from academy.permissions import es_coach, es_coordinador_tardes, es_direccion

from .models import Participante

C = Participante.Certeza
# Orden del circuito: cuanto más alto, más vistos buenos lleva.
ALTURA = {C.DEDUCIDO: 0, C.PENDIENTE: 0, C.VALIDADO_COACH: 1, C.CONFIRMADO: 2}


def hace_de_head_coach(user):
    """Los head coaches y quien coordina Competición de tardes, que hace de
    head coach de esos jugadores (25/11/2026). Dirección no: va por encima."""
    return not es_direccion(user) and (es_coach(user) or es_coordinador_tardes(user))


def certeza_de(user):
    """Hasta dónde llega lo que hace `user`: dirección confirma, el head coach
    (o quien coordina tardes) valida y el entrenador deja pendiente."""
    if es_direccion(user):
        return C.CONFIRMADO
    if hace_de_head_coach(user):
        return C.VALIDADO_COACH
    return C.PENDIENTE


def espera_a(certeza):
    """A quién le toca: «head_coach», «direccion» o None (ya confirmado)."""
    altura = ALTURA.get(certeza, 0)
    return None if altura >= 2 else "direccion" if altura == 1 else "head_coach"


def marcar(p, user, certeza=None):
    """Pone a `p` en la altura de `user` (o en `certeza`) y apunta quién y
    cuándo. No guarda. Devuelve los campos tocados."""
    certeza = certeza or certeza_de(user)
    ahora = timezone.now()
    p.certeza = certeza
    campos = ["certeza"]
    if certeza == C.VALIDADO_COACH:
        p.validado_coach_por, p.validado_coach_en = user, ahora
        p.confirmado_por, p.confirmado_en = None, None
        campos += ["validado_coach_por", "validado_coach_en", "confirmado_por", "confirmado_en"]
    elif certeza == C.CONFIRMADO:
        p.confirmado_por, p.confirmado_en = user, ahora
        campos += ["confirmado_por", "confirmado_en"]
    return campos


def puede_subir(p, user):
    """¿Le sube `user` un escalón a `p`? Solo si está por debajo de su altura."""
    return ALTURA.get(p.certeza, 0) < ALTURA[certeza_de(user)] and certeza_de(user) != C.PENDIENTE
