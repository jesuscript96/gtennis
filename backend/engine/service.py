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

from .pairing import (
    EDAD_LIBRE, NIVEL_MAX, Court, PairingInput, Player, _normalise, años_fuera_de_banda,
    emparejamiento_maximo, pueden_juntos, solve_pairing,
)


def edad_obligatoria(cfg) -> bool:
    """¿La edad es regla dura? Desde el 29/10/2026, no por defecto."""
    return bool(getattr(cfg, "edad_obligatoria", False))


def estiron_edad(cfg, es_tarde) -> int:
    """Los años que se pueden estirar las bandas de edad: si la edad no es
    regla dura, tantos que nunca bloquea; si lo es, el estirón de la tarde."""
    if not edad_obligatoria(cfg):
        return EDAD_LIBRE
    return cfg.estiron_edad if es_tarde else 0


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
    """(jugador_id, ambito) -> la falta que aplica ese día.

    Desde el 10/11/2026 hay un solo registro de faltas (`AusenciaJugador`, por
    fechas, con autor). En el parte semanal (`Disponibilidad`) solo queda
    «viene además» (EXTRA), que manda sobre una falta del mismo ámbito.

    Si varias faltas hablan del mismo jugador y ámbito, manda la más concreta:
    la de menos días (un día suelto pisa a una lesión larga) y, a igualdad, la
    última apuntada. Es lo que hacía antes el parte de la semana frente a las
    ausencias por fechas.
    """
    from scheduling.models import AusenciaJugador

    fecha = semana.fecha_inicio + timedelta(days=dia)
    out = {}
    filas = sorted(
        AusenciaJugador.objects.filter(fecha_inicio__lte=fecha, fecha_fin__gte=fecha),
        key=lambda a: (-(a.fecha_fin - a.fecha_inicio).days, a.created_at, a.id),
    )
    for a in filas:
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
# Desde el 22/10/2026 es regla dura: en la tierra del Resort solo la 2 y la 5
# se quedan sin entrenador.
VIGILADAS_ESTRICTAS = True

# Cada pista que se cubre sacando a uno del banquillo (22/10/2026). Más que
# cualquier preferencia de pista —también que dejar vigilada una de D1-D2
# (800)—, así que solo salen cuando hacen falta para colocar a alguien.
PESO_BANQUILLO = 2000

# Quien no puede ir a Satélites (invitados, escuelas solo del Resort) va por
# delante en el Resort cuando los demás sí pueden salir (23/11/2026, Yulan):
# como haberse quedado diez veces en el banquillo.
PRIORIDAD_SOLO_RESORT = 10 * (NIVEL_MAX + 1)

# Colores en el solver (22/10/2026): cada jugador con color en una pista cuyo
# entrenador es de otro color. Por debajo de abrir pista (900): no se abren
# pistas para cuadrar colores, solo se coloca a la gente para que encajen.
PESO_FUERA_COLOR = 300
# La directiva arriba: cada división por debajo de la 1 de cada jugador de su
# pista (de una pista de D2 a una de D7 son 5 por jugador: más que lo que se
# ahorra en colores), y nunca a la resina o a otra sede si otro puede ir.
PESO_DIRECTIVA_DIVISION = 150
PESO_DIRECTIVA_FUERA = 10000


def fuera_del_resort(court) -> bool:
    """Resina u otra sede: donde nunca va la directiva si otro puede ir."""
    return court.is_satellite or court.surface == "RESINA"


def debe_llevar_entrenador(court) -> bool:
    """¿Esta pista, si se abre, lleva entrenador sí o sí? La tierra del Resort
    menos la 2 y la 5. La resina y los satélites piden uno por sede, no por
    pista."""
    return (VIGILADAS_ESTRICTAS and not court.is_satellite
            and court.surface != "RESINA" and court.number is not None
            and court.number not in VIGILADAS_PREFERIDAS)

# Una pista con D1 o D2 (`nivel_protegido`) que se queda sin entrenador, vigilada
# desde la de al lado (16/10/2026). Más que saltarse el patrón 1-3-4-6 (300),
# menos que dejar a alguien sin pista (1000): nadie se queda fuera por esto.
PESO_ALTO_SIN_ENTRENADOR = 800

# Su propio entrenador de gestión, dentro de los porcentajes (en unidades de
# ESCALA_AFINIDAD). El color va en su escalón (COSTE_FUERA_DE_COLOR).
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
    for v in vacaciones.get(c.id, ()):
        if v.afecta_turno(turno, fecha):
            # El motivo que se apuntó en su calendario (vacaciones, torneo…).
            motivo = (v.motivo or "").split(" · ")[0].strip().lower()
            return f"no está: {motivo}" if motivo else "no está"
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
    # Los invitados no van nunca a Satélites (23/11/2026).
    invitados = set(Jugador.objects.filter(invitaciones__isnull=False)
                    .values_list("id", flat=True))
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
        solo_central = solo_central or j.id in invitados
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


def _dias_juntos(semana, dia, rehechos=(), hoy=None) -> dict[tuple[int, int], set[int]]:
    """(a, b) -> los OTROS días de la semana en que ya comparten pista.

    Cuentan los días anteriores y los que ya han pasado. De los que aún están
    por venir solo cuenta lo puesto a mano (26/11/2026): lo demás es
    provisional, porque cada día se rehace a las 19:00 del anterior. Antes
    contaba toda la semana y el viernes provisional de María y Silvia les
    gastó el tope del jueves. Lo que está a punto de rehacerse en esta misma
    generación tampoco cuenta. Mañana y tarde del mismo día son un solo día.
    """
    from django.utils import timezone as _tz

    hoy = hoy or _tz.localdate()
    por_venir = [d for d in range(7)
                 if d > dia and semana.fecha_inicio + timedelta(days=d) > hoy]
    por_celda = defaultdict(list)
    qs = Asignacion.objects.filter(semana=semana).exclude(dia=dia).exclude(
        dia__in=[d for d in rehechos if d > dia]).exclude(
        dia__in=por_venir, manual=False)
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
# Cubrir una pista vale más que todo lo demás: primero que no quede ninguna
# sin entrenador, y luego quién va a cada una (ver los escalones de abajo).
VALOR_CUBRIR = 10**14


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


def color_del_jugador(jid, responsable_de, color_de):
    """El color de un alumno: el del bloque de su entrenador de gestión. "" si
    no tiene (sin grupo, o de un bloque sin color)."""
    suyo = (responsable_de or {}).get(jid)
    return (color_de or {}).get(suyo, "") if suyo is not None else ""


def _fuera_de_color(miembros, cid, responsable_de, color_de):
    """Alumnos de la pista de otro color que el del entrenador. Si él no tiene
    color, o el alumno tampoco, no cuenta."""
    mio = (color_de or {}).get(cid)
    if not mio:
        return 0
    return sum(1 for jid in miembros
               if color_del_jugador(jid, responsable_de, color_de) not in ("", mio))


def _puntos_color(miembros, cid, responsable_de, color_de):
    """Lo que tira hacia este entrenador ser el de gestión de los alumnos de la
    pista (dentro de los porcentajes). El color va aparte, en su escalón."""
    if not responsable_de:
        return 0
    return sum(BONUS_SU_RESPONSABLE for jid in miembros if responsable_de.get(jid) == cid)


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


# Quién va a cada pista, por escalones (22/10/2026): cada uno pesa más que
# todo lo que viene después, y todos juntos menos que cubrir la pista.
#
# 1. La directiva (los del banquillo: Dani, Sergio, Iván, Jorge García) sale
#    solo si faltan entrenadores, y por su orden.
COSTE_BANQUILLO = 10**13
COSTE_PUESTO_BANQUILLO = 10**7
MAX_PUESTO_BANQUILLO = 8
#    Nunca a la resina ni a otra sede mientras quede otro que pueda ir.
COSTE_DIRECTIVA_FUERA = 2 * 10**13
#    Y con las divisiones más altas: cada división por debajo de la 1 cuesta,
#    y a igualdad, cada número de pista.
COSTE_ALTURA_DIRECTIVA = 10**11
COSTE_NUMERO_DIRECTIVA = 10**10
# 2. Cada entrenador con alumnos de su color (amarillo, turquesa, naranja).
COSTE_FUERA_DE_COLOR = 10**9
# 3. Dentro de su grupo de divisiones: pasarse de la tolerancia en una pista
#    que tiene que llevar entrenador (si no, ni se le pone)…
COSTE_FUERA_DE_GRUPO = 10**8
#    …y, dentro, cada división de distancia (`_penalizacion_division` con el
#    peso de Criterios del motor, multiplicado por esto).
ESCALA_GRUPO = 100
# 4. Los porcentajes (`ESCALA_AFINIDAD`) y su entrenador de gestión.
# 5. La carga de la semana y, a igualdad, la pista de número más bajo.

# Coste con el que un entrenador vetado nunca gana al hueco «sin entrenador».
# Tiene que superar a VALOR_CUBRIR: cubrir la pista vale mucho, pero romper un
# veto no compensa ni así.
VALOR_PROHIBIDO = 10 ** 16


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
    banquillo_orden=None, fuera_del_resort=frozenset(),
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

    `banquillo_orden` ({entrenador: puesto}) son los que salen del banquillo
    (la directiva) cuando faltan entrenadores para esas pistas (22/10/2026),
    por su orden, y van a las de las divisiones más altas; nunca a las
    `fuera_del_resort` (resina, otras sedes) mientras otro pueda ir: el que
    estaba arriba baja (22/10/2026). En esas pistas el grupo deja de ser límite
    y pasa a ser coste: antes un entrenador fuera de su grupo que la pista sin
    nadie. Para las pistas que se cubren de más (vigiladas que llevarían uno
    porque sobra) no sale nadie del banquillo y el grupo sigue siendo límite.

    Quién va a cada pista sigue escalones (ver COSTE_*): cubrir, directiva
    solo si falta y arriba, color, grupo, porcentajes, carga.
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

    banquillo_orden = banquillo_orden or {}
    info_pistas = info_pistas or {}
    # Desempate final: la pista de número más bajo.
    posicion = {p: n for n, p in enumerate(sorted(
        todas, key=lambda p: ((info_pistas.get(p) or (None, None, 0))[2],
                              (info_pistas.get(p) or (None, 0))[1] or 0, p)))}

    def altura(pista):
        """Lo que cuesta poner aquí a la directiva: nada en la pista de las
        divisiones más altas; más cuanto más abajo, y en la resina y otras
        sedes, solo si no hay nadie más."""
        _sede, numero, _rango = info_pistas.get(pista, (None, None, 0))
        niveles = [divisiones[j] for j in courts[pista] if divisiones.get(j)]
        coste = (COSTE_ALTURA_DIRECTIVA * (min(niveles) - 1 if niveles else NIVEL_MAX)
                 + COSTE_NUMERO_DIRECTIVA * max(0, (numero or 1) - 1))
        if pista in fuera_del_resort:
            coste += COSTE_DIRECTIVA_FUERA
        return coste

    def valor(pista, cid, estricto=True):
        coste = 0
        if cid in vetado.get(pista, ()):
            return -VALOR_PROHIBIDO
        directiva = (cid in solo_si_atado
                     and cid not in contratados(courts[pista], sponsors))
        if directiva:
            if estricto or cid not in banquillo_orden:
                return -VALOR_PROHIBIDO
            coste += (COSTE_BANQUILLO + altura(pista) + COSTE_PUESTO_BANQUILLO
                      * min(banquillo_orden[cid], MAX_PUESTO_BANQUILLO))
        else:
            if cid not in grupo_ok[pista]:
                if estricto:
                    return -VALOR_PROHIBIDO
                coste += COSTE_FUERA_DE_GRUPO
            coste += (COSTE_FUERA_DE_COLOR
                      * _fuera_de_color(courts[pista], cid, responsable_de, color_de))
            coste += ESCALA_GRUPO * _penalizacion_division(
                courts[pista], por_id[cid], divisiones, peso_division)
        return (round(ESCALA_AFINIDAD * afin[(pista, cid)])
                + ESCALA_AFINIDAD * _puntos_color(courts[pista], cid, responsable_de, color_de)
                - 10 * load[cid] - posicion[pista] - coste)

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

    def emparejar(pistas, atados_extra=None, ocupados=frozenset(), estricto=None):
        """El mejor reparto sobre `pistas`. `atados_extra` son ataduras
        forzadas {entrenador: pista}; `ocupados`, entrenadores ya colocados.
        Sin `estricto`, en las pistas que el motor manda cubrir pueden salir
        los del banquillo y un entrenador fuera de su grupo, pagando."""
        if estricto is None:
            estricto = cubrir is None
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
            [p for p in pistas if p not in tomadas], libres,
            lambda p, c: valor(p, c, estricto)))
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
            asig.update(emparejar(resto, ocupados=set(asig.values()), estricto=True))
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
                banquillo_orden.get(c, 99),
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


def _reglas_de_pista(yo, otros, span, edad=True):
    """Las reglas base que rompe `yo` metiéndose con `otros`, una vez cada
    una: «división D1–D6», «chico/chica», «edad (14 a 26 años)»."""
    from .pairing import reglas_rotas

    tipos = set()
    for o in otros:
        for r in reglas_rotas(yo, o, span, edad):
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
                       estiron_edad(cfg, es_tarde)) == DURO:
                rota = True
    if not rota:
        return ""
    con_edad = edad_obligatoria(cfg)
    reglas = _reglas_de_pista(gente[0], gente[1:], cfg.vecindad_max, con_edad)
    for k in range(1, len(gente)):
        for r in _reglas_de_pista(gente[k], gente[k + 1:], cfg.vecindad_max, con_edad):
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
                    yo, [player(a.jugador_id, a.jugador) for a in filas], cfg.vecindad_max,
                    edad_obligatoria(cfg))
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


def _altura(filas):
    """La división más alta de una pista (la 1 es la mejor); 99 sin datos."""
    niveles = [a.jugador.division.nivel for a in filas
               if a.jugador.division_id and a.jugador.division.nivel]
    return min(niveles, default=99)


def _subir_directiva(tid, nueva, directivo, yo, pistas, coach_de, by_id,
                     directiva, no_vigilan, vetos_coach, atados):
    """La pista del Resort, ya abierta en esta franja, adonde sube el de la
    directiva para que baje su entrenador a la `nueva`: la de divisiones más
    altas que lleve uno normal, no puesta a mano, sin contrato con los suyos, que el directivo
    no tenga vetado y que el de la pista nueva pueda llevar. None si ninguna
    está más arriba que la nueva (salvo que la nueva sea resina u otra sede,
    donde va otro siempre que se pueda)."""
    mia = yo.division or 99
    candidatas = []
    for (t, pid), filas in pistas.items():
        c = by_id.get(pid)
        coach = coach_de.get((t, pid))
        if (t != tid or c is None or fuera_del_resort(c) or not filas
                or coach is None or coach in directiva or coach in no_vigilan):
            continue
        # Lo puesto a mano no se toca.
        if any(a.manual for a in filas):
            continue
        if any(directivo in vetos_coach.get(a.jugador_id, ()) for a in filas):
            continue
        if any(coach in atados.get(a.jugador_id, ()) for a in filas):
            continue
        if coach in vetos_coach.get(yo.id, ()):
            continue
        candidatas.append((_altura(filas), c.number or 0, pid))
    if not candidatas:
        return None
    altura, _n, pid = min(candidatas)
    if altura >= mia and not fuera_del_resort(nueva):
        return None
    return pid


def _rescatar(semana, dia, grupo, fuera, por_id, franjas_de, cfg, vetoes,
              vetos_coach, overrides, resort, satelites, libres_de, tomar,
              nombres, no_vigilan, es_tarde, report, directiva=frozenset(),
              atados=None, coach_share=None, sede_satelites=None,
              responsable_de=None):
    """Quien sigue en el banquillo después del relleno forzado entra en una
    pista nueva: primero las que quedan libres en el Resort, que tiene
    preferencia hasta llenarse (22/10/2026), y solo después Satélites (por la
    tarde, solo si quien llama pasa `sede_satelites`; sin entrenador, nunca).

    Resort: la 2 y la 5 pueden ir vigiladas desde la de al lado; las demás y
    la resina llevan entrenador, el primero libre (los del reparto que sobren
    y después el banquillo por su orden: Dani, Sergio, Iván, Jorge García). Si
    no queda ninguno, por la mañana se abre igual, sin entrenador y con aviso.

    Satélites (23/11/2026): ya no se distingue entre clubs. Se montan tantas
    pistas como hagan falta, de tierra y, cuando la resina del Resort está
    ocupada, de resina para quien la necesita. Un entrenador por cada dos
    pistas: la primera saca entrenador, la segunda va con el mismo, la tercera
    saca otro… (sin ninguno libre, se abre igual con aviso). Los invitados no
    van nunca. `satelites` son sus pistas y `sede_satelites` la sede donde se
    montan las que falten; sin ella, no se usa.

    Se junta con alguien de su nivel si lo hay; si no, abre pista (aunque sea
    solo él) y, si ya no quedan pistas, se mete donde haya hueco rompiendo las
    reglas base. Nunca se salta una rencilla, la superficie estricta, un veto
    de entrenador ni a quien solo entrena en el Resort. Devuelve {jugador:
    asignación}.

    Si el que queda libre es de la directiva (22/10/2026), se queda arriba: va
    a la pista del Resort de divisiones más altas que lleve un entrenador
    normal, y ese baja a la pista nueva (seguro si es resina o Satélites)."""
    from academy.models import Invitado, Jugador as _J

    resort = list(resort)
    # La lista de quien llama: las pistas que se monten quedan para los días
    # siguientes de la misma generación.
    satelites = satelites if sede_satelites is not None else []
    by_id = {c.id: c for c in resort + satelites}
    sedes = dict(Sede.objects.filter(
        id__in={c.venue_id for c in by_id.values()}).values_list("id", "nombre"))
    if sede_satelites is not None:
        sedes[sede_satelites.id] = sede_satelites.nombre
    pistas = defaultdict(list)
    for a in Asignacion.objects.filter(
        semana=semana, dia=dia, turno__in=grupo,
        pista_id__in=list(by_id),
    ).select_related("jugador__division"):
        pistas[(a.turno_id, a.pista_id)].append(a)
    coach_de = {k: next((a.entrenador_id for a in filas if a.entrenador_id), None)
                for k, filas in pistas.items()}
    # En el Resort solo se usan las pistas que estaban vacías: los huecos de
    # las abiertas ya los ha mirado el relleno.
    abiertas_aqui = set()
    jugadores = {}
    tope_bloque = cfg.capacidad_tarde if es_tarde else cfg.capacidad_manana
    invitados = set(Invitado.objects.filter(jugador_creado__isnull=False)
                    .values_list("jugador_creado_id", flat=True))

    def player(jid, j=None):
        if jid not in jugadores:
            jugadores[jid] = por_id.get(jid) or _player_basico(
                j or _J.objects.select_related("division").get(pk=jid))
        return jugadores[jid]

    def en_franja(tid):
        return sum(len(f) for (t, _p), f in pistas.items() if t == tid)

    def abierta(tid, c):
        return bool(pistas.get((tid, c.id)))

    def vecinas(c):
        return [o for o in resort if o.venue_id == c.venue_id and o.number is not None
                and c.number is not None and abs(o.number - c.number) == 1]

    def puede_vigilar(tid, v, c):
        """¿La pista `v`, con entrenador, puede vigilar a `c` (vacía)?"""
        coach = coach_de.get((tid, v.id))
        if coach is None or coach in no_vigilan or len(pistas[(tid, v.id)]) > 2:
            return False
        # Cada pista con entrenador vigila a una sola.
        return not any(abierta(tid, o) and coach_de.get((tid, o.id)) is None
                       for o in vecinas(v) if o.id != c.id)

    def vigilada_posible(tid, c):
        if debe_llevar_entrenador(c):
            return False
        if c.surface == "RESINA":
            # La resina, al menos una con entrenador.
            if not any(coach_de.get((tid, o.id)) for o in resort
                       if o.venue_id == c.venue_id and o.surface == "RESINA"):
                return False
        return any(puede_vigilar(tid, v, c) for v in vecinas(c))

    def por_numero(cs):
        return sorted(cs, key=lambda c: c.number or 0)

    def resina_del_resort_ocupada(tid):
        return all(abierta(tid, c) for c in resort if c.surface == "RESINA")

    def compartible(tid, jid):
        """(entrenador, su pista) de Satélites que en esta franja lleva una sola
        pista y no atiende ya a la de al lado: la siguiente que se abra va con
        él (uno por cada dos pistas). (None, None) si no hay."""
        cuenta = Counter(coach_de.get((tid, c.id)) for c in satelites if abierta(tid, c))
        sin_nadie = {c.number for c in satelites
                     if abierta(tid, c) and coach_de.get((tid, c.id)) is None}
        for c in por_numero(satelites):
            coach = coach_de.get((tid, c.id))
            if (coach and abierta(tid, c) and cuenta[coach] == 1
                    and not (c.number is not None
                             and {c.number - 1, c.number + 1} & sin_nadie)
                    and coach not in no_vigilan
                    and coach not in vetos_coach.get(jid, ())):
                return coach, c
        return None, None

    def satelite_libre(tid, superficie, cerca=None):
        """La pista de Satélites de esa superficie vacía en la franja: la de al
        lado de `cerca` si se puede (la que atiende su entrenador), si no la
        primera. None si hay que montar otra."""
        vacias = [c for c in por_numero(satelites)
                  if c.surface == superficie and not abierta(tid, c)]
        if cerca is not None and cerca.number is not None:
            junto = [c for c in vacias if c.number in (cerca.number - 1, cerca.number + 1)]
            if junto:
                return junto[0]
        return vacias[0] if vacias else None

    def montar(superficie):
        """Una pista más en Satélites: una de esa superficie que no esté en la
        lista (apagada, p. ej.), si la hay, o una nueva con el número
        siguiente."""
        p = (Pista.objects.filter(sede=sede_satelites, superficie=superficie)
             .exclude(id__in=list(by_id)).order_by("-activa", "numero").first())
        if p is not None:
            Pista.objects.filter(pk=p.pk).update(activa=True)
        else:
            ultimo = max(Pista.objects.filter(sede=sede_satelites)
                         .values_list("numero", flat=True), default=0)
            p = Pista.objects.create(sede=sede_satelites, numero=ultimo + 1,
                                     superficie=superficie, activa=True)
        c = Court(
            id=p.id, venue_id=sede_satelites.id,
            capacity=max(sede_satelites.densidad_max or 0, sede_satelites.densidad_default),
            normal_density=sede_satelites.densidad_default, is_satellite=True,
            fill_rank=sede_satelites.orden_desbordamiento, surface=superficie,
            number=p.numero)
        satelites.append(c)
        by_id[c.id] = c
        report.setdefault("pistas_montadas", []).append(
            {"dia": dia, "pista": p.id, "numero": p.numero, "superficie": superficie})
        return c

    turnos = {t.id: t for t in grupo}
    metidos = {}
    orden = sorted(fuera, key=lambda jid: (-player(jid).priority,
                                           player(jid).division or 99))
    for jid in orden:
        yo = player(jid)
        # (clave, (pista o None para montar una, entrenador, reglas rotas,
        # entrenador compartido, superficie de la que se monta))
        opciones, impide = [], set()

        def unirse(tid, c, n, filas):
            """Meterse en una pista ya abierta por el rescate."""
            otros = [a.jugador_id for a in filas]
            if any(_normalise(jid, o) in vetoes for o in otros):
                impide.add("tiene una rencilla con quien queda en la pista libre")
                return
            coach = coach_de.get((tid, c.id))
            tope = min(c.capacity, tope_bloque)
            if coach is None:
                tope = min(tope, 2)
            if len(filas) >= tope:
                return
            if coach and coach in vetos_coach.get(jid, ()):
                impide.add("no puede entrenar con el entrenador de la pista libre")
                return
            rotas = _reglas_de_pista(
                yo, [player(a.jugador_id, a.jugador) for a in filas], cfg.vecindad_max,
                edad_obligatoria(cfg))
            opciones.append(((5 if rotas else 0, len(rotas), en_franja(tid), n, tid),
                             (c, coach, rotas, False, None)))

        libres_en = {t: libres_de(turnos[t]) for t in turnos}
        suyo = (responsable_de or {}).get(jid)
        for tid in franjas_de.get(jid, {}):
            # Entre los libres (los del reparto antes que la directiva, como
            # siempre), primero quien ya está en Satélites en otra franja del
            # bloque, luego quien puede quedarse todo el bloque y, a igualdad,
            # su entrenador (23/11/2026: el mismo en M1 y M2 prima; mejor con
            # alguien que tenga jugadores suyos).
            viajeros = {coach_de.get((t, c.id)) for t in turnos if t != tid
                        for c in satelites if abierta(t, c)}
            libres = sorted(
                (c for c in libres_en[tid] if c not in vetos_coach.get(jid, ())),
                key=lambda c: (c in directiva, c not in viajeros,
                               not all(c in libres_en[t] for t in turnos), c != suyo))
            for n, c in enumerate(por_numero(resort)):
                filas = pistas.get((tid, c.id), [])
                if filas and (tid, c.id) not in abiertas_aqui:
                    continue
                if yo.surface_pref and c.surface and c.surface != yo.surface_pref:
                    impide.add(f"solo entrena en {yo.surface_pref.lower()}")
                    continue
                if filas:
                    unirse(tid, c, n, filas)
                elif vigilada_posible(tid, c):
                    opciones.append(((1, 0, en_franja(tid), n, tid), (c, None, [], False, None)))
                elif libres:
                    opciones.append(((1, 1, en_franja(tid), n, tid),
                                     (c, libres[0], [], False, None)))
                elif not es_tarde:
                    opciones.append(((3, 0, en_franja(tid), n, tid), (c, None, [], False, None)))
            # Satélites (quien llama decide si este bloque los usa).
            if sede_satelites is None:
                continue
            if jid in invitados:
                impide.add("es invitado: no va a Satélites")
                continue
            if yo.solo_central:
                impide.add("solo entrena en el Resort")
                continue
            for c in por_numero(satelites):
                filas = pistas.get((tid, c.id), [])
                if not filas:
                    continue
                if yo.surface_pref and c.surface and c.surface != yo.surface_pref:
                    continue
                unirse(tid, c, 100 + (c.number or 0), filas)
            # Pista nueva: de tierra, y de resina solo para quien la necesita
            # y cuando la del Resort está ocupada.
            superficie = yo.surface_pref or "TIERRA"
            if superficie == "RESINA" and not resina_del_resort_ocupada(tid):
                continue
            compartido, suya = compartible(tid, jid)
            c = satelite_libre(tid, superficie, cerca=suya)
            n = 100 + (c.number if c is not None and c.number else 999)
            if compartido:
                opciones.append(((2, 0, en_franja(tid), n, tid),
                                 (c, compartido, [], True, superficie)))
            elif libres:
                opciones.append(((2, 1, en_franja(tid), n, tid),
                                 (c, libres[0], [], False, superficie)))
            elif not es_tarde:
                opciones.append(((4, 0, en_franja(tid), n, tid),
                                 (c, None, [], False, superficie)))
        if not opciones:
            # Si el relleno ya dejó su aviso («había sitio, pero…»), ese vale.
            if AvisoBanquillo.objects.filter(
                    semana=semana, dia=dia, bloque=grupo[0].bloque, jugador_id=jid).exists():
                continue
            con_satelites = sede_satelites is not None
            AvisoBanquillo.objects.create(
                semana=semana, dia=dia, bloque=grupo[0].bloque, jugador_id=jid,
                motivo=("No cabe en el Resort" + (" ni en Satélites" if con_satelites else "")
                        + (": " + "; ".join(sorted(impide)) if impide else "") + "."))
            continue
        clave, (c, coach, rotas, compartido, superficie) = min(opciones, key=lambda o: o[0])
        tid = clave[4]
        if c is None:
            c = montar(superficie)
        nueva = not pistas.get((tid, c.id))
        if nueva and compartido:
            # La segunda pista de este entrenador en Satélites: no se le vuelve
            # a sacar, ya está en esta franja.
            abiertas_aqui.add((tid, c.id))
            coach_de[(tid, c.id)] = coach
        elif nueva and coach in directiva:
            arriba = _subir_directiva(tid, c, coach, yo, pistas, coach_de, by_id,
                                      directiva, no_vigilan, vetos_coach, atados or {})
            if arriba is not None:
                bajado = coach_de[(tid, arriba)]
                tomar(coach, turnos[tid])
                coach_de[(tid, arriba)] = coach
                for a in pistas[(tid, arriba)]:
                    Asignacion.objects.filter(pk=a.pk).update(entrenador_id=coach)
                    a.entrenador_id = coach
                    if coach_share is not None:
                        coach_share[(a.jugador_id, bajado)] -= 1
                        coach_share[(a.jugador_id, coach)] += 1
                report.setdefault("directiva_arriba", []).append(
                    {"dia": dia, "turno": turnos[tid].codigo, "pista": arriba,
                     "entrenador": coach, "baja": bajado, "a": c.id})
                coach = bajado
            else:
                tomar(coach, turnos[tid])
            abiertas_aqui.add((tid, c.id))
            coach_de[(tid, c.id)] = coach
        elif nueva:
            abiertas_aqui.add((tid, c.id))
            coach_de[(tid, c.id)] = coach
            if coach is not None:
                tomar(coach, turnos[tid])
        sede = sedes.get(c.venue_id, "Satélites")
        if rotas:
            motivo, forzada = "Forzada para que entrene: " + ", ".join(rotas), True
        elif coach is None and c.is_satellite:
            motivo, forzada = f"{sede} sin entrenador, para que no se quede en el banquillo", True
        elif coach is None and not any(coach_de.get((tid, v.id)) for v in vecinas(c)):
            motivo = f"Pista {c.number} del {sede} sin entrenador, para que no se quede en el banquillo"
            forzada = True
        else:
            motivo, forzada = "", False
        a = Asignacion.objects.create(
            semana=semana, dia=dia, turno=turnos[tid], pista_id=c.id, jugador_id=jid,
            entrenador_id=coach,
            estado=_effective_state(overrides, jid, turnos[tid]),
            forzada=forzada, motivo_forzado=motivo[:200],
        )
        pistas[(tid, c.id)].append(a)
        metidos[jid] = a
        if c.is_satellite:
            report.setdefault("satelites", []).append(
                {"dia": dia, "turno": turnos[tid].codigo, "pista": c.id, "jugador": jid,
                 "sede": sede, "entrenador": coach, "reglas": rotas})
        if forzada and (rotas or not c.is_satellite):
            report.setdefault("forzadas", []).append(
                {"dia": dia, "turno": turnos[tid].codigo, "pista": c.id, "jugador": jid,
                 "reglas": rotas or ["sin entrenador"]})
    return metidos


def _trios_en_satelites(semana, dia, grupo, por_id, cfg, vetoes, vetos_coach, atados_de,
                        no_vigilan, pairs_hard, responsable_de=None, coach_share=None,
                        report=None):
    """Los tres que lleva un entrenador en Satélites (una pareja y uno solo,
    2+1) tienen que poder entrenar entre ellos (23/11/2026, como hizo Iván el
    lunes: sacó del Resort a dos D5-D6 para juntarlos con un D6 que iba solo, y
    metió en el Resort a la pareja D8-D9 que no encajaba con él).

    Si el que va solo no encaja con la pareja, por este orden:
    1. La pareja entra al Resort en la pista de una pareja que sí encaja con
       él, que sale a Satélites con su entrenador (la pista entera).
    2. Si no hay, el que va solo entra al Resort por uno que encaje con la
       pareja.
    Entre las que valen, la de jugadores del entrenador de Satélites, luego la
    de nivel más cercano y luego la pista más baja. Nunca sale del Resort quien
    no puede ir a Satélites (invitados) ni las divisiones protegidas (D1-D2), y
    no se toca nada puesto a mano, un veto, un contrato ni una pareja
    obligatoria. Con 4 en Satélites no se mira (solo con 3). Devuelve cuántos
    cambios ha hecho."""
    responsable_de = responsable_de or {}
    filas = defaultdict(list)
    sat, superficie, numero, sede = set(), {}, {}, {}
    for a in (Asignacion.objects.filter(semana=semana, dia=dia, turno__in=grupo)
              .select_related("pista__sede", "jugador__division", "turno")):
        filas[(a.turno_id, a.pista_id)].append(a)
        superficie[a.pista_id], numero[a.pista_id] = a.pista.superficie, a.pista.numero
        sede[a.pista_id] = a.pista.sede.nombre
        if a.pista.sede.es_satelite:
            sat.add(a.pista_id)
    if not sat:
        return 0
    jugadores = {}
    protegido = cfg.nivel_protegido or 0
    en_dura = defaultdict(set)
    for par in pairs_hard:
        x, y = tuple(par)
        en_dura[x].add(y)
        en_dura[y].add(x)

    def player(a):
        if a.jugador_id not in jugadores:
            jugadores[a.jugador_id] = por_id.get(a.jugador_id) or _player_basico(a.jugador)
        return jugadores[a.jugador_id]

    def coach(fs):
        return next((a.entrenador_id for a in fs if a.entrenador_id), None)

    def juntos(filas_):
        """¿Pueden entrenar todos con todos?"""
        ps = [player(a) for a in filas_]
        for i, x in enumerate(ps):
            for y in ps[i + 1:]:
                if _normalise(x.id, y.id) in vetoes or _reglas_de_pista(
                        x, [y], cfg.vecindad_max, edad_obligatoria(cfg)):
                    return False
        return True

    def sin_pareja_fuera(filas_):
        """Nadie se separa de su pareja obligatoria."""
        dentro = {a.jugador_id for a in filas_}
        return all(en_dura[a.jugador_id] <= dentro for a in filas_)

    def cabe(a, pista_id):
        pref = player(a).surface_pref
        return not pref or superficie.get(pista_id) == pref

    def puede_salir(a, a_satelites, atados):
        """¿Este del Resort puede irse a Satélites con `a_satelites`?"""
        p = player(a)
        return (not a.manual and not p.solo_central
                and not (protegido and p.division and p.division <= protegido)
                and a_satelites not in vetos_coach.get(a.jugador_id, ())
                and coach(filas[(a.turno_id, a.pista_id)]) not in atados.get(a.jugador_id, ()))

    def puede_entrar(a, pista_id, atados, de_satelites):
        """¿Este de Satélites puede entrar en la pista `pista_id` del Resort?"""
        nuevo = coach(filas[(a.turno_id, pista_id)])
        return (cabe(a, pista_id) and nuevo not in vetos_coach.get(a.jugador_id, ())
                and de_satelites not in atados.get(a.jugador_id, ()))

    def mover(a, pista_id, nuevo, turno):
        if coach_share is not None:
            if a.entrenador_id:
                coach_share[(a.jugador_id, a.entrenador_id)] -= 1
            if nuevo:
                coach_share[(a.jugador_id, nuevo)] += 1
        filas[(a.turno_id, a.pista_id)].remove(a)
        campos = {"pista_id": pista_id, "entrenador_id": nuevo}
        a_satelites = pista_id in sat
        if a_satelites:
            # Con su entrenador y con quien puede entrenar: nada que avisar.
            campos.update(forzada=False, motivo_forzado="")
            a.forzada, a.motivo_forzado = False, ""
        a.pista_id, a.entrenador_id = pista_id, nuevo
        filas[(a.turno_id, pista_id)].append(a)
        Asignacion.objects.filter(pk=a.pk).update(**campos)
        if report is None:
            return
        lista = report.setdefault("satelites", [])
        lista[:] = [r for r in lista
                    if (r["dia"], r["turno"], r["jugador"]) != (dia, turno.codigo, a.jugador_id)]
        if a_satelites:
            lista.append({"dia": dia, "turno": turno.codigo, "pista": pista_id,
                          "jugador": a.jugador_id, "sede": sede.get(pista_id, "Satélites"),
                          "entrenador": nuevo, "reglas": []})

    cambios = 0
    for t in grupo:
        atados = atados_de(t)
        unidades = defaultdict(list)
        for (tt, pid), fs in filas.items():
            if tt == t.id and fs and pid in sat and coach(fs):
                unidades[coach(fs)].append(pid)
        for de_sat, pistas_u in unidades.items():
            if len(pistas_u) != 2 or sorted(len(filas[(t.id, p)]) for p in pistas_u) != [1, 2]:
                continue
            par_pid = next(p for p in pistas_u if len(filas[(t.id, p)]) == 2)
            solo_pid = next(p for p in pistas_u if len(filas[(t.id, p)]) == 1)
            par, solo = list(filas[(t.id, par_pid)]), filas[(t.id, solo_pid)][0]
            if juntos(par + [solo]) or solo.manual or any(a.manual for a in par):
                continue
            resort = [(pid, list(fs)) for (tt, pid), fs in filas.items()
                      if tt == t.id and pid not in sat and len(fs) == 2
                      and coach(fs) not in no_vigilan]
            nivel_solo = player(solo).division or 5
            # 1) Cambiar la pareja por una pista entera del Resort.
            opciones = []
            if sin_pareja_fuera(par):
                for pid, fs in resort:
                    if (not sin_pareja_fuera(fs) or not juntos(fs + [solo])
                            or not all(puede_salir(a, de_sat, atados) and cabe(a, par_pid)
                                       for a in fs)
                            or not all(puede_entrar(a, pid, atados, de_sat) for a in par)):
                        continue
                    suyos = sum(1 for a in fs if responsable_de.get(a.jugador_id) == de_sat)
                    lejos = sum(abs((player(a).division or 5) - nivel_solo) for a in fs)
                    opciones.append((-suyos, lejos, -(numero.get(pid) or 0), pid))
            if opciones:
                pid = min(opciones)[-1]
                fuera_resort = list(filas[(t.id, pid)])
                coach_resort = coach(fuera_resort)
                for a in par:
                    mover(a, pid, coach_resort, t)
                for a in fuera_resort:
                    mover(a, par_pid, de_sat, t)
                if report is not None:
                    report.setdefault("trios_satelites", []).append(
                        {"dia": dia, "turno": t.codigo, "entra": [a.jugador_id for a in par],
                         "sale": [a.jugador_id for a in fuera_resort]})
                cambios += 1
                continue
            # 2) Cambiar al que va solo por uno del Resort que encaje con la pareja.
            if not sin_pareja_fuera([solo]):
                continue
            opciones = []
            for pid, fs in resort:
                for a in fs:
                    queda = next(b for b in fs if b is not a)
                    if (not sin_pareja_fuera([a]) or not puede_salir(a, de_sat, atados)
                            or not cabe(a, solo_pid) or not juntos(par + [a])
                            or not juntos([solo, queda])
                            or not puede_entrar(solo, pid, atados, de_sat)):
                        continue
                    suyo = 1 if responsable_de.get(a.jugador_id) == de_sat else 0
                    lejos = sum(abs((player(b).division or 5) - (player(a).division or 5))
                                for b in par)
                    opciones.append((-suyo, lejos, -(numero.get(pid) or 0), pid, a.pk))
            if opciones:
                *_x, pid, pk = min(opciones)
                a = next(b for b in filas[(t.id, pid)] if b.pk == pk)
                coach_resort = coach(filas[(t.id, pid)])
                mover(solo, pid, coach_resort, t)
                mover(a, solo_pid, de_sat, t)
                if report is not None:
                    report.setdefault("trios_satelites", []).append(
                        {"dia": dia, "turno": t.codigo, "entra": [solo.jugador_id],
                         "sale": [a.jugador_id]})
                cambios += 1
    return cambios


def _vigiladas_en_satelites(semana, dia, grupo, nivel_protegido=0, coach_share=None,
                            report=None):
    """En Satélites, de las dos pistas de un entrenador, la de al lado se queda
    sin entrenador: él la atiende desde la suya (26/11/2026, como la 2 y la 5
    del Resort). Hasta aquí el motor le pone en las dos para llevar la cuenta
    de «uno por cada dos pistas»; al final se queda en una. Se queda con él la
    de divisiones protegidas (D1-D2), luego la de más jugadores, luego la de
    nivel más alto y luego la de número más bajo. La otra no lleva aviso: está
    atendida. Lo puesto a mano no se toca. Devuelve cuántas ha dejado así."""
    filas = defaultdict(list)
    for a in (Asignacion.objects.filter(semana=semana, dia=dia, turno__in=grupo,
                                        pista__sede__es_satelite=True)
              .select_related("pista", "jugador__division")):
        filas[(a.turno_id, a.pista_id)].append(a)
    unidades = defaultdict(list)
    for (tid, pid), fs in filas.items():
        coach = next((a.entrenador_id for a in fs if a.entrenador_id), None)
        if coach:
            unidades[(tid, coach)].append(pid)

    def clave(tid, pid):
        fs = filas[(tid, pid)]
        alto = min((a.jugador.division.nivel for a in fs if a.jugador.division_id), default=99)
        protegida = bool(nivel_protegido) and alto <= nivel_protegido
        return (not protegida, -len(fs), alto, fs[0].pista.numero or 0)

    hechas = 0
    for (tid, coach), pistas in unidades.items():
        if len(pistas) != 2 or any(a.manual for p in pistas for a in filas[(tid, p)]):
            continue
        _suya, atendida = sorted(pistas, key=lambda p: clave(tid, p))
        for a in filas[(tid, atendida)]:
            if coach_share is not None and a.entrenador_id:
                coach_share[(a.jugador_id, a.entrenador_id)] -= 1
            Asignacion.objects.filter(pk=a.pk).update(entrenador_id=None)
            for r in (report or {}).get("satelites", []):
                if (r["dia"], r["jugador"], r["pista"]) == (dia, a.jugador_id, atendida):
                    r["entrenador"], r["vigilada_por"] = None, coach
        hechas += 1
    return hechas


def _mismos_en_satelites(semana, dia, grupo, libre, tomar, soltar, vetos_coach,
                         atados_de, no_vigilan, coach_share=None, report=None,
                         responsable_de=None, libres_de=None, directiva=frozenset()):
    """Quien va a Satélites se queda allí todo el bloque (23/11/2026): mejor
    que un entrenador haga M1 y M2 en Satélites que mandar a uno en M1 y a
    otro en M2. Por la tarde, primero los que ya fueron por la mañana.

    Los «viajeros», por este orden: los que fueron en otro bloque del día,
    los que están en Satélites en más franjas, los que tienen allí más
    jugadores suyos y luego por orden de franja y pista. En cada franja, el viajero que no está en Satélites ocupa el sitio
    del peor colocado (o de una pista sin entrenador): si está libre a esa
    hora, sin más; si está en una pista del Resort, se cambian y el otro sube
    a esa pista. No se toca nada puesto a mano ni se rompe un veto o un
    contrato.

    Si aun así cada franja acaba con uno distinto (no se puede mover a
    ninguno), prueba con otro entrenador que pueda ir a Satélites en todas
    (libre o cambiándose con el de su pista del Resort), nunca de la
    directiva: se hace solo si cabe en todas. Devuelve cuántos cambios ha
    hecho."""
    orden = sorted(grupo, key=lambda t: t.hora_inicio)
    filas = defaultdict(list)
    sat = set()
    for a in (Asignacion.objects.filter(semana=semana, dia=dia, turno__in=grupo)
              .select_related("pista__sede", "turno")):
        filas[(a.turno_id, a.pista_id)].append(a)
        if a.pista.sede.es_satelite:
            sat.add(a.pista_id)
    numero = {a.pista_id: a.pista.numero for fs in filas.values() for a in fs}
    if not sat:
        return 0

    def coach(fs):
        return next((a.entrenador_id for a in fs if a.entrenador_id), None)

    def unidades(tid):
        """{entrenador: [pistas]} de Satélites en la franja (None = sin él)."""
        u = defaultdict(list)
        for (t, p), fs in filas.items():
            if t == tid and fs and p in sat:
                u[coach(fs)].append(p)
        return u

    previos = list(dict.fromkeys(
        Asignacion.objects.filter(semana=semana, dia=dia, pista__sede__es_satelite=True,
                                  entrenador__isnull=False)
        .exclude(turno__in=grupo).order_by("turno__orden", "pista__numero")
        .values_list("entrenador_id", flat=True)))
    cuenta, vistos = Counter(), []
    for t in orden:
        u = unidades(t.id)
        for c in sorted((c for c in u if c), key=lambda c: min(numero[p] for p in u[c])):
            cuenta[c] += 1
            if c not in vistos:
                vistos.append(c)
    suyos = Counter((responsable_de or {}).get(a.jugador_id)
                    for (_t, p), fs in filas.items() if p in sat for a in fs)
    preferidos = previos + sorted((c for c in vistos if c not in previos),
                                  key=lambda c: (-cuenta[c], -suyos[c], vistos.index(c)))
    preferidos = [c for c in preferidos if c not in no_vigilan]
    rango = {c: i for i, c in enumerate(preferidos)}

    def poner(gente, nuevo, turno):
        for a in gente:
            viejo = a.entrenador_id
            if coach_share is not None:
                if viejo:
                    coach_share[(a.jugador_id, viejo)] -= 1
                coach_share[(a.jugador_id, nuevo)] += 1
            campos = {"entrenador_id": nuevo}
            if (a.pista_id in sat and a.forzada
                    and "sin entrenador" in (a.motivo_forzado or "")):
                campos.update(forzada=False, motivo_forzado="")
                a.forzada, a.motivo_forzado = False, ""
            a.entrenador_id = nuevo
            Asignacion.objects.filter(pk=a.pk).update(**campos)
            for r in (report or {}).get("satelites", []):
                if (r["dia"], r["turno"], r["pista"]) == (dia, turno.codigo, a.pista_id):
                    r["entrenador"] = nuevo

    cambios = 0
    for t in orden:
        atados = atados_de(t)
        for viajero in preferidos:
            u = unidades(t.id)
            if viajero in u:
                continue
            # Primero una pista sin entrenador; luego el peor colocado.
            peores = sorted((c for c in u if c is None or rango.get(c, 10 ** 6) > rango[viajero]),
                            key=lambda c: (c is not None, -rango.get(c, 10 ** 6)))
            for otro in peores:
                gente = [a for p in u[otro] for a in filas[(t.id, p)]]
                if any(a.manual for a in gente):
                    continue
                if any(viajero in vetos_coach.get(a.jugador_id, ()) for a in gente):
                    continue
                if otro is not None and any(otro in atados.get(a.jugador_id, ())
                                            for a in gente):
                    continue
                if libre(viajero, t):
                    tomar(viajero, t)
                    if otro is not None:
                        soltar(otro, t)
                    poner(gente, viajero, t)
                    cambios += 1
                    break
                if otro is None or otro in no_vigilan:
                    continue
                # El viajero está en una pista del Resort a esa hora: se cambian.
                suya = next((fs for (tt, p), fs in filas.items()
                             if tt == t.id and p not in sat and fs and coach(fs) == viajero),
                            None)
                if (suya is None or any(a.manual for a in suya)
                        or any(otro in vetos_coach.get(a.jugador_id, ()) for a in suya)
                        or any(viajero in atados.get(a.jugador_id, ()) for a in suya)):
                    continue
                poner(gente, viajero, t)
                poner(suya, otro, t)
                if report is not None:
                    report.setdefault("satelites_mismo_entrenador", []).append(
                        {"dia": dia, "turno": t.codigo, "entrenador": viajero, "sube": otro})
                cambios += 1
                break

    # Último intento: uno de fuera que pueda estar en todas las franjas.
    def huerfanos():
        """{franja: entrenadores de Satélites que no están en todas}."""
        franjas = [t for t in orden if any(c for c in unidades(t.id))]
        if len(franjas) < 2:
            return {}
        presentes = {t.id: {c for c in unidades(t.id) if c} for t in franjas}
        return {t.id: [c for c in presentes[t.id]
                       if not all(c in presentes[o.id] for o in franjas)]
                for t in franjas}

    def plan_para(x):
        """[(franja, a quién sustituye, cómo)] o None si no cabe en alguna."""
        plan = []
        for t in orden:
            sueltos = huerfanos().get(t.id)
            if sueltos is None:
                continue
            u = unidades(t.id)
            atados = atados_de(t)
            hecho = None
            for otro in sorted(sueltos, key=lambda c: rango.get(c, 10 ** 6), reverse=True):
                gente = [a for p in u[otro] for a in filas[(t.id, p)]]
                if (any(a.manual for a in gente)
                        or any(x in vetos_coach.get(a.jugador_id, ()) for a in gente)
                        or any(otro in atados.get(a.jugador_id, ()) for a in gente)):
                    continue
                if libre(x, t):
                    hecho = (t, otro, gente, None)
                    break
                if otro in no_vigilan:
                    continue
                suya = next((fs for (tt, p), fs in filas.items()
                             if tt == t.id and p not in sat and fs and coach(fs) == x), None)
                if (suya is None or any(a.manual for a in suya)
                        or any(otro in vetos_coach.get(a.jugador_id, ()) for a in suya)
                        or any(x in atados.get(a.jugador_id, ()) for a in suya)):
                    continue
                hecho = (t, otro, gente, suya)
                break
            if hecho is None:
                return None
            plan.append(hecho)
        return plan

    while any(huerfanos().values()):
        en_satelites = {c for t in orden for c in unidades(t.id) if c}
        posibles = set()
        for t in orden:
            if libres_de is not None:
                posibles |= set(libres_de(t))
            posibles |= {coach(fs) for (tt, p), fs in filas.items()
                         if tt == t.id and p not in sat and fs}
        posibles -= en_satelites | set(no_vigilan) | set(directiva) | {None}
        elegido = None
        for x in sorted(posibles, key=lambda c: (-suyos[c], c)):
            plan = plan_para(x)
            if plan:
                elegido = (x, plan)
                break
        if elegido is None:
            break
        x, plan = elegido
        for t, otro, gente, suya in plan:
            if suya is None:
                tomar(x, t)
                soltar(otro, t)
                poner(gente, x, t)
            else:
                poner(gente, x, t)
                poner(suya, otro, t)
            cambios += 1
        if report is not None:
            report.setdefault("satelites_mismo_entrenador", []).append(
                {"dia": dia, "entrenador": x, "en_lugar_de": [o for _t, o, _g, _s in plan]})
    return cambios


# Lo que vale una pareja al rehacer las parejas de una franja (27/10/2026),
# por este orden de importancia: pareja declarada (peso_pareja, 5000), ranking
# cercano, no repetir (peso_repeticion, 50 por vez) y mismo color.
#
# Ranking: cada alumno tiene un nivel fino, su división más su puesto en ella
# (el 1º de una D3 de diez es 3,05 y el último 3,95; sin ranking, 3,5). Una
# pareja vale PESO_RANKING por cada división de cercanía hasta dos: juntos
# 4000, a una división 2000, a dos 0. Una décima de división son 200, más que
# repetir pareja cuatro veces.
PESO_RANKING = 2000
# «Se empareja preferentemente hacia arriba/abajo»: con alguien de ese lado,
# esto; del lado contrario, la mitad en contra. Media división de ranking.
PESO_PREF_DIVISION = 1000
BONUS_COMPACTAR_COLOR = 30
# Edad como preferencia (29/10/2026): cada año que la pareja se pasa de su
# banda (10-14 ±2, 15-18 ±3) resta esto. Poco: un adulto con uno de 17 resta
# 100; uno de 14 con uno de 22, 600 (menos de un tercio de división de ranking).
PESO_EDAD = 100
# Desempate: a igualdad, se quedan las parejas que ya hizo el solver.
BONUS_COMPACTAR_MISMA = 10


def niveles_finos(jugadores=None) -> dict[int, float]:
    """{jugador: nivel fino} de los alumnos activos con puesto en su división:
    la división más (puesto − 0,5) / alumnos con puesto en ella. Los de una
    división sin ranking no salen: cuentan como su división y media."""
    from academy.models import Jugador

    qs = Jugador.objects.filter(activo=True, division__isnull=False,
                                orden_division__isnull=False)
    por_division = defaultdict(list)
    for jid, nivel, orden in qs.values_list("id", "division__nivel", "orden_division"):
        por_division[nivel].append((orden, jid))
    finos = {}
    for nivel, filas in por_division.items():
        filas.sort()
        for k, (_orden, jid) in enumerate(filas, start=1):
            finos[jid] = nivel + (k - 0.5) / len(filas)
    return finos


def puntos_pareja(a, b, finos, declaradas, recent, color_jugador, cfg,
                  misma_pista=False):
    """Lo que vale juntar a `a` y `b` (Player), por los escalones de arriba.
    No mira si pueden ir juntos: eso son las reglas."""
    par = frozenset((a.id, b.id))
    w = cfg.peso_pareja if par in declaradas else 0

    def fino(p):
        if p.id in finos:
            return finos[p.id]
        return p.division + 0.5 if p.division else None

    fa, fb = fino(a), fino(b)
    cercania = 1.0 if fa is None or fb is None else 2 - min(2.0, abs(fa - fb))
    w += round(PESO_RANKING * cercania)
    for yo, otro in ((a, b), (b, a)):
        if yo.division_pref and yo.division and otro.division:
            lado = (otro.division - yo.division) * yo.division_pref
            if lado > 0:
                w += PESO_PREF_DIVISION
            elif lado < 0:
                w -= PESO_PREF_DIVISION // 2
    w -= cfg.peso_repeticion * recent.get(par, 0)
    if color_jugador.get(a.id) and color_jugador.get(a.id) == color_jugador.get(b.id):
        w += BONUS_COMPACTAR_COLOR
    w -= PESO_EDAD * años_fuera_de_banda(a, b)
    if misma_pista:
        w += BONUS_COMPACTAR_MISMA
    return w


def _compactar_franja(grupos, cubiertas, vigilancia, intocables, por_id,
                      courts_by_id, reglas, con_entrenador, pairs_hard, puntos,
                      nivel_de=None):
    """Vuelve a emparejar a la gente de una franja si así salen menos pistas
    (22/10/2026) o, con las mismas, mejores parejas (27/10/2026: ranking,
    pareja declarada, no repetir, color; ver `puntos_pareja`). El solver para en cuanto lleva un rato sin mejorar y a veces
    se queda con dos individuales que podrían ir juntos, o con una pareja que,
    cambiada por otra, deja a todos de dos en dos; cada pista de más cuesta,
    con pocos entrenadores, sacar a uno de la directiva.

    Busca el emparejamiento de menos pistas entre los de la franja sin romper
    ninguna regla (rencillas, división, chico/chica, edad), sin tocar la pista
    de quien solo entra con los suyos (`intocables`), las parejas declaradas
    obligatorias ni a los alumnos sin prioridad, y recoloca los grupos en las
    mismas pistas por división (los mejores en las primeras), cerrando las que
    sobran. Las pistas conservan si llevan entrenador o van vigiladas; si se
    cierra la que vigilaba a otra, la vigila la vecina o pasa a llevar
    entrenador ella. Nunca hacen falta más entrenadores que antes.

    `grupos` es {pista: jugadores} tal y como lo dejó el solver; `cubiertas`
    las pistas con entrenador (None si no se miró); `vigilancia` {vigilada:
    pista que la vigila}; `puntos(a, b, misma_pista)` lo que vale una pareja
    y `nivel_de(jugador)` su nivel fino, para poner a los mejores en las
    primeras pistas. Devuelve (grupos, cubiertas, vigilancia, pistas cerradas)
    o None si no mejora nada."""
    fijas = set(intocables)
    en_dura = {j for par in pairs_hard for j in par}
    for cid, miembros in grupos.items():
        if any(j not in por_id or j in en_dura or por_id[j].sin_prioridad
               for j in miembros):
            fijas.add(cid)
    viejas = [cid for cid in grupos if cid not in fijas]
    movibles = [por_id[j] for cid in viejas for j in grupos[cid]]
    if len(movibles) < 2:
        return None
    pista_de = {j: cid for cid, m in grupos.items() for j in m}
    pesos = {}
    for i, a in enumerate(movibles):
        for b in movibles[i + 1:]:
            w = puntos(a, b, pista_de[a.id] == pista_de[b.id])
            if w:
                pesos[frozenset((a.id, b.id))] = w
    parejas = emparejamiento_maximo(movibles, reglas, pesos)
    if parejas is None:
        return None
    emparejados = {j for par in parejas for j in par}
    nuevos = ([sorted(par) for par in parejas]
              + [[p.id] for p in movibles if p.id not in emparejados])
    # A igual número de pistas también vale si así se deshace una pareja
    # forzada (el nuevo emparejamiento nunca rompe reglas) o si las parejas
    # puntúan más.
    forzadas = sum(
        1 for cid in viejas if len(grupos[cid]) > 1
        and not pueden_juntos(por_id[grupos[cid][0]], por_id[grupos[cid][1]], reglas))
    antes = sum(pesos.get(frozenset(grupos[cid]), 0) for cid in viejas
                if len(grupos[cid]) == 2)
    ahora = sum(pesos.get(par, 0) for par in parejas)
    if len(nuevos) > len(viejas) or (
            len(nuevos) == len(viejas) and not forzadas and ahora <= antes):
        return None

    def apta(j, cid):
        c, p = courts_by_id[cid], por_id[j]
        if p.surface_pref and c.surface and c.surface != p.surface_pref:
            return False
        return not (p.solo_central and c.is_satellite)

    def orden_pista(cid):
        c = courts_by_id[cid]
        return (c.is_satellite, c.fill_rank, c.number or 0, cid)

    libres = sorted(viejas, key=orden_pista)
    nuevas_cub = set(cubiertas) if cubiertas is not None else None
    nueva_vig = dict(vigilancia)
    asignacion = {}
    def nivel(j):
        if nivel_de is not None:
            n = nivel_de(j)
            if n is not None:
                return n
        return por_id[j].division or NIVEL_MAX + 1

    for miembros in sorted(nuevos, key=lambda m: (
            not any(j in con_entrenador for j in m), -len(m),
            min(nivel(j) for j in m))):
        necesita_cub = any(j in con_entrenador for j in miembros)
        for cid in libres:
            if cid in asignacion or not all(apta(j, cid) for j in miembros):
                continue
            if necesita_cub and nuevas_cub is not None and cid not in nuevas_cub:
                continue
            asignacion[cid] = miembros
            break
        else:
            return None
    cerradas = [cid for cid in viejas if cid not in asignacion]
    abiertas = set(asignacion) | (fijas & set(grupos))
    if nuevas_cub is not None:
        def vecinas(cid):
            c = courts_by_id[cid]
            return [o for o in abiertas if o != cid
                    and courts_by_id[o].venue_id == c.venue_id
                    and c.number is not None and courts_by_id[o].number is not None
                    and abs(courts_by_id[o].number - c.number) == 1]

        for cid in cerradas:
            if cid not in nuevas_cub:
                nueva_vig.pop(cid, None)
                continue
            nuevas_cub.discard(cid)
            for v, w in list(nueva_vig.items()):
                if w != cid:
                    continue
                del nueva_vig[v]
                otra = next((o for o in vecinas(v) if o in nuevas_cub
                             and o not in nueva_vig.values() and o not in intocables), None)
                if otra is not None:
                    nueva_vig[v] = otra
                else:
                    nuevas_cub.add(v)
        # En resina y en cada satélite, al menos una pista con entrenador.
        por_sede = defaultdict(list)
        for cid in abiertas:
            c = courts_by_id[cid]
            if c.surface == "RESINA" or c.is_satellite:
                por_sede[(c.venue_id, c.is_satellite)].append(cid)
        for cids in por_sede.values():
            if not any(cid in nuevas_cub for cid in cids):
                v = min(cids, key=orden_pista)
                nuevas_cub.add(v)
                nueva_vig.pop(v, None)
        if any(cid not in nuevas_cub and cid not in nueva_vig for cid in abiertas):
            return None
        if len(nuevas_cub) > len(cubiertas):
            return None
    grupos_nuevos = {cid: m for cid, m in grupos.items() if cid in fijas}
    grupos_nuevos.update(asignacion)
    return grupos_nuevos, nuevas_cub, nueva_vig, len(cerradas)


def _afinar_franja(grupos, intocables, por_id, courts_by_id, reglas,
                   con_entrenador, cubiertas, pairs_hard, puntos, max_vueltas=20):
    """Cambia a alumnos de pista dentro de una franja, de uno en uno, mientras
    las pistas puntúen más (27/10/2026: ranking, pareja declarada, no repetir,
    color). Es para la tarde, con pistas de tres, donde no vale emparejar de
    dos en dos. Cada pista se queda con los mismos alumnos en número, así que
    entrenadores y vigilancia no cambian; nunca junta a quien no puede ir
    junto, no toca la pista de quien solo entra con los suyos, ni las pistas
    con parejas forzadas u obligatorias, ni mueve a quien tiene contrato fuera
    de una pista con entrenador. Devuelve los grupos nuevos o None."""
    en_dura = {j for par in pairs_hard for j in par}
    from .pairing import DURO, _motivo

    def valida(miembros):
        for i, a in enumerate(miembros):
            for b in miembros[i + 1:]:
                pa, pb = por_id[a], por_id[b]
                if _normalise(a, b) in reglas.vetoes:
                    return False
                if frozenset((a, b)) in reglas.pairs_declaradas:
                    continue
                if _motivo(pa, pb, reglas.vetoes, reglas.apply_neighbor, reglas.neighbor_span,
                           reglas.span_extra, reglas.edad_extra) == DURO:
                    return False
        return True

    movibles = {cid: list(m) for cid, m in grupos.items()
                if cid not in intocables and all(
                    j in por_id and j not in en_dura and not por_id[j].sin_prioridad
                    for j in m) and valida(m)}
    if len(movibles) < 2:
        return None
    original = {j: cid for cid, m in movibles.items() for j in m}

    def valor(miembros):
        return sum(puntos(por_id[a], por_id[b], original[a] == original[b])
                   for i, a in enumerate(miembros) for b in miembros[i + 1:])

    def apta(j, cid):
        c, p = courts_by_id[cid], por_id[j]
        if p.surface_pref and c.surface and c.surface != p.surface_pref:
            return False
        if p.solo_central and c.is_satellite:
            return False
        return not (j in con_entrenador and cubiertas is not None and cid not in cubiertas)

    cambiado = False
    for _vuelta in range(max_vueltas):
        mejor = None
        pistas = sorted(movibles)
        for x, ca in enumerate(pistas):
            for cb in pistas[x + 1:]:
                ma, mb = movibles[ca], movibles[cb]
                base = valor(ma) + valor(mb)
                for a in ma:
                    for b in mb:
                        if not (apta(a, cb) and apta(b, ca)):
                            continue
                        na = [b if j == a else j for j in ma]
                        nb = [a if j == b else j for j in mb]
                        ganancia = valor(na) + valor(nb) - base
                        if ganancia > 0 and (mejor is None or ganancia > mejor[0]) \
                                and valida(na) and valida(nb):
                            mejor = (ganancia, ca, cb, na, nb)
        if mejor is None:
            break
        _g, ca, cb, na, nb = mejor
        movibles[ca], movibles[cb] = na, nb
        cambiado = True
    if not cambiado:
        return None
    nuevos = dict(grupos)
    nuevos.update(movibles)
    return nuevos


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


def quien_viene(semana, dia):
    """Quién debería entrenar ese día, para el banquillo del cuadrante
    (19/11/2026): {jugador_id: (estado, falta)}.

    Es la misma regla con la que el motor decide a quién coloca
    (`_entra_en_franja`): de alta ese día, con el día en su horario habitual
    —o en una visita aprobada, si es invitado— o apuntado como «viene
    además», y en una franja que el club abra ese día. `falta` es True cuando
    le tocaba pero no viene a ninguna de sus franjas por una falta (ausencia,
    torneo, climatología…); `estado` dice cuál.

    Quien no sale aquí no viene ese día: invitados de otros días, altas que
    aún no han empezado, bajas pasadas o un día que no le toca entrenar. Antes
    el banquillo los enseñaba a todos.
    """
    from academy.models import Escuela, HorarioJugador, Jugador

    fecha = semana.fecha_inicio + timedelta(days=dia)
    turnos = sorted(
        (t for t in Turno.objects.filter(activo=True)
         if hay_entrenamiento(dia, t.bloque) and (dia, t.codigo) not in FRANJA_CERRADA),
        key=lambda t: t.hora_inicio,
    )
    if not turnos:
        return {}
    escuela_cfg = {e.id: (e.turno_unico_id, e.solo_central) for e in Escuela.objects.all()}
    # Como en `generate`: la franja exclusiva de una escuela, salvo por la tarde.
    de_tarde = set(Turno.objects.filter(bloque=Turno.Bloque.TARDE).values_list("id", flat=True))
    exclusivos = {}
    for escuela_id, (turno_unico_id, _solo_central) in escuela_cfg.items():
        if turno_unico_id and turno_unico_id not in exclusivos and turno_unico_id not in de_tarde:
            exclusivos[turno_unico_id] = escuela_id
    tarde = [t for t in turnos if t.bloque == Turno.Bloque.TARDE]
    desborde = {t.id: {d.id for d in tarde[i + 1:]} for i, t in enumerate(tarde)}
    horario = _horario_del_dia(
        {(h.jugador_id, h.dia): (h.turno_manana_id, h.turno_tarde_id,
                                 h.entrena_manana, h.entrena_tarde)
         for h in HorarioJugador.objects.filter(dia=dia)},
        _dias_de_invitados(), fecha, dia,
        dict(Turno.objects.values_list("codigo", "id")),
    )
    overrides = _overrides(semana, dia)
    cfg = ConfiguracionMotor.get_solo()

    def entra(j, t, faltas):
        return _entra_en_franja(j, dia, t, fecha, faltas, escuela_cfg,
                                exclusivos.get(t.id), horario, {}, {}, cfg, desborde)

    out = {}
    for j in Jugador.objects.filter(activo=True):
        viene = falta = None
        for t in turnos:
            estado = entra(j, t, overrides)
            if estado is not None:
                viene = viene or estado
            elif falta is None and entra(j, t, {}) is not None:
                # Le tocaba esta franja y no entra: es por una falta.
                falta = _effective_state(overrides, j.id, t, fecha)
        if viene is not None:
            out[j.id] = (viene, False)
        elif falta is not None:
            out[j.id] = (falta, True)
    return out


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
        # La 1, 3, 4 y 6 del Resort no se quedan sin entrenador en el
        # cuadrante: el que vigila la 2 figura en la 1 (22/10/2026).
        if debe_llevar_entrenador(courts_by_id[suya]):
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
    # Tope de toda la generación (21/10/2026): una semana tarda en torno a dos
    # minutos; si alguna se complica, al pasar de MOTOR_TOPE_GENERACION_S (3
    # minutos desde el 22/10) lo que falte se resuelve con 1 s por llamada, sin
    # dejar días a medias.
    fin_generacion = time.monotonic() + float(
        os.environ.get("MOTOR_TOPE_GENERACION_S", "180"))
    # El reparto es solo del Resort. Satélites se abre después, con las
    # pistas que hagan falta, para quien se quedaría en el banquillo
    # (23/11/2026: ya no entran nunca en el reparto).
    todas = _build_courts()
    courts = [c for c in todas if not c.is_satellite]
    sede_satelites = (
        Sede.objects.filter(es_satelite=True, activa=True)
        .order_by("orden_desbordamiento", "id").first()
        if cfg.modo_satelites != ConfiguracionMotor.ModoSatelites.NUNCA else None)
    # Las pistas de Satélites; el rescate añade aquí las que monte.
    satelites = [c for c in todas if sede_satelites is not None
                 and c.venue_id == sede_satelites.id]

    def satelites_en(tarde):
        """¿Hay Satélites en este bloque? Por la mañana, salvo «nunca»; por la
        tarde, solo en el modo «también por la tarde»."""
        return sede_satelites is not None and (
            not tarde or cfg.modo_satelites == ConfiguracionMotor.ModoSatelites.SIEMPRE)
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
    nombres_coach = {c.id: c.nombre for c in all_coaches}
    # Los que salen del banquillo cuando faltan entrenadores, por su orden
    # (22/10/2026): Dani Gimeno, Sergio Gallego, Iván Gallego, Jorge García.
    banquillo_orden = {c.id: c.orden_banquillo for c in all_coaches
                       if c.orden_banquillo is not None}
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
    # El tipo de pista de un día de invitado va delante de todo: es solo ese
    # día y lo ha pedido quien le invita (27/10/2026).
    from academy.models import VisitaInvitado

    for jid, fecha, sup in VisitaInvitado.objects.filter(
        estado=VisitaInvitado.Estado.APROBADA,
        invitado__jugador_creado__isnull=False,
    ).exclude(superficie="").values_list(
        "invitado__jugador_creado_id", "fecha", "superficie"
    ):
        surface_prefs[jid].insert(0, (sup, fecha, fecha))

    # Parejas preferidas (#5): HARD misma pista, SOFT bonus.
    from academy.models import PreferenciaPareja

    pairs_hard: set = set()
    pairs_soft: set = set()
    # «Pueden repetir más días» (26/11/2026, María y Silvia): ni obliga ni
    # empuja a juntarlos; solo les quita el tope de días juntos a la semana y
    # el castigo por repetir pareja.
    sin_tope: set = set()
    for pp in PreferenciaPareja.objects.filter(activa=True):
        key = frozenset((pp.jugador_id, pp.jugador_objetivo_id))
        if pp.tipo == PreferenciaPareja.Tipo.SIN_TOPE:
            sin_tope.add(key)
        else:
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
    # Ranking dentro de cada división (27/10/2026).
    finos = niveles_finos()
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
        recent = {k: v for k, v in _recent_partners(semana, dia).items()
                  if k not in sin_tope}
        horario_hoy = _horario_del_dia(
            horario, invitados, semana.fecha_inicio + timedelta(days=dia), dia,
            turno_por_codigo)
        # Tope duro de días juntos a la semana (3 en el club): la pareja que ya
        # lo ha alcanzado no comparte pista hoy, tampoco si está declarada. Se
        # trata como una rencilla solo para este día.
        topados = {
            par for par, dias_par in _dias_juntos(semana, dia, dias).items()
            if cfg.max_dias_misma_pista and len(dias_par) >= cfg.max_dias_misma_pista
            and frozenset(par) not in sin_tope
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
        # «Disp. entrenadores» ya no existe (10/11/2026): todo lo que un
        # entrenador no puede está en su calendario (`vac_de`).
        coach_ovr = {}

        def elegibles_para(turno, presentes=frozenset(), todos=False):
            """Entrenadores que pueden dar clase en este turno y no están ya en
            otra pista a esa hora. Quien solo entra con unos jugadores, solo si
            alguno está entre los `presentes` (o con `todos`)."""
            ini_t, fin_t = turno.horas(fecha)
            return [
                c for c in all_coaches
                if motivo_no_disponible(c, dia, turno, fecha, vac_de, jornada, coach_ovr) is None
                # No puede estar en dos pistas a la vez.
                and not any(i < fin_t and f > ini_t for i, f in ocupacion_coach[c.id])
                and (todos or not (solo_con.get(c.id)
                                   and not solo_con[c.id] & set(presentes)))
            ]

        def reservas_de(turno):
            """Los del banquillo libres en este turno, por su orden. Dani
            cuenta aunque no venga ninguno de los suyos."""
            return sorted(
                (c for c in elegibles_para(turno, todos=True)
                 if c.id in banquillo_orden),
                key=lambda c: (banquillo_orden[c.id], c.id))

        def para_reparto(turno, presentes):
            """Los que el reparto de entrenadores puede usar: los elegibles y,
            si faltan, los del banquillo."""
            vistos = {c.id: c for c in elegibles_para(turno, presentes)}
            for c in reservas_de(turno):
                vistos.setdefault(c.id, c)
            return list(vistos.values())

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
            # Si alguien tiene que salir del Resort, que sea quien puede entrenar
            # en Satélites (23/11/2026: Yulan, invitada, se quedó fuera con su
            # pareja obligatoria; a Satélites no podía ir). Su pareja obligatoria
            # entra con él por la regla de las parejas.
            if satelites_en(es_tarde):
                for p in players:
                    if p.solo_central:
                        franjas_de[p.id] = {f: pr + PRIORIDAD_SOLO_RESORT
                                            for f, pr in franjas_de[p.id].items()}
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
                # Por la tarde, mientras quede una franja después (T2), no
                # se saca a nadie del banquillo: antes T2 con los del reparto.
                ultima = fase[-1] == orden[-1]
                banquillo_fase = {t.id: len(reservas_de(t)) if ultima else 0
                                  for t in fase}
                regla = any(reparto.values()) or any(banquillo_fase.values())
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
                    max_pistas=({t.id: len(para_reparto(t, presentes_en(t, jugadores)))
                                 for t in fase} if es_tarde else {}),
                    pistas_objetivo={} if es_tarde else n_entrenadores,
                    w_exceso_pistas=0 if es_tarde else cfg.peso_exceso_pistas,
                    w_individual=cfg.peso_individual,
                    # El estirón (una división o un año de más) solo por la
                    # tarde, cuando falta gente: por la mañana ±1 estricto.
                    span_extra=cfg.estiron_division if es_tarde else 0,
                    edad_extra=estiron_edad(cfg, es_tarde),
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
                    vigiladas_estrictas=VIGILADAS_ESTRICTAS,
                    w_vigilada_fuera=0 if VIGILADAS_ESTRICTAS else PESO_VIGILADA_FUERA,
                    resina_con_entrenador=True,
                    satelite_con_entrenador=True,
                    banquillo=banquillo_fase,
                    banquillo_dedicados=set(solo_con) & set(banquillo_orden),
                    w_banquillo=PESO_BANQUILLO,
                    clases_entrenador={
                        t.id: dict(Counter(color_de.get(cid, "") for cid in reparto[t.id]
                                           if cid not in solo_con))
                        for t in fase},
                    color_jugador={p.id: color_del_jugador(p.id, responsable_de, color_de)
                                   for p in jugadores},
                    w_fuera_color=PESO_FUERA_COLOR,
                    w_directiva_division=PESO_DIRECTIVA_DIVISION,
                    w_directiva_fuera=PESO_DIRECTIVA_FUERA,
                    prioridad_cubrir={
                        p.id for p in jugadores
                        if cfg.nivel_protegido and p.division is not None
                        and p.division <= cfg.nivel_protegido},
                    w_cubrir_prioridad=PESO_ALTO_SIN_ENTRENADOR,
                    forzar=forzar,
                    paciencia=ultima and not forzar,
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
                # Por la tarde no se fuerza en T1 a quien aún cabe en T2.
                despues = {t.id for t in orden if t.hora_inicio > fase[-1].hora_inicio}
                if any(p.id not in colocados_en(r) and not despues & set(franjas_de[p.id])
                       for p in jugadores):
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
            # Repaso de las parejas de cada franja (22 y 27/10/2026). Por la
            # mañana (pistas de dos), el emparejamiento de menos pistas y, con
            # las mismas, el que más puntúa (ranking, pareja declarada, no
            # repetir, color). Por la tarde (tríos), cambios de uno en uno.
            reglas = PairingInput(
                players=[], courts=[], vetoes=vetoes_dia,
                pairs_declaradas=pairs_declaradas_dia,
                apply_neighbor=cfg.aplicar_vecindad, neighbor_span=cfg.vecindad_max,
                span_extra=cfg.estiron_division if es_tarde else 0,
                edad_extra=estiron_edad(cfg, es_tarde))
            colores_bloque = {pid: color_del_jugador(pid, responsable_de, color_de)
                              for pid in por_id_bloque}
            declaradas_bloque = pairs_soft_dia | pairs_declaradas_dia | (
                parejas_manana if es_tarde else set())

            def puntos(a, b, misma=False):
                return puntos_pareja(a, b, finos, declaradas_bloque, recent,
                                     colores_bloque, cfg, misma)

            def nivel_de(jid):
                p = por_id_bloque.get(jid)
                if jid in finos:
                    return finos[jid]
                return p.division + 0.5 if p and p.division else None

            for t in grupo:
                if not franjas_res.get(t.id):
                    continue
                atados_t = {
                    jid for jid, cids in atados_de(t).items()
                    if jid in franjas_de and cids & del_reparto(t, presentes_en(t, players))}
                intocables = set(dedicadas_res.get(t.id, {}).values())
                if not es_tarde:
                    res = _compactar_franja(
                        franjas_res[t.id], cubiertas_res.get(t.id),
                        vigilancia_res.get(t.id, {}), intocables, por_id_bloque,
                        courts_by_id, reglas, atados_t, pairs_hard_dia, puntos, nivel_de)
                    if res:
                        franjas_res[t.id], cubiertas_res[t.id], vigilancia_res[t.id], n = res
                        report.setdefault("compactadas", []).append(
                            {"dia": dia, "turno": t.codigo, "pistas_cerradas": n})
                else:
                    res = _afinar_franja(
                        franjas_res[t.id], intocables, por_id_bloque, courts_by_id,
                        reglas, atados_t, cubiertas_res.get(t.id), pairs_hard_dia, puntos)
                    if res:
                        franjas_res[t.id] = res
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
                    pistas, atados, para_reparto(turno, en_turno), load,
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
                    sin_rescate=set(solo_con) - set(banquillo_orden),
                    responsable_de=responsable_de, color_de=color_de,
                    banquillo_orden=banquillo_orden,
                    fuera_del_resort={c.id for c in turno_courts if fuera_del_resort(c)},
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
            # Lo que queda abre pista: primero lo libre del Resort y luego
            # Satélites, con entrenador si queda alguno.
            if fuera:
                usar_sat = satelites_en(es_tarde)

                def libres_rescate(turno):
                    del_rep = [c.id for c in elegibles_para(turno)
                               if c.id not in de_banquillo and c.id not in solo_con]
                    return del_rep + [c.id for c in reservas_de(turno)
                                      if c.id not in del_rep]

                def tomar(cid, turno):
                    ocupacion_coach[cid].append(turno.horas(fecha))
                    load[cid] += 1

                def soltar(cid, turno):
                    if turno.horas(fecha) in ocupacion_coach[cid]:
                        ocupacion_coach[cid].remove(turno.horas(fecha))
                    load[cid] -= 1

                metidos = _rescatar(
                    semana, dia, grupo, fuera, por_id_bloque, franjas_orig, cfg,
                    vetoes_dia, vetos_coach, overrides,
                    [c for c in turno_courts if not c.is_satellite],
                    satelites if usar_sat else [], libres_rescate, tomar,
                    nombres_coach, set(solo_con), es_tarde, report,
                    directiva=set(banquillo_orden), atados=sponsors,
                    coach_share=coach_share,
                    sede_satelites=sede_satelites if usar_sat else None,
                    responsable_de=responsable_de,
                )
                for c in satelites:
                    courts_by_id.setdefault(c.id, c)
                if usar_sat:
                    _trios_en_satelites(
                        semana, dia, grupo, por_id_bloque, cfg, vetoes_dia,
                        vetos_coach, atados_de, set(solo_con), pairs_hard_dia,
                        responsable_de=responsable_de, coach_share=coach_share,
                        report=report,
                    )
                    _mismos_en_satelites(
                        semana, dia, grupo,
                        libre=lambda cid, t: cid in libres_rescate(t),
                        tomar=tomar, soltar=soltar, vetos_coach=vetos_coach,
                        atados_de=atados_de, no_vigilan=set(solo_con),
                        coach_share=coach_share, report=report,
                        responsable_de=responsable_de, libres_de=libres_rescate,
                        directiva=set(banquillo_orden),
                    )
                    _vigiladas_en_satelites(
                        semana, dia, grupo, cfg.nivel_protegido,
                        coach_share=coach_share, report=report,
                    )
                for jid, a in metidos.items():
                    player_sessions[jid] += 1
                    sesiones_hoy[jid] += 1
                    sesiones_bloque[(jid, bloque)] += 1
                    colocados.add(jid)
                    if a.entrenador_id:
                        coach_share[(jid, a.entrenador_id)] += 1
                # El relleno pudo dejar un aviso («había sitio, pero…») a quien
                # al final ha entrado en Satélites.
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
