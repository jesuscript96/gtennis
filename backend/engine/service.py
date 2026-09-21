"""Bridges the pure pairing core (`pairing.py`) with Django models: gathers the
inputs for a Semana, runs the solver per (day, block) —all the shifts of a
morning at once—, assigns coaches and persists Asignacion rows.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from django.db import transaction

from academy.models import (
    Contrato,
    Entrenador,
    Pista,
    Rencilla,
    Turno,
    VacacionesEntrenador,
)
from scheduling.models import (
    DIAS,
    ESTADOS_DEPRIORIZADOS,
    ESTADOS_EXCLUYENTES,
    Asignacion,
    ConfiguracionMotor,
    Disponibilidad,
    DisponibilidadEntrenador,
    Estado,
    Semana,
)

from .pairing import Court, PairingInput, Player, solve_pairing


def _build_courts(usar_satelites: bool = True) -> list[Court]:
    courts = []
    for pista in Pista.objects.filter(activa=True).select_related("sede"):
        if not pista.sede.activa:
            continue
        # En verano el club no desborda a los clubs satélite (#17): lo que no
        # cabe en el Resort se queda en el banquillo, no se reparte fuera.
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


def _effective_state(overrides, jugador_id, turno, fecha=None):
    """Resolución por prioridad: turno concreto > bloque (mañana/tarde) > día.

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
        return d.estado
    return Estado.DISPONIBLE


# Nivel más bajo posible de división. La división 1 es la élite, así que la
# prioridad de colocación se invierte respecto al nivel.
NIVEL_MAX = 9  # nueve niveles desde septiembre de 2026 («GRUPOS TODOS»)


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
CERRADO = {(2, "TARDE")}


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


def _jugador_motor(j, fecha, sponsors, surface_prefs, priority, solo_central):
    """El `Player` del solver para la ficha `j` ese día."""
    coach = next(iter(sponsors.get(j.id, set())), None)
    # Superficie preferida activa en la fecha (#1).
    pref = None
    for sup, desde, hasta in surface_prefs.get(j.id, ()):
        if (desde is None or fecha >= desde) and (hasta is None or fecha <= hasta):
            pref = sup
            break
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
    )


def _entra_en_franja(j, dia, turno, fecha, overrides, escuela_cfg,
                     exclusive_escuela_id, horario, hechas_dia, hechas_bloque, cfg):
    """Con qué estado entra `j` en esta franja ese día, o None si no entra."""
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
    if elegido is not None and elegido != turno.id:
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
    jugadores, franjas_de, max_franjas = [], {}, {}
    for j in Jugador.objects.filter(activo=True).select_related("division"):
        division = j.division.nivel if j.division else None
        opciones, extra_de_franja = {}, 0
        for turno in grupo:
            state = _entra_en_franja(
                j, dia, turno, fecha, overrides, escuela_cfg,
                exclusivos.get(turno.id), horario, hechas_dia, hechas_bloque, cfg,
            )
            if state is None:
                continue
            # Con prioridad alta, para que no se quede en el banquillo justo
            # el que el entrenador ha apuntado.
            opciones[turno.id] = _player_priority(
                division, state, 99 if state == Estado.EXTRA else banquillo.get(j.id, 0),
            )
            parte = overrides.get((j.id, turno.codigo))
            if parte is not None and parte.estado == Estado.EXTRA:
                extra_de_franja += 1
        if not opciones:
            continue
        _unico, solo_central = escuela_cfg.get(j.escuela_id, (None, False))
        jugadores.append(_jugador_motor(
            j, fecha, sponsors, surface_prefs, max(opciones.values()), solo_central,
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


def _emparejar_entrenadores(
    courts, sponsors, elegibles, load, pesos=None, con_quien=None,
    sesiones=None, blandos=None, info_pistas=None,
):
    """Reparte los entrenadores de un turno: uno por pista, sin repetir.

    Devuelve `({pista: entrenador}, [entrenadores repetidos])`.

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
    afin = {
        (pista, cid): _afinidad(miembros, cid, pesos, con_quien, sesiones)
        for pista, miembros in courts.items() for cid in ids_elegibles
    }

    def valor(pista, cid):
        return round(ESCALA_AFINIDAD * afin[(pista, cid)]) - load[cid]

    # Candidatos por pista: todos los disponibles, primero el del contrato duro
    # y después por afinidad.
    candidatos = {}
    for pista, miembros in courts.items():
        duros = contratados(miembros, sponsors)
        candidatos[pista] = sorted(
            ids_elegibles,
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
    modo_vecinas = bool(info_pistas) and 0 < len(ids_elegibles) < len(todas)
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
    if modo_vecinas:
        sedes = sorted(por_sede, key=lambda x: (orden_sede[x], str(x)))
        reparto = repartir_entre_sedes(
            {x: list(por_sede[x]) for x in sedes}, len(ids_elegibles), sedes,
        )
        opciones = {}
        for x in sedes:
            fijas = {n for n, p in por_sede[x].items()
                     if contratados(courts[p], sponsors) & ids_elegibles}
            opciones[x] = [
                {por_sede[x][n] for n in elegidas}
                for elegidas in opciones_de_pistas(
                    list(por_sede[x]), reparto[x], fijas=fijas,
                )
            ]
        # El reparto geométricamente mejor puede no cubrirse entero (un
        # contrato duro ata a quien ata): esa pista se queda sin entrenador y su
        # vecina, huérfana. Se prueba cada sede, en orden de llenado, con sus
        # repartos de mejor a peor, y se queda el primero que se cubre entero
        # (si ninguno, el que más cubre).
        elegido = {x: opciones[x][0] for x in sedes}
        for x in sedes:
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
        """Lo previsto que no se pudo cubrir se intenta con los que sobran."""
        if modo_vecinas and ids_elegibles - set(asig.values()):
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

    repetidos = []
    for pista in sorted(todas, key=lambda p: (len(candidatos[p]), p)):
        if not candidatos[pista] or not huerfana(pista, asignado):
            continue
        # No queda nadie libre a esta hora y ninguna vecina la cubre: se repite
        # a quien más le toca, mejor que dejarla sin nadie.
        cid = min(candidatos[pista], key=lambda c: (-afin[(pista, c)], load[c], c))
        asignado[pista] = cid
        repetidos.append(cid)
    for cid in asignado.values():
        load[cid] += 1
    return asignado, repetidos


@transaction.atomic
def generate(semana: Semana, dias=None, bloques=None) -> dict:
    """Generate (or regenerate) the cuadrante.

    dias: iterable of day indices (por defecto de lunes a viernes).

    El sábado queda fuera: en el cuadrante real tiene su propio horario —dos
    bandas de mañana, 8:30-10:00 y 10:00-11:30— que no son los turnos del
    curso, y solo se usa algunas semanas. Generarlo con M1/M2/JP/T1/T2 inventa
    sesiones que nadie da. Los modelos siguen admitiéndolo, así que basta con
    pasar `dias` para incluirlo.
    bloques: restrict to {'MANANA','TARDE'} shifts — used by the afternoon
             regeneration so the morning history stays untouched.

    Cada bloque se decide de una vez: la mañana (M1 y M2) y la tarde (T1 y
    T2) reparten a sus jugadores entre las franjas en vez de llenar la primera
    y dejar las demás vacías. El turno propio de una escuela (JP) va aparte.
    """
    dias = list(dias) if dias is not None else [d for d, _ in DIAS if d < 5]
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
    grupos = _grupos_de_turnos(turnos, turnos_exclusivos)

    cfg = ConfiguracionMotor.get_solo()
    courts = _build_courts(cfg.usar_satelites)
    courts_by_id = {c.id: c for c in courts}
    vetoes = _vetoes()
    sponsors = _sponsor_map()
    blandos = _sponsor_map("BLANDO")
    load: Counter = Counter()
    report = {"dias": {}, "overflow": [], "unassigned": []}

    # --- Entrenadores disponibles (#10/#11) y con quién entrena cada alumno --
    all_coaches = list(
        Entrenador.objects.filter(activo=True, disponible_semana=True)
    )
    pesos = pesos_de_entrenamiento()

    # Preferencias de superficie estrictas por jugador (#1).
    from academy.models import PreferenciaSuperficie

    surface_prefs: dict[int, list] = defaultdict(list)
    for ps in PreferenciaSuperficie.objects.filter(estricta=True):
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
    # Jornada semanal de cada entrenador: (entrenador, día) -> (mañana, tarde).
    from academy.models import HorarioEntrenador

    jornada = {
        (h.entrenador_id, h.dia): (h.manana, h.tarde)
        for h in HorarioEntrenador.objects.all()
    }

    for dia in dias:
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
        # Strongly penalise pairs that already hit the per-week repeat limit.
        recent = {
            pair: count * (5 if count >= cfg.max_dias_misma_pista else 1)
            for pair, count in recent.items()
        }
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

        def elegibles_para(turno):
            """Entrenadores que pueden dar clase en este turno y no están ya en
            otra pista a esa hora."""
            ini_t, fin_t = turno.horas(fecha)
            return [
                c for c in all_coaches
                if motivo_no_disponible(c, dia, turno, fecha, vac_de, jornada, coach_ovr) is None
                # No puede estar en dos pistas a la vez.
                and not any(i < fin_t and f > ini_t for i, f in ocupacion_coach[c.id])
            ]

        for grupo in grupos:
            # El club cierra algunas medias jornadas: ahí no se reparte nada y,
            # además, se limpia lo que hubiera de antes. Saltar sin borrar deja
            # en pie el cuadrante de la última generación, que es justo lo que
            # no debe verse.
            if not hay_entrenamiento(dia, grupo[0].bloque):
                Asignacion.objects.filter(
                    semana=semana, dia=dia, turno__in=grupo
                ).delete()
                continue
            n_entrenadores = {t.id: len(elegibles_para(t)) for t in grupo}
            players, franjas_de, max_franjas = _candidatos_bloque(
                semana, dia, grupo, sponsors, escuela_cfg, surface_prefs,
                turnos_exclusivos, cfg, sesiones_hoy, sesiones_bloque, horario,
                banquillo, overrides,
            )
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
            result = solve_pairing(
                PairingInput(
                    players=players,
                    courts=turno_courts,
                    vetoes=vetoes,
                    recent_partners=recent,
                    time_limit_s=cfg.time_limit_s * len(grupo),
                    w_assign=cfg.peso_asignacion,
                    w_satellite=cfg.peso_satelite,
                    w_central=cfg.peso_central,
                    w_resina=cfg.peso_resina,
                    w_repeat=cfg.peso_repeticion,
                    apply_neighbor=cfg.aplicar_vecindad,
                    neighbor_span=cfg.vecindad_max,
                    min_occupancy=1 if cfg.permitir_individuales else 2,
                    w_density=cfg.peso_densidad,
                    w_court=cfg.peso_pista_abierta,
                    pairs_hard=pairs_hard,
                    pairs_soft=pairs_soft,
                    w_pair=cfg.peso_pareja,
                    franjas=[t.id for t in grupo],
                    franjas_de=franjas_de,
                    max_franjas=max_franjas,
                    entrenadores_franja=n_entrenadores,
                    w_balance=cfg.peso_equilibrio_franjas,
                )
            )
            # Regenerar = rehacer el bloque desde cero (incluye celdas editadas
            # a mano/por swap), para no chocar con el unique al reasignar.
            Asignacion.objects.filter(
                semana=semana, dia=dia, turno__in=grupo
            ).delete()
            colocados = set()
            for turno in grupo:
                pistas = result.franjas.get(turno.id, {})
                ini_t, fin_t = turno.horas(fecha)
                # Un entrenador por pista, y a cada una quien más les toca a sus
                # alumnos según sus porcentajes y lo que llevan hecho esta semana.
                entrenador_de, repetidos = _emparejar_entrenadores(
                    pistas, sponsors, elegibles_para(turno), load,
                    pesos=pesos, con_quien=coach_share, sesiones=player_sessions,
                    blandos=blandos,
                    info_pistas={c.id: (c.venue_id, c.number, c.fill_rank)
                                 for c in turno_courts},
                )
                sin_entrenador = [p for p in pistas if p not in entrenador_de]
                if sin_entrenador:
                    report.setdefault("sin_entrenador", []).append(
                        {"dia": dia, "turno": turno.codigo, "pistas": sin_entrenador}
                    )
                for court_id, member_ids in pistas.items():
                    coach_id = entrenador_de.get(court_id)
                    for jid in member_ids:
                        Asignacion.objects.create(
                            semana=semana,
                            dia=dia,
                            turno=turno,
                            pista_id=court_id,
                            jugador_id=jid,
                            entrenador_id=coach_id,
                            estado=_effective_state(overrides, jid, turno),
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
                for cid in repetidos:
                    report.setdefault("coach_repetido", []).append(
                        {"dia": dia, "turno": turno.codigo, "entrenador": cid}
                    )
                report["dias"].setdefault(dia, {})[turno.codigo] = result.status
            fuera = [p.id for p in players if p.id not in colocados] + sin_franja
            for jid in fuera:
                banquillo[jid] += 1
            if fuera:
                report["unassigned"].append(
                    {
                        "dia": dia,
                        "turno": "+".join(t.codigo for t in grupo),
                        "jugadores": fuera,
                        "status": result.status,
                    }
                )

    semana.generado_at = datetime.now(timezone.utc)
    semana.save(update_fields=["generado_at"])
    return report


def regenerate_afternoon(semana: Semana, dia: int) -> dict:
    """PRD §02: re-generate ONLY the afternoon block for one day (e.g. after a
    midday injury), leaving the morning and other days intact."""
    return generate(semana, dias=[dia], bloques=[Turno.Bloque.TARDE])
