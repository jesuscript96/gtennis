"""Bridges the pure pairing core (`pairing.py`) with Django models: gathers the
inputs for a Semana, runs the solver per (day, shift), assigns coaches and
persists Asignacion rows.
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


def _player_priority(division, state, deficit=0):
    """Prioridad de colocación en el turno, en dos niveles.

    Manda el DÉFICIT de cupo semanal: mientras a alguien le falten sesiones,
    va por delante de cualquiera que ya tenga las suyas, sea del nivel que
    sea. Es lo que hace Iván — todo el mundo entrena lo suyo antes de que
    nadie repita. A igualdad de déficit desempata el nivel, donde la división
    1 es la élite (nivel 1 → 8, nivel 8 → 1).

    Molestias/torneo bajan la prioridad: llenan hueco solo tras los
    plenamente disponibles.
    """
    nivel = (NIVEL_MAX + 1 - division) if division else 4
    if state in ESTADOS_DEPRIORIZADOS:
        nivel = max(1, nivel // 2)
    # El déficit escala por encima del rango de niveles para que domine.
    return max(0, deficit) * (NIVEL_MAX + 1) + nivel


# Medias jornadas en las que el club no entrena. Los miércoles por la tarde no
# hay pista: ni jugadores ni entrenadores se pueden colocar ahí, ni el motor ni
# a mano. (día de la semana con lunes=0, bloque)
CERRADO = {(2, "TARDE")}


def hay_entrenamiento(dia, bloque):
    """¿Se entrena ese día en ese bloque? El miércoles por la tarde, no."""
    return (dia, bloque) not in CERRADO


def cupo_por_horario(horario, dias):
    """Sesiones de la semana que salen del horario declarado, por jugador.

    Solo cuenta a quien tiene fila para TODOS los días: eso es declarar la
    semana. Una fila suelta es una excepción («el martes por la tarde no») y no
    dice nada de cuántas sesiones hace; si contara, esa única fila le dejaría
    el cupo en una sesión a la semana. La tarde de un día cerrado no suma.
    """
    filas = defaultdict(dict)
    for (jid, d), fila in horario.items():
        filas[jid][d] = fila
    cupo = Counter()
    for jid, por_dia in filas.items():
        if not set(dias) <= set(por_dia):
            continue
        for d in dias:
            _m, _t, entrena_m, entrena_t = por_dia[d]
            cupo[jid] += bool(entrena_m) + (
                bool(entrena_t) and hay_entrenamiento(d, "TARDE")
            )
    return cupo


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


def _available_players(
    semana, dia, turno, sponsors, escuela_cfg=None, surface_prefs=None,
    exclusive_escuela_id=None, cfg=None, hechas_dia=None, hechas_semana=None,
    idx_dia=0, n_dias=5, hechas_bloque=None, dias_presente=None, orden_dia=None,
    horario=None, cupo_horario=None,
) -> list[Player]:
    from academy.models import Jugador

    escuela_cfg = escuela_cfg or {}
    surface_prefs = surface_prefs or {}
    hechas_dia = hechas_dia or {}
    hechas_semana = hechas_semana or {}
    hechas_bloque = hechas_bloque or {}
    dias_presente = dias_presente or {}
    orden_dia = orden_dia or {}
    horario = horario or {}
    cupo_horario = cupo_horario or {}
    tope_bloque = cfg.sesiones_bloque_max if cfg else 1
    tope_dia_def = cfg.sesiones_dia_max_default if cfg else 2
    cupo_sem_def = cfg.sesiones_semana_default if cfg else 4
    fecha = semana.fecha_inicio + timedelta(days=dia)
    overrides = _overrides(semana, dia)
    players = []

    def _nuevo(j, state, deficit, solo_central):
        division = j.division.nivel if j.division else None
        coach = next(iter(sponsors.get(j.id, set())), None)
        # Superficie preferida activa en la fecha (#1).
        pref = None
        for sup, desde, hasta in surface_prefs.get(j.id, ()):
            if (desde is None or fecha >= desde) and (hasta is None or fecha <= hasta):
                pref = sup
                break
        return Player(
            division_pref={"ARRIBA": -1, "ABAJO": 1}.get(j.pareja_division, 0),
            id=j.id,
            division=division,
            sponsor_coach_id=coach,
            priority=_player_priority(division, state, deficit),
            surface_pref=pref,
            solo_central=solo_central,
        )

    qs = Jugador.objects.filter(activo=True).select_related("division")
    for j in qs:
        # Alta a mitad de mes: hasta el día que empieza, el alumno no entra en
        # ningún entrenamiento aunque su ficha ya exista (y lo mismo al revés
        # con la fecha de baja).
        if not j.en_alta(fecha):
            continue
        # #6: los jugadores de una escuela con turno único (p. ej. Junior
        # Program → JP) solo entran en ese turno; en el resto se excluyen.
        turno_unico, solo_central = escuela_cfg.get(j.escuela_id, (None, False))
        if turno_unico is not None and turno_unico != turno.id:
            continue
        # Regla inversa: si ESTE turno es exclusivo de una escuela (alguien lo
        # tiene como turno_unico), solo pueden entrar jugadores de esa escuela.
        # Evita que Alto Rendimiento caiga en el turno JP.
        if exclusive_escuela_id is not None and j.escuela_id != exclusive_escuela_id:
            continue
        state = _effective_state(overrides, j.id, turno, fecha)
        if state in ESTADOS_EXCLUYENTES:
            continue
        # Excepción del entrenador: ese día y en esa franja viene sí o sí, diga
        # lo que diga su horario, su cupo o sus topes. Solo se respeta lo que no
        # depende de él: el alta, la escuela y que el club abra. Con prioridad
        # alta, para que no se quede en el banquillo justo el que se ha apuntado.
        if state == Estado.EXTRA:
            players.append(_nuevo(j, state, 99, solo_central))
            continue
        # Franja del jugador para este bloque. Manda el horario del día si lo
        # tiene (puede entrar a primera hora los lunes y a segunda los
        # miércoles); si no, el turno fijo de su ficha; y si tampoco, el motor
        # elige. En la fila de un día cada bloque tiene tres respuestas: no
        # entrena, entrena en la franja que salga (turno vacío) o entrena en
        # esa franja. Antes el turno vacío valía por «no entrena», y decir que
        # un martes por la tarde no venía le sacaba también de las mañanas.
        fila = horario.get((j.id, dia))
        if fila is not None:
            man, tar, entrena_m, entrena_t = fila
            es_manana = turno.bloque == "MANANA"
            if not (entrena_m if es_manana else entrena_t):
                continue
            elegido = man if es_manana else tar
            if elegido is not None and elegido != turno.id:
                continue
        else:
            elegido = (j.turno_manana_id if turno.bloque == "MANANA"
                       else j.turno_tarde_id)
            if elegido is not None and elegido != turno.id:
                continue
        # Tope de sesiones el mismo día (#18): quien ya ha cubierto su dosis
        # de hoy no entra en los turnos que quedan.
        tope_dia = j.sesiones_dia_max if j.sesiones_dia_max is not None else tope_dia_def
        if hechas_dia.get(j.id, 0) >= tope_dia:
            continue
        # Y como mucho una por bloque: quien ya ha entrenado por la mañana
        # repite por la tarde, no a la hora siguiente. Es lo que hace la
        # academia — de 249 dobles sesiones en agosto, 248 son mañana+tarde.
        if hechas_bloque.get((j.id, turno.bloque), 0) >= tope_bloque:
            continue
        cupo = (cupo_horario.get(j.id)
                or j.sesiones_semana
                or cupo_sem_def)
        hechas = hechas_semana.get(j.id, 0)
        # Quien ya lleva su dosis semanal no entra en el sorteo: es lo que deja
        # pistas a 2 y con hueco, en vez de apretar a 4 para colocar a todos.
        if hechas >= cupo:
            continue
        # Ritmo semanal. A día `i` de `n`, a este jugador le tocan como mucho
        # la parte proporcional de su cupo. El solver va turno a turno y llena
        # con avidez, así que sin este freno la cuota entera se gasta lunes y
        # martes y el viernes queda vacío.
        #
        # La `fase` (estable, derivada del id) desplaza el escalón de cada
        # jugador: sin ella todos suben de cupo el mismo día y se alternan
        # jornadas llenas con jornadas muertas. Con ella, cada día entra un
        # subconjunto distinto — que es justo lo que hace Iván, donde no viene
        # todo el mundo todos los días. Es un reparto, NO el horario real de
        # cada alumno: eso son las Disponibilidades, hoy sin cargar.
        # El ritmo se mide sobre los días en que ESTE jugador está, no sobre
        # los de la semana: quien solo viene tres días y tiene cupo 6 hace dos
        # sesiones cada uno de esos tres, no una diaria de lunes a viernes.
        mis_dias = dias_presente.get(j.id, n_dias) or n_dias
        mi_idx = orden_dia.get(j.id, idx_dia)
        fase = j.id % max(1, mis_dias)
        permitidas_hoy = (cupo * (mi_idx + 1) + fase) // max(1, mis_dias)
        if hechas >= permitidas_hoy:
            continue
        deficit = permitidas_hoy - hechas
        players.append(_nuevo(j, state, deficit, solo_central))
    players.sort(key=lambda p: p.priority, reverse=True)
    return players


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

    cfg = ConfiguracionMotor.get_solo()
    courts = _build_courts(cfg.usar_satelites)
    courts_by_id = {c.id: c for c in courts}
    vetoes = _vetoes()
    sponsors = _sponsor_map()
    blandos = _sponsor_map("BLANDO")
    load: Counter = Counter()
    report = {"dias": {}, "overflow": [], "unassigned": []}

    # --- Entrenadores disponibles (#10/#11) y con quién entrena cada alumno --
    from academy.models import Jugador

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

    # Días de la semana en que cada jugador NO está excluido por una ausencia
    # declarada. Es lo que permite repartirle su cupo solo entre los días que
    # de verdad viene.
    from academy.models import Jugador as _J

    todos_ids = list(_J.objects.filter(activo=True).values_list("id", flat=True))

    # Horario semanal de cada jugador: (jugador, día) -> (turno mañana, tarde).
    from academy.models import HorarioJugador

    horario = {
        (h.jugador_id, h.dia): (h.turno_manana_id, h.turno_tarde_id,
                                h.entrena_manana, h.entrena_tarde)
        for h in HorarioJugador.objects.all()
    }
    # Quien tiene horario declarado ya está diciendo cuántas sesiones hace:
    # su cupo semanal es el número de franjas que ha marcado, no el valor por
    # defecto del club. Sin esto el cupo genérico le cortaba antes de llegar a
    # las tardes y el horario quedaba a medio cumplir.
    # Jornada semanal de cada entrenador: (entrenador, día) -> (mañana, tarde).
    from academy.models import HorarioEntrenador

    jornada = {
        (h.entrenador_id, h.dia): (h.manana, h.tarde)
        for h in HorarioEntrenador.objects.all()
    }
    cupo_horario = cupo_por_horario(horario, dias)
    dias_presente: Counter = Counter()
    dias_del_jugador: dict[int, list[int]] = defaultdict(list)
    for d in dias:
        ovr_d = _overrides(semana, d)
        for jid in todos_ids:
            fuera = any(
                ovr_d.get((jid, key)) is not None
                and ovr_d[(jid, key)].estado in ESTADOS_EXCLUYENTES
                for key in ("DIA", "MANANA", "TARDE")
            )
            if not fuera:
                dias_presente[jid] += 1
                dias_del_jugador[jid].append(d)
    orden_por_dia = {
        d: {jid: ds.index(d) for jid, ds in dias_del_jugador.items() if d in ds}
        for d in dias
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
        for turno in turnos:
            # El club cierra algunas medias jornadas: ahí no se reparte nada y,
            # además, se limpia lo que hubiera de antes. Saltar sin borrar deja
            # en pie el cuadrante de la última generación, que es justo lo que
            # no debe verse.
            if not hay_entrenamiento(dia, turno.bloque):
                Asignacion.objects.filter(
                    semana=semana, dia=dia, turno=turno
                ).delete()
                continue
            # Entrenadores elegibles para este turno: no de vacaciones y cuya
            # ventana horaria cubre el turno (según horario de temporada).
            ini_t, fin_t = turno.horas(fecha)
            elegibles = []
            for c in all_coaches:
                if any(v.afecta_turno(turno) for v in vac_de.get(c.id, ())):
                    continue
                # Jornada estable: quien no trabaja ese bloque ese día no
                # entra. Sin fila se entiende jornada completa.
                jor = jornada.get((c.id, dia))
                if jor is not None and not (
                    jor[0] if turno.bloque == Turno.Bloque.MANANA else jor[1]
                ):
                    continue
                if not entrenador_en_franja(c, turno):
                    continue
                ovr = coach_ovr.get(c.id)
                if ovr is not None and not ovr.disponible_en(ini_t, fin_t):
                    continue
                # No puede estar en dos pistas a la vez.
                if any(i < fin_t and f > ini_t for i, f in ocupacion_coach[c.id]):
                    continue
                elegibles.append(c)
            players = _available_players(
                semana, dia, turno, sponsors, escuela_cfg, surface_prefs,
                exclusive_escuela_id=turnos_exclusivos.get(turno.id),
                cfg=cfg, hechas_dia=sesiones_hoy, hechas_semana=player_sessions,
                idx_dia=dias.index(dia), n_dias=len(dias),
                hechas_bloque=sesiones_bloque,
                dias_presente=dias_presente, orden_dia=orden_por_dia.get(dia, {}),
                horario=horario, cupo_horario=cupo_horario,
            )
            # #17: por la tarde nunca se usan los clubs satélite. Solo pistas de
            # sedes no satélite; el desbordamiento queda en banquillo, no spillea.
            turno_courts = (
                [c for c in courts if not c.is_satellite]
                if turno.bloque == Turno.Bloque.TARDE
                else courts
            )
            result = solve_pairing(
                PairingInput(
                    players=players,
                    courts=turno_courts,
                    vetoes=vetoes,
                    recent_partners=recent,
                    time_limit_s=cfg.time_limit_s,
                    w_assign=cfg.peso_asignacion,
                    w_satellite=cfg.peso_satelite,
                    w_central=cfg.peso_central,
                    w_repeat=cfg.peso_repeticion,
                    apply_neighbor=cfg.aplicar_vecindad,
                    neighbor_span=cfg.vecindad_max,
                    min_occupancy=1 if cfg.permitir_individuales else 2,
                    w_density=cfg.peso_densidad,
                    w_court=cfg.peso_pista_abierta,
                    pairs_hard=pairs_hard,
                    pairs_soft=pairs_soft,
                    w_pair=cfg.peso_pareja,
                )
            )
            # Regenerar = rehacer el turno desde cero (incluye celdas editadas a
            # mano/por swap), para no chocar con el unique al reasignar.
            Asignacion.objects.filter(
                semana=semana, dia=dia, turno=turno
            ).delete()
            # Un entrenador por pista, y a cada una quien más les toca a sus
            # alumnos según sus porcentajes y lo que llevan hecho esta semana.
            entrenador_de, repetidos = _emparejar_entrenadores(
                result.courts, sponsors, elegibles, load,
                pesos=pesos, con_quien=coach_share, sesiones=player_sessions,
                blandos=blandos,
                info_pistas={c.id: (c.venue_id, c.number, c.fill_rank)
                             for c in turno_courts},
            )
            sin_entrenador = [p for p in result.courts if p not in entrenador_de]
            if sin_entrenador:
                report.setdefault("sin_entrenador", []).append(
                    {"dia": dia, "turno": turno.codigo, "pistas": sin_entrenador}
                )
            for court_id, member_ids in result.courts.items():
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
                    # Historial para acercarse a los % objetivo (#12) y para
                    # el reparto de dosis semanal/diaria (#18).
                    player_sessions[jid] += 1
                    sesiones_hoy[jid] += 1
                    sesiones_bloque[(jid, turno.bloque)] += 1
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
            if result.unassigned:
                report["unassigned"].append(
                    {
                        "dia": dia,
                        "turno": turno.codigo,
                        "jugadores": result.unassigned,
                        "status": result.status,
                    }
                )
            report["dias"].setdefault(dia, {})[turno.codigo] = result.status

    semana.generado_at = datetime.now(timezone.utc)
    semana.save(update_fields=["generado_at"])
    return report


def regenerate_afternoon(semana: Semana, dia: int) -> dict:
    """PRD §02: re-generate ONLY the afternoon block for one day (e.g. after a
    midday injury), leaving the morning and other days intact."""
    return generate(semana, dias=[dia], bloques=[Turno.Bloque.TARDE])
