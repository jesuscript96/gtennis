"""Bridges the pure pairing core (`pairing.py`) with Django models: gathers the
inputs for a Semana, runs the solver per (day, block) —all the shifts of a
morning at once—, assigns coaches and persists Asignacion rows.
"""
from __future__ import annotations

import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from django.db import transaction

from academy.models import (
    Contrato,
    Entrenador,
    Pista,
    Rencilla,
    Sede,
    Turno,
    VacacionesEntrenador,
)
from scheduling.models import (
    DIAS,
    ESTADOS_DEPRIORIZADOS,
    ESTADOS_EXCLUYENTES,
    Asignacion,
    AvisoBanquillo,
    ConfiguracionMotor,
    Disponibilidad,
    DisponibilidadEntrenador,
    Estado,
    QuitadoAMano,
    Semana,
)

from .pairing import NIVEL_MAX, Court, PairingInput, Player, _normalise, solve_pairing


def _build_courts(usar_satelites: bool = True) -> list[Court]:
    courts = []
    for pista in Pista.objects.filter(activa=True).select_related("sede"):
        if not pista.sede.activa:
            continue
        if pista.sede.es_satelite and not usar_satelites:
            continue
        courts.append(
            Court(
                id=pista.id,
                venue_id=pista.sede_id,
                capacity=max(
                    pista.sede.densidad_max or 0, pista.sede.densidad_default
                ),
                normal_density=pista.sede.densidad_default,
                is_satellite=pista.sede.es_satelite,
                fill_rank=pista.sede.orden_desbordamiento,
                surface=pista.superficie,
                number=pista.numero,
            )
        )
    return courts


def _vetoes() -> set[tuple[int, int]]:
    out = set()
    for r in Rencilla.objects.filter(activa=True):
        a, b = r.jugador_a_id, r.jugador_b_id
        out.add((a, b) if a <= b else (b, a))
    return out


def _vetos_entrenador() -> dict[int, set[int]]:
    """jugador_id -> entrenadores con los que no debe entrenar (regla dura)."""
    from academy.models import VetoEntrenador

    m: dict[int, set[int]] = defaultdict(set)
    for v in VetoEntrenador.objects.filter(activo=True):
        m[v.jugador_id].add(v.entrenador_id)
    return m


def _preferencias_franja(tipo) -> dict[int, dict[int, set[int]]]:
    """turno_id -> {jugador_id: entrenadores} («si entrena en M1, con Iván»)."""
    from academy.models import PreferenciaEntrenadorFranja

    m: dict[int, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    for pf in PreferenciaEntrenadorFranja.objects.filter(activa=True, tipo=tipo):
        m[pf.turno_id][pf.jugador_id].add(pf.entrenador_id)
    return m


def _sponsor_map(tipo="DURO") -> dict[int, set[int]]:
    """jugador_id -> entrenadores con contrato de ese tipo.

    Los duros atan al entrenador con el jugador antes de repartir; los blandos
    solo se aplican si no dejan ninguna otra pista sin entrenador.
    """
    m: dict[int, set[int]] = defaultdict(set)
    for c in Contrato.objects.filter(activo=True, tipo=tipo):
        m[c.jugador_id].add(c.entrenador_id)
    return m


def _overrides(semana: Semana, dia: int) -> dict[tuple[int, str], object]:
    """(jugador_id, ambito) -> la ausencia que aplica ese día.

    Se juntan dos fuentes que el motor trata igual: el parte de la semana
    (`Disponibilidad`, una fila por día) y las ausencias declaradas por rango
    de fechas (`AusenciaJugador`, una sola fila para toda una lesión). Las de
    rango se expanden aquí, así que quien declaró "del 2 de noviembre al 15 de
    diciembre" no tiene que repetirlo cada semana.

    Si ambas hablan del mismo jugador y ámbito, manda el parte de la semana:
    es más reciente y más específico.
    """
    from scheduling.models import AusenciaJugador

    fecha = semana.fecha_inicio + timedelta(days=dia)
    out = {}
    for a in AusenciaJugador.objects.filter(
        fecha_inicio__lte=fecha, fecha_fin__gte=fecha
    ):
        out[(a.jugador_id, a.ambito)] = a
    for d in Disponibilidad.objects.filter(semana=semana, dia=dia):
        out[(d.jugador_id, d.ambito)] = d
    return out


def override_efectivo(overrides, jugador_id, turno, fecha=None):
    """La falta o parte que manda para este jugador en este turno, o None.

    Resolución por prioridad: turno concreto > bloque (mañana/tarde) > día.
    Una ausencia con horas solo cuenta si se solapa con este turno: quien
    "llega a las 10:30" está ausente en la franja de 8:30 pero no en la suya.
    """
    has_horas = hasattr(turno, "horas") and callable(getattr(turno, "horas", None))
    ini, fin = turno.horas(fecha) if has_horas else (None, None)
    for key in (getattr(turno, "codigo", None), getattr(turno, "bloque", None), "DIA"):
        if not key:
            continue
        d = overrides.get((jugador_id, key))
        if d is None:
            continue
        if hasattr(d, "afecta") and ini is not None and fin is not None and not d.afecta(ini, fin):
            continue
        return d
    return None


def _effective_state(overrides, jugador_id, turno, fecha=None):
    d = override_efectivo(overrides, jugador_id, turno, fecha)
    return d.estado if d is not None else Estado.DISPONIBLE


def _player_priority(division, state, banquillo=0):
    """Prioridad de colocación en el turno, en dos niveles.

    Solo cuenta cuando no caben todos. Manda el BANQUILLO: quien esta semana
    ya se ha quedado sin pista estando disponible va por delante de quien no,
    sea del nivel que sea — así no es siempre el mismo el que se queda fuera.
    A igualdad desempata el nivel, donde la división 1 es la élite (nivel 1 →
    9, nivel 9 → 1).

    No hay cupo semanal: se da por hecho que todos vienen todos los días y lo
    que no, se declara (ausencias, horario).

    Molestias/torneo bajan la prioridad: llenan hueco solo tras los
    plenamente disponibles.
    """
    nivel = (NIVEL_MAX + 1 - division) if division else 4
    if state in ESTADOS_DEPRIORIZADOS:
        nivel = max(1, nivel // 2)
    # El banquillo escala por encima del rango de niveles para que domine.
    return max(0, banquillo) * (NIVEL_MAX + 1) + nivel


# Medias jornadas en las que el club no entrena. Los miércoles por la tarde no
# hay pista: ni jugadores ni entrenadores se pueden colocar ahí, ni el motor ni
# a mano. (día de la semana con lunes=0, bloque)
CERRADO = {(2, "TARDE"), (5, "TARDE")}

# Franjas que no se abren un día concreto aunque el bloque esté abierto. El
# viernes por la tarde todo el mundo entrena a las 14:15.
FRANJA_CERRADA = {(4, "T2")}

# Premio por cada jugador de su lista que va en la pista de quien solo entra
# con ellos (Dani Gimeno): que vayan juntos cuando se pueda. Por debajo de lo
# que vale colocar a alguien, así que nunca deja a nadie fuera.
PESO_JUNTOS_DEDICADO = 500

# Pistas de tierra que se dejan sin entrenador, vigiladas por la de al lado:
# con entrenador la 1, 3, 4 y 6, y sin él la 2 y la 5 (14/10/2026). Es
# preferencia: vigilar otra cuesta esto, menos que abrir pista o dejar a
# alguien fuera.
VIGILADAS_PREFERIDAS = frozenset({2, 5})
PESO_VIGILADA_FUERA = 300

# Una pista con D1 o D2 (`nivel_protegido`) que se queda sin entrenador, vigilada
# desde la de al lado (16/10/2026). Más que saltarse el patrón 1-3-4-6 (300),
# menos que dejar a alguien sin pista (1000): nadie se queda fuera por esto.
PESO_ALTO_SIN_ENTRENADOR = 800

# El color del grupo (pestaña Grupos) al elegir entrenador para una pista
# (16/10/2026): por cada alumno de su color, y algo más si es su propio
# entrenador de gestión. Pesa más que los porcentajes (`_afinidad`, en unidades
# de ESCALA_AFINIDAD), que deciden dentro del color: la afinidad de un alumno
# es su porcentaje por las sesiones de la semana menos las hechas, así que
# para el viernes llega a valer varias unidades; con 3 no ganaba el color.
BONUS_MISMO_COLOR = 20
BONUS_SU_RESPONSABLE = 5


def hay_entrenamiento(dia, bloque):
    """¿Se entrena ese día en ese bloque? El miércoles por la tarde, no."""
    return (dia, bloque) not in CERRADO


def entrenador_en_franja(entrenador, turno):
    """¿Entra este entrenador en esta franja?

    Igual que el alumno: si tiene declarada la franja de ese bloque solo entra
    en esa, y si no la tiene entra en cualquiera — que es el caso normal, da
    clase siempre que haya jugadores suyos disponibles.

    No confundir con `HorarioEntrenador` ("los martes no vengo por la tarde"),
    que va por día: esto es la franja fija de toda la semana.
    """
    from academy.models import Turno as _T

    fijo = (entrenador.turno_manana_id if turno.bloque == _T.Bloque.MANANA
            else entrenador.turno_tarde_id)
    return fijo is None or fijo == turno.id


# Horquilla de divisiones de cada opción de la ficha: (por encima, por debajo).
# Vacío = la del club.
HORQUILLA_VECINDAD = {
    "SOLO": (0, 0),
    "ARRIBA": (1, 0),
    "ABAJO": (0, 1),
    "AMBAS": (1, 1),
}


def motivo_no_disponible(c, dia, turno, fecha, vacaciones, jornada, partes):
    """Por qué este entrenador no puede dar esta franja, o None si sí puede.

    Lo usa el motor para elegir a quién puede poner y el panel del cuadrante
    para enseñar quién está libre en cada franja, así que la regla vive en un
    único sitio. No mira si ya está en otra pista: eso depende de cómo vaya
    quedando el reparto y se comprueba aparte.
    """
    if not c.disponible_semana:
        return "no disponible esta semana"
    if any(v.afecta_turno(turno) for v in vacaciones.get(c.id, ())):
        return "de vacaciones"
    # Jornada estable: quien no trabaja ese bloque ese día no entra. Sin fila
    # se entiende jornada completa.
    jor = jornada.get((c.id, dia))
    if jor is not None and not (
        jor[0] if turno.bloque == Turno.Bloque.MANANA else jor[1]
    ):
        return "ese día no trabaja " + (
            "por la mañana" if turno.bloque == Turno.Bloque.MANANA else "por la tarde")
    if not entrenador_en_franja(c, turno):
        return "solo da clase en su franja fija"
    parte = partes.get(c.id)
    if parte is not None and not parte.disponible_en(*turno.horas(fecha)):
        return "declarado no disponible ese día"
    return None


def _jugador_motor(j, fecha, sponsors, surface_prefs, priority, solo_central,
                   nivel_solo_tierra=0):
    """El `Player` del solver para la ficha `j` ese día."""
    coach = next(iter(sponsors.get(j.id, set())), None)
    # Superficie preferida activa en la fecha (#1).
    pref = None
    for sup, desde, hasta in surface_prefs.get(j.id, ()):
        if (desde is None or fecha >= desde) and (hasta is None or fecha <= hasta):
            pref = sup
            break
    # Los de arriba entrenan en tierra. Solo pisan resina si alguien se lo
    # declara expresamente en la ficha, que es lo que hace el `if` de antes.
    if (pref is None and nivel_solo_tierra and j.division
            and j.division.nivel <= nivel_solo_tierra):
        pref = "TIERRA"
    arriba, abajo = HORQUILLA_VECINDAD.get(j.vecindad, (None, None))
    return Player(
        division_pref={"ARRIBA": -1, "ABAJO": 1}.get(j.pareja_division, 0),
        id=j.id,
        division=j.division.nivel if j.division else None,
        sponsor_coach_id=coach,
        priority=priority,
        surface_pref=pref,
        solo_central=solo_central,
        div_arriba=arriba,
        div_abajo=abajo,
        sexo=j.sexo or None,
        edad=j.edad,
        sin_prioridad=j.sin_prioridad,
    )


def _entra_en_franja(j, dia, turno, fecha, overrides, escuela_cfg,
                     exclusive_escuela_id, horario, hechas_dia, hechas_bloque, cfg,
                     desborde=None):
    """Con qué estado entra `j` en esta franja ese día, o None si no entra.

    `desborde` ({franja: franjas de después}) es la tarde: quien declara T1
    entra también en T2, para cuando en T1 ya no cabe (13/10/2026).
    """
    # Alta a mitad de mes: hasta el día que empieza, el alumno no entra en
    # ningún entrenamiento aunque su ficha ya exista (y lo mismo al revés
    # con la fecha de baja).
    if not j.en_alta(fecha):
        return None
    # #6: los jugadores de una escuela con turno único (p. ej. Junior
    # Program → JP) solo entran en ese turno; en el resto se excluyen.
    turno_unico, _solo_central = escuela_cfg.get(j.escuela_id, (None, False))
    if turno_unico is not None and turno_unico != turno.id:
        return None
    # Regla inversa: si ESTE turno es exclusivo de una escuela (alguien lo
    # tiene como turno_unico), solo pueden entrar jugadores de esa escuela.
    # Evita que Alto Rendimiento caiga en el turno JP.
    if exclusive_escuela_id is not None and j.escuela_id != exclusive_escuela_id:
        return None
    state = _effective_state(overrides, j.id, turno, fecha)
    if state in ESTADOS_EXCLUYENTES:
        return None
    # Excepción del entrenador: ese día y en esa franja viene sí o sí, diga lo
    # que diga su horario o sus topes. Solo se respeta lo que no depende de
    # él: el alta, la escuela y que el club abra.
    if state == Estado.EXTRA:
        return state
    # Franja del jugador para este bloque. Manda el horario del día si lo
    # tiene (puede entrar a primera hora los lunes y a segunda los
    # miércoles); si no, el turno fijo de su ficha; y si tampoco, el motor
    # elige. En la fila de un día cada bloque tiene tres respuestas: no
    # entrena, entrena en la franja que salga (turno vacío) o entrena en esa
    # franja.
    fila = horario.get((j.id, dia))
    if fila is not None:
        man, tar, entrena_m, entrena_t = fila
        es_manana = turno.bloque == "MANANA"
        if not (entrena_m if es_manana else entrena_t):
            return None
        elegido = man if es_manana else tar
    else:
        elegido = (j.turno_manana_id if turno.bloque == "MANANA"
                   else j.turno_tarde_id)
    if (elegido is not None and elegido != turno.id
            and turno.id not in (desborde or {}).get(elegido, ())):
        return None
    # Tope de sesiones el mismo día (#18): quien ya ha cubierto su dosis de
    # hoy no entra en los turnos que quedan.
    tope_dia = (j.sesiones_dia_max if j.sesiones_dia_max is not None
                else (cfg.sesiones_dia_max_default if cfg else 2))
    if hechas_dia.get(j.id, 0) >= tope_dia:
        return None
    # Y como mucho una por bloque: quien ya ha entrenado por la mañana repite
    # por la tarde, no a la hora siguiente. Es lo que hace la academia — de
    # 249 dobles sesiones en agosto, 248 son mañana+tarde.
    tope_bloque = cfg.sesiones_bloque_max if cfg else 1
    if hechas_bloque.get((j.id, turno.bloque), 0) >= tope_bloque:
        return None
    return state


def _candidatos_bloque(
    semana, dia, grupo, sponsors, escuela_cfg, surface_prefs, exclusivos, cfg,
    hechas_dia, hechas_bloque, horario, banquillo, overrides,
):
    """Quién puede entrar en las franjas de `grupo` ese día.

    Devuelve `(jugadores, franjas_de, max_franjas)`, que es lo que pide
    `solve_pairing` para decidir el bloque de una vez: los jugadores de más a
    menos prioridad, en qué franjas puede entrar cada uno y con qué prioridad,
    y en cuántas como mucho.
    """
    from academy.models import Jugador

    fecha = semana.fecha_inicio + timedelta(days=dia)
    tope_bloque = cfg.sesiones_bloque_max if cfg else 1
    tope_dia_def = cfg.sesiones_dia_max_default if cfg else 2
    bloque = grupo[0].bloque
    # Por la tarde la franja declarada es la primera opción, no la única: el
    # que no cabe en T1 sigue en T2 antes que quedarse sin entrenar.
    desborde = {}
    if bloque == "TARDE":
        orden = sorted(grupo, key=lambda t: t.hora_inicio)
        desborde = {t.id: {d.id for d in orden[i + 1:]} for i, t in enumerate(orden)}
    jugadores, franjas_de, max_franjas = [], {}, {}
    for j in Jugador.objects.filter(activo=True).select_related("division"):
        division = j.division.nivel if j.division else None
        opciones, extra_de_franja = {}, 0
        for turno in grupo:
            state = _entra_en_franja(
                j, dia, turno, fecha, overrides, escuela_cfg,
                exclusivos.get(turno.id), horario, hechas_dia, hechas_bloque, cfg,
                desborde,
            )
            if state is None:
                continue
            # Con prioridad alta, para que no se quede en el banquillo justo
            # el que el entrenador ha apuntado.
            opciones[turno.id] = (
                1 if j.sin_prioridad else _player_priority(
                    division, state,
                    99 if state == Estado.EXTRA else banquillo.get(j.id, 0),
                )
            )
            parte = overrides.get((j.id, turno.codigo))
            if parte is not None and parte.estado == Estado.EXTRA:
                extra_de_franja += 1
        if not opciones:
            continue
        _unico, solo_central = escuela_cfg.get(j.escuela_id, (None, False))
        jugadores.append(_jugador_motor(
            j, fecha, sponsors, surface_prefs, max(opciones.values()), solo_central,
            cfg.nivel_solo_tierra if cfg else 0,
        ))
        franjas_de[j.id] = opciones
        # Una sesión por bloque. Quien viene además a dos franjas concretas
        # (M1 y M2) hace las dos; «viene además por la mañana» es una.
        tope_dia = j.sesiones_dia_max if j.sesiones_dia_max is not None else tope_dia_def
        normal = min(tope_bloque - hechas_bloque.get((j.id, bloque), 0),
                     tope_dia - hechas_dia.get(j.id, 0))
        max_franjas[j.id] = max(1, normal, extra_de_franja)
    jugadores.sort(key=lambda p: p.priority, reverse=True)
    return jugadores, franjas_de, max_franjas


def _available_players(
    semana, dia, turno, sponsors, escuela_cfg=None, surface_prefs=None,
    exclusive_escuela_id=None, cfg=None, hechas_dia=None, hechas_bloque=None,
    horario=None, banquillo=None,
) -> list[Player]:
    """Quién puede entrar en una sola franja ese día, de más a menos prioridad."""
    exclusivos = ({turno.id: exclusive_escuela_id}
                  if exclusive_escuela_id is not None else {})
    jugadores, _franjas_de, _max = _candidatos_bloque(
        semana, dia, [turno], sponsors, escuela_cfg or {}, surface_prefs or {},
        exclusivos, cfg, hechas_dia or {}, hechas_bloque or {}, horario or {},
        banquillo or {}, _overrides(semana, dia),
    )
    return jugadores


def _grupos_de_turnos(turnos, exclusivos):
    """Las franjas que se deciden juntas, en el orden del día.

    Las de un mismo bloque son alternativas para el mismo alumno (M1 o M2; T1
    o T2), así que van juntas. La de una escuela con turno propio (JP) va
    sola: nadie más entra en ella y sus jugadores no entran en otra.
    """
    grupos = {}
    for turno in turnos:
        clave = ("propio", turno.id) if turno.id in exclusivos else ("bloque", turno.bloque)
        grupos.setdefault(clave, []).append(turno)
    return sorted(grupos.values(), key=lambda g: min(t.orden for t in g))


def _dias_juntos(semana, dia, rehechos=()) -> dict[tuple[int, int], set[int]]:
    """(a, b) -> los OTROS días de la semana en que ya comparten pista.

    Cuenta toda la semana, no solo lo anterior: si se rehace el miércoles con
    el jueves y el viernes ya hechos, esos días también cuentan. Lo que no
    cuenta es lo que está a punto de rehacerse (los días posteriores de esta
    misma generación), porque se va a borrar. Mañana y tarde del mismo día
    son un solo día.
    """
    por_celda = defaultdict(list)
    qs = Asignacion.objects.filter(semana=semana).exclude(dia=dia).exclude(
        dia__in=[d for d in rehechos if d > dia])
    for a in qs.values_list("dia", "turno_id", "pista_id", "jugador_id"):
        por_celda[a[:3]].append(a[3])
    out: dict[tuple[int, int], set[int]] = defaultdict(set)
    for (d, _t, _p), ids in por_celda.items():
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                out[_normalise(ids[i], ids[j])].add(d)
    return out


def _recent_partners(semana, before_dia) -> dict[frozenset[int], int]:
    """Pairs that already shared a court earlier in the week (drives rotation)."""
    counts: Counter = Counter()
    qs = Asignacion.objects.filter(semana=semana, dia__lt=before_dia)
    by_cell = defaultdict(list)
    for a in qs:
        by_cell[(a.dia, a.turno_id, a.pista_id)].append(a.jugador_id)
    for members in by_cell.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                counts[frozenset((members[i], members[j]))] += 1
    return dict(counts)


# El resolvedor trabaja con enteros: un 1% de peso son 100 unidades, y la carga
# de cada entrenador (unas pocas sesiones) solo desempata.
ESCALA_AFINIDAD = 10_000
# Cubrir una pista vale más que cualquier afinidad: primero que no quede
# ninguna sin entrenador, y luego quién va a cada una.
VALOR_CUBRIR = 10**8


def pesos_de_entrenamiento():
    """{jugador: {entrenador: fracción}}: con quién entrena cada alumno.

    Salen de sus porcentajes (`ResponsableJugador`), normalizados por si a mano
    no suman 100. Un alumno sin porcentajes entrena con su responsable, y sin
    responsable, con quien toque.
    """
    from academy.models import Jugador, ResponsableJugador

    brutos = defaultdict(dict)
    for jid, cid, pct in ResponsableJugador.objects.filter(
        activo=True, entrenador__activo=True, porcentaje_objetivo__gt=0,
    ).values_list("jugador_id", "entrenador_id", "porcentaje_objetivo"):
        brutos[jid][cid] = pct
    pesos = {
        jid: {cid: pct / sum(suyos.values()) for cid, pct in suyos.items()}
        for jid, suyos in brutos.items()
    }
    for jid, cid in Jugador.objects.filter(
        activo=True, entrenador_responsable__isnull=False,
    ).values_list("id", "entrenador_responsable_id"):
        pesos.setdefault(jid, {cid: 1.0})
    return pesos


def _puntos_color(miembros, cid, responsable_de, color_de):
    """Lo que tira el color del grupo hacia este entrenador en esta pista: por
    cada alumno de su color, y más si es su entrenador de gestión. Los alumnos
    sin color (sin grupo, o de un bloque sin color) no cuentan."""
    if not responsable_de or not color_de:
        return 0
    mio = color_de.get(cid)
    puntos = 0
    for jid in miembros:
        suyo = responsable_de.get(jid)
        if suyo is None:
            continue
        if suyo == cid:
            puntos += BONUS_MISMO_COLOR + BONUS_SU_RESPONSABLE
        elif mio and color_de.get(suyo) == mio:
            puntos += BONUS_MISMO_COLOR
    return puntos


def _afinidad(miembros, cid, pesos, con_quien, sesiones):
    """Cuánto le toca a este entrenador llevar esta pista ahora.

    Por cada alumno: lo que le correspondería con él contando esta sesión,
    menos lo que ya lleva hecho con él esta semana. Con Víctor al 60%, la
    primera sesión es de Víctor (0,6 frente a 0,1); si ya ha hecho dos de dos
    con él, le toca a un secundario. Así cada uno se acerca a su porcentaje sin
    que se concentre nadie. Un alumno sin porcentajes no tira hacia nadie.
    """
    total = 0.0
    for jid in miembros:
        suyos = pesos.get(jid)
        if suyos:
            total += suyos.get(cid, 0.0) * (sesiones[jid] + 1) - con_quien[(jid, cid)]
    return total


# Coste con el que un entrenador vetado nunca gana al hueco «sin entrenador».
# Tiene que superar a VALOR_CUBRIR: cubrir la pista vale mucho, pero romper un
# veto no compensa ni así.
VALOR_PROHIBIDO = 10 ** 10


def _mejor_asignacion(pistas, entrenadores, valor):
    """{pista: entrenador}: el máximo de pistas cubiertas y, entre esos
    repartos, el de más valor. Nadie va a dos pistas.

    Es el problema de asignación y lo resuelve OR-Tools. Para que admita pistas
    sin entrenador (si faltan) y entrenadores sin pista (si sobran), cada pista
    tiene además un hueco «sin entrenador» y cada entrenador uno «sin pista»,
    los dos a coste cero.
    """
    from ortools.graph.python import linear_sum_assignment

    if not pistas or not entrenadores:
        return {}
    n_p, n_e = len(pistas), len(entrenadores)
    lsa = linear_sum_assignment.SimpleLinearSumAssignment()
    for i, pista in enumerate(pistas):
        for k, cid in enumerate(entrenadores):
            lsa.add_arc_with_cost(i, k, -(VALOR_CUBRIR + valor(pista, cid)))
        for k in range(n_e, n_e + n_p):
            lsa.add_arc_with_cost(i, k, 0)
    for i in range(n_p, n_p + n_e):
        for k in range(n_e + n_p):
            lsa.add_arc_with_cost(i, k, 0)
    if lsa.solve() != lsa.OPTIMAL:
        return {}
    return {
        pistas[i]: entrenadores[lsa.right_mate(i)]
        for i in range(n_p) if lsa.right_mate(i) < n_e
    }


def _penalizacion_division(miembros, entrenador, divisiones, peso):
    """Cuánto cuesta que este entrenador lleve esta pista, por el grupo.

    Cada alumno fuera de su grupo suma las divisiones de distancia, y pesan más
    los de arriba: llevar a un alumno de la división 1 que no es de tu grupo
    cuesta nueve veces más que a uno de la 9. Es coste, no prohibición: si no
    hay nadie más, la pista la coge igual.
    """
    if not peso:
        return 0
    total = 0
    for jid in miembros:
        nivel = divisiones.get(jid)
        distancia = entrenador.distancia_division(nivel)
        if distancia:
            total += distancia * (NIVEL_MAX + 1 - nivel)
    return peso * total


def _emparejar_entrenadores(
    courts, sponsors, elegibles, load, pesos=None, con_quien=None,
    sesiones=None, blandos=None, info_pistas=None, divisiones=None,
    peso_division=0, vetos=None, solo_si_atado=frozenset(),
    nivel_protegido=0, tolerancia_division=None, cubrir=None,
    sin_rescate=frozenset(), responsable_de=None, color_de=None,
):
    """Reparte los entrenadores de un turno: uno por pista, sin repetir.

    Devuelve `({pista: entrenador}, [pistas que se quedan huérfanas])`: sin
    entrenador propio y sin ninguna vecina que las cubra. Nadie da dos pistas
    del mismo turno.

    `solo_si_atado` son los del banquillo: no entran en el reparto, pero si un
    contrato o una preferencia de franja les llama a una pista concreta, van.

    `nivel_protegido` son las divisiones que nunca se quedan sin nadie que las
    vigile (grupo 1-2). Sus pistas se cubren las primeras, por delante del
    criterio geométrico, y si alguna queda además huérfana —sin entrenador y
    sin vecina que lo tenga— se saca a uno del banquillo.

    `tolerancia_division` es cuántas divisiones se le admite a un entrenador
    salirse de su grupo. Es límite, no coste: Dani Gimeno lleva el grupo 1-2 y
    con tolerancia 2 llega hasta la 4, pero no acaba con un D7. Se levanta en
    la pista que, con el límite puesto, no admitiría a nadie.

    Quién va a cada pista lo deciden los porcentajes de sus alumnos (`pesos`,
    {jugador: {entrenador: fracción}}) y lo que llevan hecho esta semana con
    cada uno (`con_quien`, `sesiones`); ver `_afinidad`. La división no
    limita: sirve para emparejar alumnos, no para elegir entrenador, así que si
    no queda libre ninguno de los suyos la cubre otro antes que nadie. Es un
    problema de asignación: primero cubrir todas las pistas posibles y, entre
    esos repartos, el que más se acerca a los porcentajes.

    Contratos. El duro ata al entrenador con la pista de su jugador antes de
    repartir. El blando no ata: primero se reparte como si no existiera, y
    después se prueba a llevar al entrenador a la pista del jugador; se queda
    así solo si no se pierde ninguna pista cubierta — «primero su grupo, y con
    ese jugador cuando pueda».

    Pocos entrenadores. Si `info_pistas` dice dónde está cada pista
    ({pista: (sede, número, orden de llenado)}) y hay menos entrenadores que
    pistas ocupadas, primero se eligen las pistas que llevan entrenador de modo
    que cada una sin él tenga una vecina con él (`reparto_pistas`), y el reparto
    trabaja sobre esas. A las que vigila el de al lado no se les repite a nadie;
    solo a las que se quedan sin vecina que las cubra.

    `responsable_de` ({jugador: entrenador de gestión}) y `color_de`
    ({entrenador: color de su grupo}) dan preferencia al entrenador del color
    de los alumnos de la pista, y más aún a su propio entrenador de gestión
    (16/10/2026). Decide entre los que valen; los porcentajes, dentro del color.

    `sin_rescate` son los de `solo_si_atado` que nunca salen a rescatar una
    pista del grupo 1-2: quien solo entra con su lista (Dani Gimeno).

    `cubrir` son las pistas que el motor ha decidido que llevan entrenador
    (las demás tienen dos como mucho y una vecina con entrenador que las
    vigila). Con ellas no se busca otro patrón: se cubren esas.
    """
    from .reparto_pistas import opciones_de_pistas, repartir_entre_sedes

    blandos = blandos or {}
    pesos = pesos or {}
    con_quien = con_quien if con_quien is not None else Counter()
    sesiones = sesiones if sesiones is not None else Counter()

    def contratados(miembros, mapa):
        return {cid for j in miembros for cid in mapa.get(j, set())}

    ids_elegibles = {c.id for c in elegibles}
    todas = list(courts)
    # Vetos (#«no debe entrenar con»): entrenadores prohibidos en cada pista
    # por alguno de sus jugadores. Es regla dura — antes se queda la pista sin
    # entrenador que romperla.
    vetos = vetos or {}
    vetado = {
        pista: {cid for j in miembros for cid in vetos.get(j, ())}
        for pista, miembros in courts.items()
    }
    divisiones = divisiones or {}
    protegidas = {
        pista for pista, miembros in courts.items()
        if nivel_protegido and any(
            divisiones.get(j) is not None and divisiones[j] <= nivel_protegido
            for j in miembros)
    }
    # Grupo del entrenador como límite, no como coste.
    por_id_todos = {c.id: c for c in elegibles}

    def dentro_del_grupo(pista, cid):
        if tolerancia_division is None:
            return True
        ent = por_id_todos[cid]
        for j in courts[pista]:
            nivel = divisiones.get(j)
            if nivel is None:
                continue
            if ent.distancia_division(nivel) > tolerancia_division:
                return False
        return True

    grupo_ok = {pista: {c for c in ids_elegibles if dentro_del_grupo(pista, c)}
                for pista in courts}
    for pista, admite in grupo_ok.items():
        # Si con el límite no queda nadie, se levanta: antes un entrenador de
        # otro grupo que una pista sin nadie.
        if not admite - vetado.get(pista, set()):
            grupo_ok[pista] = set(ids_elegibles)
    afin = {
        (pista, cid): _afinidad(miembros, cid, pesos, con_quien, sesiones)
        for pista, miembros in courts.items() for cid in ids_elegibles
    }

    por_id = {c.id: c for c in elegibles}

    def valor(pista, cid):
        if cid in vetado.get(pista, ()) or cid not in grupo_ok[pista]:
            return -VALOR_PROHIBIDO
        if cid in solo_si_atado and cid not in contratados(courts[pista], sponsors):
            return -VALOR_PROHIBIDO
        return (round(ESCALA_AFINIDAD * afin[(pista, cid)]) - load[cid]
                + ESCALA_AFINIDAD * _puntos_color(courts[pista], cid, responsable_de, color_de)
                - _penalizacion_division(courts[pista], por_id[cid], divisiones, peso_division))

    # Candidatos por pista: todos los disponibles, primero el del contrato duro
    # y después por afinidad.
    candidatos = {}
    for pista, miembros in courts.items():
        duros = contratados(miembros, sponsors)
        posibles = (ids_elegibles & grupo_ok[pista]) - vetado.get(pista, set())
        posibles -= {c for c in solo_si_atado if c not in duros}
        candidatos[pista] = sorted(
            posibles,
            key=lambda c: (c not in duros, -afin[(pista, c)], load[c], c),
        )

    def emparejar(pistas, atados_extra=None, ocupados=frozenset()):
        """El mejor reparto sobre `pistas`. `atados_extra` son ataduras
        forzadas {entrenador: pista}; `ocupados`, entrenadores ya colocados."""
        de_entrenador = {}
        # El contrato duro se ata antes: si no, el emparejamiento le da ese
        # entrenador a otra pista y el contrato se rompe siempre.
        for pista in pistas:
            duros = contratados(courts[pista], sponsors)
            for cid in candidatos[pista]:
                if cid in duros and cid not in de_entrenador and cid not in ocupados:
                    de_entrenador[cid] = pista
                    break
        for cid, pista in (atados_extra or {}).items():
            if pista not in pistas or cid not in candidatos[pista] or cid in ocupados:
                continue
            de_entrenador = {c: p for c, p in de_entrenador.items()
                             if c != cid and p != pista}
            de_entrenador[cid] = pista
        tomadas = set(de_entrenador.values())
        libres = [c for c in sorted(ids_elegibles)
                  if c not in de_entrenador and c not in ocupados]
        asignado = {pista: cid for cid, pista in de_entrenador.items()}
        asignado.update(_mejor_asignacion(
            [p for p in pistas if p not in tomadas], libres, valor))
        return asignado

    # --- Pocos entrenadores: qué pistas llevan uno -----------------------
    permitidas = set(todas)
    # El patrón alterno (1-3-4-6-7, cada pista descubierta entre dos cubiertas)
    # se decide con los entrenadores que entran en el reparto. Los de banquillo
    # no cuentan: si contaran, bastaría con tenerlos ahí para que el patrón
    # dejara de aplicarse.
    del_reparto = ids_elegibles - set(solo_si_atado)
    modo_vecinas = bool(info_pistas) and 0 < len(del_reparto) < len(todas)
    por_sede, orden_sede, ubicacion = defaultdict(dict), {}, {}
    if modo_vecinas:
        for pista in todas:
            sede, numero, rango = info_pistas.get(pista, (None, None, 0))
            if numero is None:
                modo_vecinas = False
                break
            por_sede[sede][numero] = pista
            orden_sede[sede] = rango
            ubicacion[pista] = (sede, numero)
    if cubrir is not None:
        permitidas = set(cubrir) & set(todas)
    elif modo_vecinas:
        sedes = sorted(por_sede, key=lambda x: (orden_sede[x], str(x)))
        reparto = repartir_entre_sedes(
            {x: list(por_sede[x]) for x in sedes}, len(del_reparto), sedes,
        )
        opciones = {}
        for x in sedes:
            fijas = {n for n, p in por_sede[x].items()
                     if contratados(courts[p], sponsors) & ids_elegibles}
            prefer = {n for n, p in por_sede[x].items() if p in protegidas}
            opciones[x] = [
                {por_sede[x][n] for n in elegidas}
                for elegidas in opciones_de_pistas(
                    list(por_sede[x]), reparto[x], fijas=fijas,
                    preferidas=prefer,
                )
            ]
        # El reparto geométricamente mejor puede no cubrirse entero (un
        # contrato duro ata a quien ata): esa pista se queda sin entrenador y su
        # vecina, huérfana. Se prueba cada sede, en orden de llenado, con sus
        # repartos de mejor a peor, y se queda el primero que se cubre entero
        # (si ninguno, el que más cubre).
        elegido = {x: opciones[x][0] for x in sedes}
        for x in sedes:
            # Las opciones ya vienen ordenadas —geometría primero y, a
            # igualdad, las de grupo alto cubiertas—; aquí solo se descartan
            # las que no se pueden cubrir enteras.
            mejor, mejor_n = elegido[x], -1
            for opcion in opciones[x][:200]:
                prueba = set(opcion)
                for y in sedes:
                    if y != x:
                        prueba |= elegido[y]
                n = len(emparejar([p for p in todas if p in prueba]))
                if n > mejor_n:
                    mejor, mejor_n = opcion, n
                if n == len(prueba):
                    break
            elegido[x] = mejor
        permitidas = set().union(*elegido.values())

    def huerfana(pista, asig):
        """Sin entrenador y, con pocos, sin vecina que lo tenga."""
        if pista in asig:
            return False
        if not modo_vecinas:
            return True
        sede, numero = ubicacion[pista]
        return not any(por_sede[sede].get(v) in asig for v in (numero - 1, numero + 1))

    def completar(asig):
        """Lo previsto que no se pudo cubrir se intenta con los que sobran. Y
        si el motor ha dejado pistas sin entrenador pero sobra alguno, va a
        ellas: vigilada está bien, con entrenador está mejor."""
        if ((modo_vecinas or cubrir is not None)
                and del_reparto - set(asig.values())):
            resto = [p for p in todas if p not in asig]
            asig.update(emparejar(resto, ocupados=set(asig.values())))
        return asig

    asignado = completar(emparejar([p for p in todas if p in permitidas]))

    # --- Contratos blandos: solo si no cuesta ninguna pista --------------
    duros_del_turno = set()
    for pista in todas:
        duros_del_turno |= contratados(courts[pista], sponsors)
    for jid in sorted(blandos):
        pista = next((p for p in todas if jid in courts[p]), None)
        if pista is None:
            continue
        for cid in sorted(blandos[jid]):
            if (cid not in ids_elegibles or cid in duros_del_turno
                    or asignado.get(pista) == cid or cid not in candidatos[pista]):
                continue
            base = [p for p in todas if p in permitidas or p == pista]
            prueba = completar(emparejar(base, atados_extra={cid: pista}))
            if (len(prueba) >= len(asignado)
                    and sum(huerfana(p, prueba) for p in todas)
                    <= sum(huerfana(p, asignado) for p in todas)):
                asignado = prueba
                break

    # Grupo 1-2 nunca sin entrenador: si el reparto no ha llegado, se saca a
    # uno del banquillo. Es el único caso en que entran sin que les llame un
    # contrato o una franja.
    for pista in sorted(protegidas - set(asignado)):
        # Entre dos pistas con entrenador no está sola: la vigila el de al
        # lado, y el club lo da por bueno.
        if not huerfana(pista, asignado):
            continue
        ocupados = set(asignado.values())
        libres = [c for c in sorted((solo_si_atado - set(sin_rescate)) & ids_elegibles)
                  if c not in ocupados and c not in vetado.get(pista, ())]
        if libres:
            asignado[pista] = min(libres, key=lambda c: (
                _penalizacion_division(courts[pista], por_id[c], divisiones,
                                       peso_division),
                load[c], c))

    # Un entrenador no puede estar en dos pistas del mismo turno: el club lo
    # ve mal y prefiere la pista sin entrenador, vigilada desde la de al lado.
    # Las pistas que quedan huérfanas se listan igual, para que el informe
    # avise.
    repetidos = [pista for pista in sorted(todas)
                 if candidatos[pista] and huerfana(pista, asignado)]
    for cid in asignado.values():
        load[cid] += 1
    return asignado, repetidos


def _player_basico(j):
    """Lo justo de un jugador para ver qué reglas rompe al compartir pista."""
    return Player(
        id=j.id, division=j.division.nivel if j.division_id else None,
        sexo=j.sexo or None, edad=j.edad,
    )


def _reglas_de_pista(yo, otros, span):
    """Las reglas base que rompe `yo` metiéndose con `otros`, una vez cada
    una: «división D1–D6», «chico/chica», «edad (14 a 26 años)»."""
    from .pairing import reglas_rotas

    tipos = set()
    for o in otros:
        for r in reglas_rotas(yo, o, span):
            tipos.add(r.split(" ")[0])
    rotas = []
    if "división" in tipos:
        niveles = [p.division for p in [yo, *otros] if p.division is not None]
        rotas.append(f"división D{min(niveles)}–D{max(niveles)}")
    if "chico/chica" in tipos:
        rotas.append("chico/chica")
    if "edad" in tipos:
        edades = [p.edad for p in [yo, *otros] if p.edad]
        rotas.append(f"edad ({min(edades)} a {max(edades)} años)")
    return rotas


def _dificiles(jugadores, fase, res):
    """Los que en el reparto normal se quedaron fuera o solos en una pista:
    con ellos (y solo con ellos) se puede forzar."""
    dentro, solos = set(), set()
    for t in fase:
        for m in res.franjas.get(t.id, {}).values():
            dentro.update(m)
            if len(m) == 1:
                solos.update(m)
    return {p.id for p in jugadores if p.id not in dentro} | solos


def _motivo_forzado(miembros, por_id, cfg, es_tarde, vetoes, declaradas):
    """Si en esta pista hay alguna pareja que las reglas no admiten (pista
    forzada por el motor), el aviso con lo que rompe; si no, ""."""
    from .pairing import DURO, _motivo

    gente = [por_id[j] for j in miembros if j in por_id]
    rota = False
    for i, a in enumerate(gente):
        for b in gente[i + 1:]:
            if frozenset((a.id, b.id)) in declaradas:
                continue
            if _motivo(a, b, vetoes, cfg.aplicar_vecindad, cfg.vecindad_max,
                       cfg.estiron_division if es_tarde else 0,
                       cfg.estiron_edad if es_tarde else 0) == DURO:
                rota = True
    if not rota:
        return ""
    reglas = _reglas_de_pista(gente[0], gente[1:], cfg.vecindad_max)
    for k in range(1, len(gente)):
        for r in _reglas_de_pista(gente[k], gente[k + 1:], cfg.vecindad_max):
            if r.split(" ")[0] not in {x.split(" ")[0] for x in reglas}:
                reglas.append(r)
    return ("Forzada para que entrene: " + ", ".join(reglas))[:200] if reglas else ""


def _rellenar_huecos(semana, dia, grupo, fuera, por_id, franjas_de, cfg, vetoes,
                     vetos_coach, solo_con, es_tarde, overrides, courts_by_id,
                     report):
    """Mete a quien se ha quedado en el banquillo en los huecos de las pistas
    ya abiertas del bloque, aunque rompa las reglas base —división, chico/chica,
    edad—, para que entrene todo el mundo (14/10/2026, Iván con Nik y Chimo).

    No abre pistas ni se salta la franja del jugador, el tope de la pista (2
    sin entrenador, y 2 en la que vigila a la de al lado), una rencilla, un
    veto de entrenador, la superficie estricta ni la pista de quien solo entra
    con su lista. Si había hueco y solo lo impide una de esas, queda un aviso
    en el banquillo. Devuelve {jugador: asignación creada}."""
    from academy.models import Jugador as _J

    tope_bloque = cfg.capacidad_tarde if es_tarde else cfg.capacidad_manana
    pistas = defaultdict(list)
    for a in Asignacion.objects.filter(
        semana=semana, dia=dia, turno__in=grupo,
    ).select_related("jugador__division"):
        pistas[(a.turno_id, a.pista_id)].append(a)
    jugadores = {}

    def player(jid, j=None):
        if jid not in jugadores:
            jugadores[jid] = por_id.get(jid) or _player_basico(
                j or _J.objects.select_related("division").get(pk=jid))
        return jugadores[jid]

    def con_entrenador(filas):
        return next((a.entrenador_id for a in filas if a.entrenador_id), None)

    def vigila_a_otra(turno_id, pista_id):
        c = courts_by_id[pista_id]
        if c.number is None:
            return False
        for (t, p), filas in pistas.items():
            o = courts_by_id.get(p)
            if (t == turno_id and o is not None and o.venue_id == c.venue_id
                    and o.number in (c.number - 1, c.number + 1)
                    and con_entrenador(filas) is None):
                return True
        return False

    turnos = {t.id: t for t in grupo}
    fecha = semana.fecha_inicio + timedelta(days=dia)
    metidos = {}
    orden = sorted(fuera, key=lambda jid: -(por_id[jid].priority if jid in por_id else 0))
    for jid in orden:
        yo = player(jid)
        opciones, impide = [], set()
        for tid in franjas_de.get(jid, {}):
            for (t, pid), filas in pistas.items():
                if t != tid or not filas:
                    continue
                c = courts_by_id.get(pid)
                if c is None:
                    continue
                coach = con_entrenador(filas)
                tope = min(c.capacity, tope_bloque)
                if coach is None or vigila_a_otra(t, pid):
                    tope = min(tope, 2)
                if len(filas) >= tope:
                    continue
                otros = [a.jugador_id for a in filas]
                if any(_normalise(jid, o) in vetoes for o in otros):
                    impide.add("tiene una rencilla con alguien de la pista libre")
                    continue
                if yo.surface_pref and c.surface and c.surface != yo.surface_pref:
                    impide.add(f"solo entrena en {yo.surface_pref.lower()}")
                    continue
                if coach and coach in vetos_coach.get(jid, ()):
                    impide.add("no puede entrenar con el entrenador de la pista libre")
                    continue
                if coach in solo_con and jid not in solo_con[coach]:
                    continue
                rotas = _reglas_de_pista(
                    yo, [player(a.jugador_id, a.jugador) for a in filas], cfg.vecindad_max)
                distancia = max((abs((yo.division or 0) - (player(o).division or 0))
                                 for o in otros), default=0)
                opciones.append((len(rotas), distancia, c.number or 0, t, pid, coach, rotas))
        if not opciones:
            if impide:
                AvisoBanquillo.objects.create(
                    semana=semana, dia=dia, bloque=grupo[0].bloque, jugador_id=jid,
                    motivo="Había sitio, pero " + "; ".join(sorted(impide)) + ".")
            continue
        _n, _d, _num, t, pid, coach, rotas = min(opciones)
        a = Asignacion.objects.create(
            semana=semana, dia=dia, turno=turnos[t], pista_id=pid, jugador_id=jid,
            entrenador_id=coach,
            estado=_effective_state(overrides, jid, turnos[t]),
            forzada=bool(rotas),
            motivo_forzado=("Forzada para que entrene: " + ", ".join(rotas))[:200] if rotas else "",
        )
        pistas[(t, pid)].append(a)
        metidos[jid] = a
        if rotas:
            report.setdefault("forzadas", []).append(
                {"dia": dia, "turno": turnos[t].codigo, "pista": pid, "jugador": jid,
                 "reglas": rotas})
    return metidos


def _abrir_satelites(semana, dia, grupo, fuera, por_id, franjas_de, cfg, vetoes,
                     overrides, satelites, report):
    """Quien sigue en el banquillo después del relleno forzado va a los clubs
    satélite, sin entrenador: Sta. Bárbara primero, luego Bétera y Mas
    Camarena (21/10/2026). Solo por la mañana; si hay que redistribuir, se hace
    a mano.

    Se junta con alguien de su nivel si lo hay; si no, abre pista (aunque sea
    solo él) y, si ya no quedan pistas libres, se mete donde haya hueco
    rompiendo las reglas base. Nunca se salta una rencilla, la superficie
    estricta ni a quien solo entrena en el Resort. Devuelve {jugador: asignación}."""
    from academy.models import Jugador as _J

    sedes = dict(Sede.objects.filter(
        id__in={c.venue_id for c in satelites}).values_list("id", "nombre"))
    pistas = defaultdict(list)
    for a in Asignacion.objects.filter(
        semana=semana, dia=dia, turno__in=grupo,
        pista_id__in=[c.id for c in satelites],
    ).select_related("jugador__division"):
        pistas[(a.turno_id, a.pista_id)].append(a)
    jugadores = {}

    def player(jid, j=None):
        if jid not in jugadores:
            jugadores[jid] = por_id.get(jid) or _player_basico(
                j or _J.objects.select_related("division").get(pk=jid))
        return jugadores[jid]

    def en_franja(tid):
        return sum(len(f) for (t, _p), f in pistas.items() if t == tid)

    orden_pistas = sorted(satelites, key=lambda c: (c.fill_rank, c.venue_id, c.number or 0))
    turnos = {t.id: t for t in grupo}
    metidos = {}
    orden = sorted(fuera, key=lambda jid: (-player(jid).priority,
                                           player(jid).division or 99))
    for jid in orden:
        yo = player(jid)
        if yo.solo_central:
            AvisoBanquillo.objects.create(
                semana=semana, dia=dia, bloque=grupo[0].bloque, jugador_id=jid,
                motivo="No cabe en el Resort y solo entrena allí.")
            continue
        opciones, impide = [], set()
        for tid in franjas_de.get(jid, {}):
            for n, c in enumerate(orden_pistas):
                filas = pistas.get((tid, c.id), [])
                coach = next((a.entrenador_id for a in filas if a.entrenador_id), None)
                tope = min(c.capacity, cfg.capacidad_manana)
                if coach is None:
                    tope = min(tope, 2)
                if len(filas) >= tope:
                    continue
                if yo.surface_pref and c.surface and c.surface != yo.surface_pref:
                    impide.add(f"solo entrena en {yo.surface_pref.lower()}")
                    continue
                otros = [a.jugador_id for a in filas]
                if any(_normalise(jid, o) in vetoes for o in otros):
                    impide.add("tiene una rencilla con quien queda en los satélites")
                    continue
                rotas = _reglas_de_pista(
                    yo, [player(a.jugador_id, a.jugador) for a in filas], cfg.vecindad_max)
                # Con alguien sin romper nada, mejor que abrir; abrir, mejor
                # que forzar. Desempata la franja con menos gente y el orden
                # de las pistas (Sta. Bárbara 1, 2, 3, Bétera…).
                clase = 0 if (filas and not rotas) else (1 if not filas else 2)
                opciones.append((clase, len(rotas), en_franja(tid), n, tid, c, rotas))
        if not opciones:
            AvisoBanquillo.objects.create(
                semana=semana, dia=dia, bloque=grupo[0].bloque, jugador_id=jid,
                motivo=("No cabe en el Resort ni en los satélites"
                        + (": " + "; ".join(sorted(impide)) if impide else "") + "."))
            continue
        _cl, _n, _f, _o, tid, c, rotas = min(opciones)
        motivo = f"{sedes.get(c.venue_id, 'Satélite')} sin entrenador, para que no se quede en el banquillo"
        if rotas:
            motivo += ": " + ", ".join(rotas)
        a = Asignacion.objects.create(
            semana=semana, dia=dia, turno=turnos[tid], pista_id=c.id, jugador_id=jid,
            estado=_effective_state(overrides, jid, turnos[tid]),
            forzada=True, motivo_forzado=motivo[:200],
        )
        pistas[(tid, c.id)].append(a)
        metidos[jid] = a
        report.setdefault("satelites", []).append(
            {"dia": dia, "turno": turnos[tid].codigo, "pista": c.id, "jugador": jid,
             "sede": sedes.get(c.venue_id, ""), "reglas": rotas})
    return metidos


def _dias_de_invitados():
    """{jugador: {"2026-10-14": {"manana": "M2", …}}}: los días que viene cada
    invitado, de sus visitas aprobadas (14/10/2026)."""
    from academy.models import VisitaInvitado

    dias = defaultdict(dict)
    for jid, fecha, manana, tarde in VisitaInvitado.objects.filter(
        estado=VisitaInvitado.Estado.APROBADA,
        invitado__jugador_creado__isnull=False,
    ).values_list("invitado__jugador_creado_id", "fecha", "manana", "tarde"):
        fila = {}
        if manana is not None:
            fila["manana"] = manana
        if tarde is not None:
            fila["tarde"] = tarde
        dias[jid][fecha.isoformat()] = fila
    return dias


def _horario_del_dia(horario, invitados, fecha, dia, turno_por_codigo):
    """El horario de la semana con los invitados de ese día: el invitado viene
    en los bloques que se marcaron para esa fecha y ningún otro día."""
    if not invitados:
        return horario
    hoy = dict(horario)
    for jid, fechas in invitados.items():
        fila = fechas.get(fecha.isoformat()) or {}
        man, tar = fila.get("manana"), fila.get("tarde")
        hoy[(jid, dia)] = (
            turno_por_codigo.get(man) if man else None,
            turno_por_codigo.get(tar) if tar else None,
            man is not None, tar is not None,
        )
    return hoy


def _con_la_de_menos(entrenador_de, pistas, vigilancia, courts_by_id, atados,
                     vetos, solo_atado):
    """El entrenador que cuida dos pistas —la suya y la que vigila al lado—
    va en el cuadrante con la que menos jugadores tiene (14/10/2026).

    No se cambia si así la resina se queda sin entrenador, si alguno de los de
    la pista nueva le tiene vetado, si tiene contrato con alguno de la suya, ni
    si es de los que solo entran por unos jugadores (banquillo, Dani)."""
    for vigilada, suya in vigilancia.items():
        cid = entrenador_de.get(suya)
        if (cid is None or vigilada in entrenador_de or cid in solo_atado
                or vigilada not in pistas or suya not in pistas
                or len(pistas[vigilada]) >= len(pistas[suya])):
            continue
        if (courts_by_id[suya].surface == "RESINA"
                and courts_by_id[vigilada].surface != "RESINA"):
            continue
        if any(cid in vetos.get(j, ()) for j in pistas[vigilada]):
            continue
        if any(cid in atados.get(j, ()) for j in pistas[suya]):
            continue
        entrenador_de[vigilada] = entrenador_de.pop(suya)


@transaction.atomic
def _con_preferencia(base, extra):
    """`base` (contratos) más las preferencias de esta franja, sin tocar `base`."""
    if not extra:
        return base
    fusion = defaultdict(set, {j: set(c) for j, c in base.items()})
    for jid, coaches in extra.items():
        fusion[jid] |= coaches
    return fusion


def generate(semana: Semana, dias=None, bloques=None, mantener_manual=True) -> dict:
    """Generate (or regenerate) the cuadrante.

    mantener_manual: lo puesto a mano (y los mandados al banquillo a mano) se
    queda. Con False se rehace todo desde cero (15/10/2026: lo elige quien
    regenera; la generación de las 19:00 siempre lo mantiene).

    dias: iterable of day indices (por defecto de lunes a sábado).

    El sábado solo tiene mañana: en el cuadrante real son dos bandas
    (8:30-10:00 y 10:00-11:30), que se corresponden con M1 y M2 aunque la
    segunda empiece media hora antes. Por la tarde el club no abre, igual que
    el miércoles. Quién entrena el sábado sale del horario semanal: sin fila de
    sábado declarada, nadie viene.
    bloques: restrict to {'MANANA','TARDE'} shifts — used by the afternoon
             regeneration so the morning history stays untouched.

    Cada bloque se decide de una vez: la mañana (M1 y M2) y la tarde (T1 y
    T2) reparten a sus jugadores entre las franjas en vez de llenar la primera
    y dejar las demás vacías. El turno propio de una escuela (JP) va aparte.
    """
    dias = list(dias) if dias is not None else [d for d, _ in DIAS]
    turnos = list(Turno.objects.filter(activo=True))
    if bloques:
        turnos = [t for t in turnos if t.bloque in bloques]
    # Config por escuela (#6): turno único (p. ej. Junior Program solo JP) y si
    # sus jugadores solo pueden ir al Resort (sin satélites).
    from academy.models import Escuela

    escuela_cfg = {
        e.id: (e.turno_unico_id, e.solo_central) for e in Escuela.objects.all()
    }
    # Mapa inverso: para cada turno que alguna escuela tenga como exclusivo
    # (turno_unico), anota qué escuela es. Es la regla "el turno JP solo admite
    # jugadores de la escuela Junior Program" — complementaria de la clásica
    # "los jugadores JP solo van al turno JP".
    turnos_exclusivos: dict[int, int] = {}
    for escuela_id, (turno_unico_id, _solo_central) in escuela_cfg.items():
        if turno_unico_id and turno_unico_id not in turnos_exclusivos:
            turnos_exclusivos[turno_unico_id] = escuela_id
    # Por la tarde no hay franja reservada (13/10/2026): T2 es la de la
    # «Escuela», pero cuando T1 se llena el que no cabe pasa a T2 en vez de
    # quedarse sin entrenar. Los alumnos de esa escuela siguen yendo solo a T2.
    de_tarde = set(Turno.objects.filter(bloque=Turno.Bloque.TARDE)
                   .values_list("id", flat=True))
    turnos_exclusivos = {t: e for t, e in turnos_exclusivos.items()
                         if t not in de_tarde}
    grupos = _grupos_de_turnos(turnos, turnos_exclusivos)

    cfg = ConfiguracionMotor.get_solo()
    # Tope de toda la generación (21/10/2026): una semana tarda en torno a un
    # minuto; si alguna se complica, al pasar de MOTOR_TOPE_GENERACION_S (2
    # minutos) lo que falte se resuelve con 1 s por llamada, sin dejar días a
    # medias.
    fin_generacion = time.monotonic() + float(
        os.environ.get("MOTOR_TOPE_GENERACION_S", "120"))
    # Los satélites entran en el reparto solo en modo «desbordar». En modo
    # «rescate» (el normal desde el 21/10/2026) se abren después, sin
    # entrenador, para quien se quedaría en el banquillo.
    todas = _build_courts()
    satelites = [c for c in todas if c.is_satellite]
    courts = (todas if cfg.modo_satelites == ConfiguracionMotor.ModoSatelites.DESBORDAR
              else [c for c in todas if not c.is_satellite])
    courts_by_id = {c.id: c for c in todas}
    vetoes = _vetoes()
    vetos_coach = _vetos_entrenador()
    sponsors = _sponsor_map()
    blandos = _sponsor_map("BLANDO")
    # «Si entrena en M1, entrena con Iván»: solo ata en esa franja, así que se
    # suma al contrato justo en el turno que toca.
    pref_franja_duro = _preferencias_franja("DURO")
    pref_franja_blando = _preferencias_franja("BLANDO")
    load: Counter = Counter()
    report = {"dias": {}, "overflow": [], "unassigned": []}

    # --- Entrenadores disponibles (#10/#11) y con quién entrena cada alumno --
    # Los de reserva no entran en el reparto: están para ponerlos a mano.
    # Los de banquillo (Sergio, Iván, Jorge) no entran en el reparto, pero sí
    # cuando un contrato o una preferencia de franja les llama por su nombre.
    # Los de «nunca en automático» ni siquiera eso: solo a mano.
    all_coaches = list(
        Entrenador.objects.filter(
            activo=True, disponible_semana=True, solo_manual=False)
    )
    de_banquillo = {c.id for c in all_coaches if c.reserva}
    # Quien solo entra en pista con unos jugadores (14/10/2026: Dani Gimeno,
    # con sus seis del grupo 1-2): {entrenador: jugadores}. Mañana y tarde.
    solo_con = defaultdict(set)
    for cid, jid in Entrenador.solo_con.through.objects.filter(
        entrenador_id__in=[c.id for c in all_coaches]
    ).values_list("entrenador_id", "jugador_id"):
        solo_con[cid].add(jid)
    pesos = pesos_de_entrenamiento()
    # Nivel de cada alumno: lo usa el reparto de entrenadores para respetar
    # los grupos de cada uno.
    from academy.models import Jugador as _JD

    divisiones_jugador = dict(
        _JD.objects.filter(activo=True, division__isnull=False)
        .values_list("id", "division__nivel")
    )

    # Preferencias de superficie estrictas por jugador (#1).
    from academy.models import PreferenciaSuperficie

    # Las que tienen fechas van delante: «del 5 al 9, resina» —declarada en el
    # calendario para preparar un torneo— manda sobre la superficie fija de la
    # ficha, y `_jugador_motor` se queda con la primera que cubre el día.
    surface_prefs: dict[int, list] = defaultdict(list)
    for ps in sorted(
        PreferenciaSuperficie.objects.filter(estricta=True),
        key=lambda ps: (ps.fecha_desde is None and ps.fecha_hasta is None, -ps.id),
    ):
        surface_prefs[ps.jugador_id].append(
            (ps.superficie, ps.fecha_desde, ps.fecha_hasta)
        )

    # Parejas preferidas (#5): HARD misma pista, SOFT bonus.
    from academy.models import PreferenciaPareja

    pairs_hard: set = set()
    pairs_soft: set = set()
    for pp in PreferenciaPareja.objects.filter(activa=True):
        key = frozenset((pp.jugador_id, pp.jugador_objetivo_id))
        (pairs_hard if pp.tipo == "HARD" else pairs_soft).add(key)
    # Las declaradas a mano saltan las reglas de emparejamiento; las parejas
    # que el motor se inventa por la mañana para repetirlas por la tarde, no.
    pairs_declaradas = pairs_hard | pairs_soft

    # Recuento de sesiones para acercarse a los % objetivo a lo largo de la semana.
    coach_share: Counter = Counter()      # (jugador_id, coach_id) -> nº sesiones
    player_sessions: Counter = Counter()  # jugador_id -> nº sesiones
    # Veces que cada jugador se ha quedado sin pista estando disponible. Sube
    # su prioridad la próxima vez, para que no se quede fuera siempre el mismo.
    # Solo cuenta los días que se generan: de los que no se rehacen no se sabe.
    banquillo: Counter = Counter()

    # Si se regeneran solo ciertos días o bloques (p. ej. a mitad de semana tras
    # una lesión), las sesiones de los días que NO se tocan cuentan para los
    # porcentajes de cada entrenador.
    qs_prev = Asignacion.objects.filter(semana=semana)
    if bloques:
        qs_prev = qs_prev.exclude(dia__in=dias, turno__bloque__in=bloques)
    else:
        qs_prev = qs_prev.exclude(dia__in=dias)
    for a in qs_prev:
        player_sessions[a.jugador_id] += 1
        if a.entrenador_id:
            coach_share[(a.jugador_id, a.entrenador_id)] += 1

    # Horario semanal de cada jugador: (jugador, día) -> (turno mañana, tarde).
    from academy.models import HorarioJugador

    horario = {
        (h.jugador_id, h.dia): (h.turno_manana_id, h.turno_tarde_id,
                                h.entrena_manana, h.entrena_tarde)
        for h in HorarioJugador.objects.all()
    }
    invitados = _dias_de_invitados()
    # Grupos de color (pestaña Grupos): de quién es cada alumno y de qué color
    # es cada entrenador.
    from academy.models import Coach

    responsable_de = dict(_JD.objects.filter(
        activo=True, entrenador_responsable__isnull=False,
    ).values_list("id", "entrenador_responsable_id"))
    color_de = {}
    for coach in Coach.objects.filter(activo=True).exclude(color="").prefetch_related("entrenadores"):
        for e in coach.entrenadores.all():
            color_de.setdefault(e.id, coach.color)
    turno_por_codigo = dict(Turno.objects.values_list("codigo", "id"))
    # Jornada semanal de cada entrenador: (entrenador, día) -> (mañana, tarde).
    from academy.models import HorarioEntrenador

    jornada = {
        (h.entrenador_id, h.dia): (h.manana, h.tarde)
        for h in HorarioEntrenador.objects.all()
    }

    for dia in dias:
        # Quién ha entrenado con quién esta mañana: por la tarde se intenta
        # repetir la pareja (blando), que es como lo hace el club.
        parejas_manana: set = set()
        # Sesiones ya dadas hoy a cada jugador: alimenta el tope diario (#18)
        # y se reinicia cada jornada.
        sesiones_hoy: Counter = Counter()
        sesiones_bloque: Counter = Counter()   # (jugador, bloque) -> sesiones
        # Franjas que ya ocupa cada entrenador hoy. JP (12:30-14:30) y T1
        # (14:15-15:30) se pisan quince minutos, así que sin esto el mismo
        # entrenador acaba en los dos a la vez.
        ocupacion_coach: dict[int, list] = defaultdict(list)
        overrides = _overrides(semana, dia)
        recent = _recent_partners(semana, dia)
        horario_hoy = _horario_del_dia(
            horario, invitados, semana.fecha_inicio + timedelta(days=dia), dia,
            turno_por_codigo)
        # Tope duro de días juntos a la semana (3 en el club): la pareja que ya
        # lo ha alcanzado no comparte pista hoy, tampoco si está declarada. Se
        # trata como una rencilla solo para este día.
        topados = {
            par for par, dias_par in _dias_juntos(semana, dia, dias).items()
            if cfg.max_dias_misma_pista and len(dias_par) >= cfg.max_dias_misma_pista
        }
        vetoes_dia = vetoes | topados
        libres = {frozenset(p) for p in topados}
        pairs_hard_dia = pairs_hard - libres
        pairs_soft_dia = pairs_soft - libres
        pairs_declaradas_dia = pairs_declaradas - libres
        # Entrenadores fuera por vacaciones ese día (#11) y overrides del día (#10).
        fecha = semana.fecha_inicio + timedelta(days=dia)
        # Ausencias del entrenador ese día. Pueden ser de un bloque o de una
        # franja («el martes no puede a las 8:30»): se miran turno a turno.
        vac_de = defaultdict(list)
        for v in VacacionesEntrenador.objects.filter(
            fecha_inicio__lte=fecha, fecha_fin__gte=fecha
        ):
            vac_de[v.entrenador_id].append(v)
        coach_ovr = {
            d.entrenador_id: d
            for d in DisponibilidadEntrenador.objects.filter(semana=semana, dia=dia)
        }

        def elegibles_para(turno, presentes=frozenset()):
            """Entrenadores que pueden dar clase en este turno y no están ya en
            otra pista a esa hora. Quien solo entra con unos jugadores, solo si
            alguno está entre los `presentes`."""
            ini_t, fin_t = turno.horas(fecha)
            return [
                c for c in all_coaches
                if motivo_no_disponible(c, dia, turno, fecha, vac_de, jornada, coach_ovr) is None
                # No puede estar en dos pistas a la vez.
                and not any(i < fin_t and f > ini_t for i, f in ocupacion_coach[c.id])
                and not (solo_con.get(c.id)
                         and not solo_con[c.id] & set(presentes))
            ]

        def atados_de(turno):
            """Contratos duros de este turno: los de siempre y las preferencias
            de franja. Quien solo entra con su lista no se ata por contrato (Dani
            lo tenía con Taberner y acababa en su pista aunque fuera con alguien
            de fuera): a él le da la pista el motor, y solo de los suyos."""
            base = _con_preferencia(sponsors, pref_franja_duro.get(turno.id))
            if not solo_con:
                return base
            return {j: c - set(solo_con) for j, c in base.items() if c - set(solo_con)}

        def del_reparto(turno, presentes):
            """Los que el reparto puede poner: los elegibles menos los de
            banquillo."""
            return {c.id for c in elegibles_para(turno, presentes)
                    if c.id not in de_banquillo}

        # Los avisos del banquillo de lo que se rehace (una vez por bloque: la
        # mañana tiene más de un grupo de franjas).
        AvisoBanquillo.objects.filter(
            semana=semana, dia=dia,
            bloque__in={g[0].bloque for g in grupos},
        ).delete()
        for grupo in grupos:
            # El club cierra algunas medias jornadas: ahí no se reparte nada y,
            # además, se limpia lo que hubiera de antes. Saltar sin borrar deja
            # en pie el cuadrante de la última generación, que es justo lo que
            # no debe verse.
            bloque = grupo[0].bloque
            if not hay_entrenamiento(dia, bloque):
                Asignacion.objects.filter(
                    semana=semana, dia=dia, turno__in=grupo
                ).delete()
                continue
            # Franjas cerradas ese día (el viernes no hay T2): se vacían y se
            # quitan del grupo, para que nadie caiga en ellas.
            cerradas = [t for t in grupo if (dia, t.codigo) in FRANJA_CERRADA]
            if cerradas:
                Asignacion.objects.filter(
                    semana=semana, dia=dia, turno__in=cerradas
                ).delete()
                grupo = [t for t in grupo if t not in cerradas]
                if not grupo:
                    continue
            # Lo puesto a mano se queda (01/10/2026): rehacer el día rellena
            # alrededor sin mover esas pistas. Solo se cae quien después ha
            # declarado una falta para esa franja, porque no va a venir.
            fijas = [
                a for a in Asignacion.objects.filter(
                    semana=semana, dia=dia, turno__in=grupo, manual=True,
                ).select_related("turno")
                if _effective_state(overrides, a.jugador_id, a.turno, fecha)
                not in ESTADOS_EXCLUYENTES
            ] if mantener_manual else []
            ocupadas = set()
            fijos = set()
            for a in fijas:
                fijos.add(a.jugador_id)
                player_sessions[a.jugador_id] += 1
                sesiones_hoy[a.jugador_id] += 1
                sesiones_bloque[(a.jugador_id, bloque)] += 1
                if a.entrenador_id:
                    coach_share[(a.jugador_id, a.entrenador_id)] += 1
                if (a.turno_id, a.pista_id) not in ocupadas:
                    ocupadas.add((a.turno_id, a.pista_id))
                    if a.entrenador_id:
                        ocupacion_coach[a.entrenador_id].append(a.turno.horas(fecha))
            # A quien se mandó al banquillo a mano no se le vuelve a poner en
            # este bloque ese día.
            if not mantener_manual:
                QuitadoAMano.objects.filter(
                    semana=semana, dia=dia, turno__in=grupo).delete()
            quitados = set(QuitadoAMano.objects.filter(
                semana=semana, dia=dia, turno__bloque=bloque,
            ).values_list("jugador_id", flat=True))
            es_tarde = bloque == Turno.Bloque.TARDE
            players, franjas_de, max_franjas = _candidatos_bloque(
                semana, dia, grupo, sponsors, escuela_cfg, surface_prefs,
                turnos_exclusivos, cfg, sesiones_hoy, sesiones_bloque, horario_hoy,
                banquillo, overrides,
            )
            franjas_orig = {jid: dict(o) for jid, o in franjas_de.items()}
            fuera_del_motor = fijos | quitados
            # Todos los de este bloque, también los puestos a mano: hacen falta
            # para ver qué reglas rompe quien se mete en su pista.
            por_id_bloque = {p.id: p for p in players}
            players = [p for p in players if p.id not in fuera_del_motor]
            fijos_en = defaultdict(set)
            for a in fijas:
                fijos_en[a.turno_id].add(a.jugador_id)

            def presentes_en(turno, jugadores):
                return {p.id for p in jugadores} | fijos_en[turno.id]

            n_entrenadores = {
                t.id: len(del_reparto(t, presentes_en(t, players))) for t in grupo
            }
            # Por la tarde todos a la primera franja mientras quepan, aunque
            # salgan pistas de tres; por la mañana se reparten entre las dos.
            orden = sorted(grupo, key=lambda t: t.hora_inicio)
            # A una franja sin ningún entrenador no se manda a nadie mientras
            # otra del bloque sí tenga. Si no hay en ninguna, como siempre.
            sin_franja = []
            con_entrenador = {tid for tid, n in n_entrenadores.items() if n}
            if con_entrenador and len(con_entrenador) < len(grupo):
                for jid, opciones in franjas_de.items():
                    franjas_de[jid] = {f: pr for f, pr in opciones.items()
                                       if f in con_entrenador}
                sin_franja = [p.id for p in players if not franjas_de[p.id]]
                players = [p for p in players if franjas_de[p.id]]
            # #17: por la tarde nunca se usan los clubs satélite. Solo pistas de
            # sedes no satélite; el desbordamiento queda en banquillo, no spillea.
            turno_courts = (
                [c for c in courts if not c.is_satellite]
                if grupo[0].bloque == Turno.Bloque.TARDE
                else courts
            )
            def resolver(jugadores, fase, forzar=False, previo=None):
                """Empareja a `jugadores` en las franjas de `fase` de una vez."""
                ids = [t.id for t in fase]
                opciones = {p.id: {f: pr for f, pr in franjas_de[p.id].items()
                                   if f in ids} for p in jugadores}
                # Pistas con entrenador, como mucho tantas como entrenadores; y
                # las pistas de quien tiene contrato con alguien libre, con él.
                reparto = {t.id: del_reparto(t, presentes_en(t, jugadores))
                           for t in fase}
                regla = any(reparto.values())
                con_entrenador = {
                    t.id: {jid for jid, cids in atados_de(t).items()
                           if jid in opciones and cids & reparto[t.id]}
                    for t in fase
                }
                return solve_pairing(PairingInput(
                    players=jugadores,
                    courts=turno_courts,
                    vetoes=vetoes_dia,
                    recent_partners=recent,
                    time_limit_s=max(1.0, min(cfg.time_limit_s * len(fase),
                                              fin_generacion - time.monotonic())),
                    w_assign=cfg.peso_asignacion,
                    w_satellite=cfg.peso_satelite,
                    w_central=cfg.peso_central,
                    w_resina=cfg.peso_resina,
                    w_pista_division=cfg.peso_pista_division,
                    w_orden_pista=cfg.peso_orden_pista,
                    w_repeat=cfg.peso_repeticion,
                    apply_neighbor=cfg.aplicar_vecindad,
                    neighbor_span=cfg.vecindad_max,
                    # Por la tarde preferimos una pista de tres con entrenador
                    # a alguien solo, así que ahí no se abren individuales
                    # mientras haya con quién juntarse (con capacidad 3
                    # cualquier número de dos para arriba se reparte).
                    # En T2, que es lo que queda, sí: antes solo con su
                    # entrenador que sin entrenar.
                    min_occupancy=(2 if (es_tarde and len(jugadores) > 1
                                         and fase[0] == orden[0])
                                   else (1 if cfg.permitir_individuales else 2)),
                    w_density=(cfg.peso_densidad_tarde if es_tarde
                               else cfg.peso_densidad),
                    w_court=cfg.peso_pista_abierta,
                    pairs_hard=pairs_hard_dia,
                    pairs_soft=pairs_soft_dia | (parejas_manana if es_tarde else set()),
                    pairs_declaradas=pairs_declaradas_dia,
                    w_pair=cfg.peso_pareja,
                    franjas=ids,
                    franjas_de=opciones,
                    max_franjas=max_franjas,
                    entrenadores_franja=n_entrenadores,
                    w_balance=0 if es_tarde else cfg.peso_equilibrio_franjas,
                    capacidad_max=(cfg.capacidad_tarde if es_tarde
                                   else cfg.capacidad_manana),
                    # Tantas pistas como entrenadores: tope por la tarde,
                    # preferencia por la mañana (con dos por pista no siempre
                    # salen las cuentas).
                    # Por la tarde el tope cuenta también al banquillo: si hay
                    # un entrenador libre, se abre pista en vez de hacer un trío.
                    max_pistas=({t.id: len(elegibles_para(t, presentes_en(t, jugadores)))
                                 for t in fase} if es_tarde else {}),
                    pistas_objetivo={} if es_tarde else n_entrenadores,
                    w_exceso_pistas=0 if es_tarde else cfg.peso_exceso_pistas,
                    w_individual=cfg.peso_individual,
                    # El estirón (una división o un año de más) solo por la
                    # tarde, cuando falta gente: por la mañana ±1 estricto.
                    span_extra=cfg.estiron_division if es_tarde else 0,
                    edad_extra=cfg.estiron_edad if es_tarde else 0,
                    w_relajar=cfg.peso_relajar_vecindad,
                    ocupadas=ocupadas,
                    # Sin entrenadores en todo el bloque no se mira: se coloca
                    # como siempre y se reparte a mano.
                    entrenadores_reparto=(
                        {f: len(c) for f, c in reparto.items()} if regla else None),
                    con_entrenador=con_entrenador,
                    # Quien solo entra con su lista lleva, como mucho, una
                    # pista solo de ellos; si no, al banquillo.
                    dedicados={t.id: {cid: solo_con[cid] & set(opciones)
                                      for cid in reparto[t.id] if cid in solo_con}
                               for t in fase},
                    w_dedicado=PESO_JUNTOS_DEDICADO,
                    vigiladas_preferidas=VIGILADAS_PREFERIDAS,
                    w_vigilada_fuera=PESO_VIGILADA_FUERA,
                    resina_con_entrenador=True,
                    prioridad_cubrir={
                        p.id for p in jugadores
                        if cfg.nivel_protegido and p.division is not None
                        and p.division <= cfg.nivel_protegido},
                    w_cubrir_prioridad=PESO_ALTO_SIN_ENTRENADOR,
                    forzar=forzar,
                    forzar_con=_dificiles(jugadores, fase, previo) if previo else set(),
                    pista_previa=({(jid, f): c for f, pistas in previo.franjas.items()
                                   for c, m in pistas.items() for jid in m}
                                  if previo else {}),
                ))

            # Por la tarde, T1 primero con todos y, quien no cabe, a T2 (si
            # hace falta T2, se usa: 13/10/2026). La mañana se decide entera.
            fases = [[t] for t in orden] if es_tarde else [grupo]
            franjas_res, cubiertas_res, estados = {}, {}, {}
            forzado_en = set()
            dedicadas_res, vigilancia_res = {}, {}
            pendientes = list(players)
            for fase in fases:
                ids = {t.id for t in fase}
                jugadores = [p for p in pendientes if ids & set(franjas_de[p.id])]
                if not jugadores:
                    continue
                r = resolver(jugadores, fase)
                # Si sin romper reglas alguien se queda fuera, se repite
                # permitiendo pistas forzadas (16/10/2026), y se queda la
                # repetición si coloca a más.
                def colocados_en(res):
                    return {jid for t in fase for m in res.franjas.get(t.id, {}).values()
                            for jid in m}
                if any(p.id not in colocados_en(r) for p in jugadores):
                    r2 = resolver(jugadores, fase, forzar=True, previo=r)
                    if len(colocados_en(r2)) > len(colocados_en(r)):
                        r = r2
                        forzado_en.update(t.id for t in fase)
                for t in fase:
                    franjas_res[t.id] = r.franjas.get(t.id, {})
                    cubiertas_res[t.id] = r.cubiertas.get(t.id)
                    dedicadas_res[t.id] = r.dedicadas.get(t.id, {})
                    vigilancia_res[t.id] = r.vigilancia.get(t.id, {})
                    estados[t.id] = r.status
                puestos = {jid for t in fase for m in franjas_res[t.id].values()
                           for jid in m}
                pendientes = [p for p in pendientes if p.id not in puestos]
            # Regenerar = rehacer el bloque desde cero, menos lo puesto a mano.
            Asignacion.objects.filter(
                semana=semana, dia=dia, turno__in=grupo
            ).exclude(id__in=[a.id for a in fijas]).delete()
            colocados = set(fijos)
            for turno in grupo:
                pistas = franjas_res.get(turno.id, {})
                ini_t, fin_t = turno.horas(fecha)
                en_turno = {j for m in pistas.values() for j in m} | fijos_en[turno.id]
                # Un entrenador por pista, y a cada una quien más les toca a sus
                # alumnos según sus porcentajes y lo que llevan hecho esta semana.
                # Quien solo entra con su lista va a la pista que el motor le
                # ha dado y a ninguna otra, como los del banquillo con contrato.
                atados = _con_preferencia(atados_de(turno), {
                    jid: {cid}
                    for cid, pista in dedicadas_res.get(turno.id, {}).items()
                    for jid in pistas.get(pista, ())
                })
                sueltos = _con_preferencia(blandos, pref_franja_blando.get(turno.id))
                solo_atado = set(de_banquillo) | set(solo_con)
                entrenador_de, repetidos = _emparejar_entrenadores(
                    pistas, atados, elegibles_para(turno, en_turno), load,
                    pesos=pesos, con_quien=coach_share, sesiones=player_sessions,
                    blandos=sueltos, vetos=vetos_coach,
                    solo_si_atado=solo_atado,
                    info_pistas={c.id: (c.venue_id, c.number, c.fill_rank)
                                 for c in turno_courts},
                    divisiones=divisiones_jugador,
                    peso_division=cfg.peso_division_entrenador,
                    nivel_protegido=cfg.nivel_protegido,
                    tolerancia_division=cfg.tolerancia_division,
                    cubrir=cubiertas_res.get(turno.id),
                    sin_rescate=set(solo_con),
                    responsable_de=responsable_de, color_de=color_de,
                )
                _con_la_de_menos(entrenador_de, pistas, vigilancia_res.get(turno.id, {}),
                                 courts_by_id, atados, vetos_coach, solo_atado)
                sin_entrenador = [p for p in pistas if p not in entrenador_de]
                if sin_entrenador:
                    report.setdefault("sin_entrenador", []).append(
                        {"dia": dia, "turno": turno.codigo, "pistas": sin_entrenador}
                    )
                for court_id, member_ids in pistas.items():
                    coach_id = entrenador_de.get(court_id)
                    motivo_forzado = (
                        _motivo_forzado(member_ids, por_id_bloque, cfg, es_tarde,
                                        vetoes_dia, pairs_declaradas_dia)
                        if turno.id in forzado_en else "")
                    if motivo_forzado:
                        report.setdefault("forzadas", []).append(
                            {"dia": dia, "turno": turno.codigo, "pista": court_id,
                             "jugadores": list(member_ids), "reglas": motivo_forzado})
                    for jid in member_ids:
                        Asignacion.objects.create(
                            semana=semana,
                            dia=dia,
                            turno=turno,
                            pista_id=court_id,
                            jugador_id=jid,
                            entrenador_id=coach_id,
                            estado=_effective_state(overrides, jid, turno),
                            forzada=bool(motivo_forzado),
                            motivo_forzado=motivo_forzado,
                        )
                        # Historial para acercarse a los % objetivo (#12) y
                        # para los topes del día y del bloque (#18).
                        player_sessions[jid] += 1
                        sesiones_hoy[jid] += 1
                        sesiones_bloque[(jid, turno.bloque)] += 1
                        colocados.add(jid)
                        if coach_id:
                            coach_share[(jid, coach_id)] += 1
                    if coach_id:
                        ocupacion_coach[coach_id].append((ini_t, fin_t))
                    if courts_by_id[court_id].is_satellite:
                        report["overflow"].append(
                            {"dia": dia, "turno": turno.codigo, "pista": court_id}
                        )
                if repetidos:
                    report.setdefault("pistas_huerfanas", []).append(
                        {"dia": dia, "turno": turno.codigo, "pistas": repetidos}
                    )
                report["dias"].setdefault(dia, {})[turno.codigo] = estados.get(
                    turno.id, "SIN JUGADORES")
            if not es_tarde:
                a_mano = defaultdict(list)
                for a in fijas:
                    a_mano[(a.turno_id, a.pista_id)].append(a.jugador_id)
                for miembros in a_mano.values():
                    for i, a_id in enumerate(miembros):
                        for b_id in miembros[i + 1:]:
                            parejas_manana.add(frozenset((a_id, b_id)))
                for turno in grupo:
                    for miembros in franjas_res.get(turno.id, {}).values():
                        for i, a_id in enumerate(miembros):
                            for b_id in miembros[i + 1:]:
                                parejas_manana.add(frozenset((a_id, b_id)))
            fuera = [p.id for p in players if p.id not in colocados] + sin_franja
            # Nadie se queda sin entrenar si queda un hueco en una pista ya
            # abierta (14/10/2026): se le mete aunque rompa reglas base, y la
            # asignación queda marcada como forzada.
            if fuera:
                metidos = _rellenar_huecos(
                    semana, dia, grupo, fuera, por_id_bloque, franjas_orig, cfg,
                    vetoes_dia, vetos_coach, solo_con, es_tarde, overrides,
                    courts_by_id, report,
                )
                for jid, a in metidos.items():
                    player_sessions[jid] += 1
                    sesiones_hoy[jid] += 1
                    sesiones_bloque[(jid, bloque)] += 1
                    colocados.add(jid)
                    if a.entrenador_id:
                        coach_share[(jid, a.entrenador_id)] += 1
                fuera = [jid for jid in fuera if jid not in metidos]
            # Lo que queda, a los satélites sin entrenador (solo por la mañana).
            if (fuera and not es_tarde and satelites
                    and cfg.modo_satelites != ConfiguracionMotor.ModoSatelites.NUNCA):
                metidos = _abrir_satelites(
                    semana, dia, grupo, fuera, por_id_bloque, franjas_orig, cfg,
                    vetoes_dia, overrides, satelites, report,
                )
                for jid, a in metidos.items():
                    player_sessions[jid] += 1
                    sesiones_hoy[jid] += 1
                    sesiones_bloque[(jid, bloque)] += 1
                    colocados.add(jid)
                # El relleno pudo dejar un aviso («había sitio, pero…») a quien
                # al final ha entrado en un satélite.
                AvisoBanquillo.objects.filter(
                    semana=semana, dia=dia, bloque=bloque, jugador_id__in=list(metidos),
                    motivo__startswith="Había sitio",
                ).delete()
                fuera = [jid for jid in fuera if jid not in metidos]
            for jid in fuera:
                banquillo[jid] += 1
            if fuera:
                report["unassigned"].append(
                    {
                        "dia": dia,
                        "turno": "+".join(t.codigo for t in grupo),
                        "jugadores": fuera,
                        "status": "/".join(sorted(set(estados.values()))) or "SIN JUGADORES",
                    }
                )

    # Una pareja obligatoria puede seguir siendo imposible (uno entrena por la
    # mañana y el otro por la tarde, superficies incompatibles…). Antes se
    # quedaban los dos fuera sin explicación; ahora el informe lo dice.
    if pairs_hard:
        juntos = defaultdict(set)
        for a in Asignacion.objects.filter(semana=semana):
            juntos[(a.dia, a.turno_id, a.pista_id)].add(a.jugador_id)
        cumplidas = {frozenset((x, y)) for m in juntos.values()
                     for x in m for y in m if x != y}
        for pareja in pairs_hard - cumplidas:
            report.setdefault("parejas_imposibles", []).append(sorted(pareja))

    semana.generado_at = datetime.now(timezone.utc)
    semana.save(update_fields=["generado_at"])
    return report


def regenerate_afternoon(semana: Semana, dia: int) -> dict:
    """PRD §02: re-generate ONLY the afternoon block for one day (e.g. after a
    midday injury), leaving the morning and other days intact."""
    return generate(semana, dias=[dia], bloques=[Turno.Bloque.TARDE])
