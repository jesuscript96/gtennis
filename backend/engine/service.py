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


def _build_courts() -> list[Court]:
    courts = []
    for pista in Pista.objects.filter(activa=True).select_related("sede"):
        if not pista.sede.activa:
            continue
        courts.append(
            Court(
                id=pista.id,
                venue_id=pista.sede_id,
                capacity=pista.sede.densidad_default,
                is_satellite=pista.sede.es_satelite,
                fill_rank=pista.sede.orden_desbordamiento,
            )
        )
    return courts


def _vetoes() -> set[tuple[int, int]]:
    out = set()
    for r in Rencilla.objects.filter(activa=True):
        a, b = r.jugador_a_id, r.jugador_b_id
        out.add((a, b) if a <= b else (b, a))
    return out


def _sponsor_map() -> dict[int, set[int]]:
    """jugador_id -> set of coach ids that sponsor them."""
    m: dict[int, set[int]] = defaultdict(set)
    for c in Contrato.objects.filter(activo=True):
        m[c.jugador_id].add(c.entrenador_id)
    return m


def _overrides(semana: Semana, dia: int) -> dict[tuple[int, str], Disponibilidad]:
    """(jugador_id, ambito) -> Disponibilidad for the day. ambito is one of
    DIA / MANANA / TARDE / M1 / M2 / T1 / T2."""
    out = {}
    for d in Disponibilidad.objects.filter(semana=semana, dia=dia):
        out[(d.jugador_id, d.ambito)] = d
    return out


def _effective_state(overrides, jugador_id, turno):
    """Resolución por prioridad: turno concreto > bloque (mañana/tarde) > día."""
    for key in (turno.codigo, turno.bloque, "DIA"):
        d = overrides.get((jugador_id, key))
        if d:
            return d.estado
    return Estado.DISPONIBLE


def _player_priority(division, state):
    """Higher-division players get higher priority (8 → 1).
    Players with molestias/torneo are deprioritised so they fill spots
    only after fully-available players."""
    base = division if division else 4
    if state in ESTADOS_DEPRIORIZADOS:
        base = max(1, base // 2)
    return base


def _available_players(semana, dia, turno, sponsors) -> list[Player]:
    from academy.models import Jugador

    overrides = _overrides(semana, dia)
    players = []
    for j in Jugador.objects.filter(activo=True).select_related("division"):
        state = _effective_state(overrides, j.id, turno)
        if state in ESTADOS_EXCLUYENTES:
            continue
        division = j.division.nivel if j.division else None
        coach = next(iter(sponsors.get(j.id, set())), None)
        players.append(
            Player(
                id=j.id,
                division=division,
                sponsor_coach_id=coach,
                priority=_player_priority(division, state),
            )
        )
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


def _coach_capacita(coach, coach_niveles, court_niveles):
    """¿El entrenador está capacitado para las divisiones de esta pista? (#3)"""
    habil = coach_niveles.get(coach.id)
    if habil is None:
        return True
    return all(n is None or n in habil for n in court_niveles)


def _assign_coaches(
    members, sponsors, elegibles, coach_niveles, player_div,
    player_responsables, coach_share, player_sessions, load,
):
    """Pick one coach per court entre los `elegibles` (ya filtrados por
    disponibilidad horaria y vacaciones):

      0) capacitado para las divisiones de la pista (#3);
      1) sponsor (contrato) de algún jugador de la pista;
      2) responsable del jugador, respetando prioridad y acercándose al %
         objetivo de entrenos deseado (#2/#12, best-effort);
      3) el menos cargado (rotación equilibrada).
    """
    court_niveles = {player_div.get(jid) for jid in members}
    capaces = [c for c in elegibles if _coach_capacita(c, coach_niveles, court_niveles)]
    if not capaces:
        return None
    cap_ids = {c.id for c in capaces}

    # 1) sponsor on this court
    for jid in members:
        for cid in sponsors.get(jid, set()):
            if cid in cap_ids:
                load[cid] += 1
                return cid

    # 2) responsables ponderados por prioridad y déficit respecto al % objetivo.
    scores: dict[int, float] = {}
    for jid in members:
        total = max(1, player_sessions.get(jid, 0))
        for cid, prio, pct in player_responsables.get(jid, []):
            if cid not in cap_ids:
                continue
            share = 100.0 * coach_share.get((jid, cid), 0) / total
            # Déficit: cuánto le falta a este entrenador para su % objetivo.
            deficit = (pct - share) if pct else 0.0
            # El principal (prioridad 1) recibe un empujón base.
            base = 6.0 if prio == 1 else max(0.0, 4.0 - prio)
            scores[cid] = scores.get(cid, 0.0) + deficit + base
    if scores:
        best = max(scores.items(), key=lambda kv: (kv[1], -load[kv[0]]))[0]
        load[best] += 1
        return best

    # 3) least-loaded capable coach (balanced rotation)
    chosen = min(capaces, key=lambda e: load[e.id])
    load[chosen.id] += 1
    return chosen.id


@transaction.atomic
def generate(semana: Semana, dias=None, bloques=None) -> dict:
    """Generate (or regenerate) the cuadrante.

    dias: iterable of day indices (default Mon-Sat).
    bloques: restrict to {'MANANA','TARDE'} shifts — used by the afternoon
             regeneration so the morning history stays untouched.
    """
    dias = list(dias) if dias is not None else [d for d, _ in DIAS]
    turnos = list(Turno.objects.all())
    if bloques:
        turnos = [t for t in turnos if t.bloque in bloques]

    courts = _build_courts()
    courts_by_id = {c.id: c for c in courts}
    vetoes = _vetoes()
    sponsors = _sponsor_map()
    cfg = ConfiguracionMotor.get_solo()
    load: Counter = Counter()
    report = {"dias": {}, "overflow": [], "unassigned": []}

    # --- Entrenadores: capacidad por división (#3) y disponibilidad (#10/#11) --
    from academy.models import Jugador

    all_coaches = list(
        Entrenador.objects.filter(activo=True, disponible_semana=True)
        .prefetch_related("divisiones_habilitadas")
    )
    coach_niveles = {c.id: c.niveles_habilitados() for c in all_coaches}
    player_div = dict(
        Jugador.objects.filter(activo=True).values_list("id", "division__nivel")
    )

    # Responsables ponderados por jugador (#2/#12): prioridad y % objetivo.
    from academy.models import ResponsableJugador

    player_responsables: dict[int, list] = defaultdict(list)
    for rj in ResponsableJugador.objects.filter(activo=True).order_by(
        "jugador_id", "prioridad"
    ):
        player_responsables[rj.jugador_id].append(
            (rj.entrenador_id, rj.prioridad, rj.porcentaje_objetivo)
        )
    # Fallback: jugadores sin fila usan su entrenador_responsable como principal.
    for jid, cid in Jugador.objects.filter(
        activo=True, entrenador_responsable__isnull=False
    ).values_list("id", "entrenador_responsable_id"):
        if jid not in player_responsables:
            player_responsables[jid].append((cid, 1, 0))

    # Recuento de sesiones para acercarse a los % objetivo a lo largo de la semana.
    coach_share: Counter = Counter()      # (jugador_id, coach_id) -> nº sesiones
    player_sessions: Counter = Counter()  # jugador_id -> nº sesiones

    for dia in dias:
        overrides = _overrides(semana, dia)
        recent = _recent_partners(semana, dia)
        # Strongly penalise pairs that already hit the per-week repeat limit.
        recent = {
            pair: count * (5 if count >= cfg.max_dias_misma_pista else 1)
            for pair, count in recent.items()
        }
        # Entrenadores fuera por vacaciones ese día (#11) y overrides del día (#10).
        fecha = semana.fecha_inicio + timedelta(days=dia)
        vac_ids = set(
            VacacionesEntrenador.objects.filter(
                fecha_inicio__lte=fecha, fecha_fin__gte=fecha
            ).values_list("entrenador_id", flat=True)
        )
        coach_ovr = {
            d.entrenador_id: d
            for d in DisponibilidadEntrenador.objects.filter(semana=semana, dia=dia)
        }
        for turno in turnos:
            # Entrenadores elegibles para este turno: no de vacaciones y cuya
            # ventana horaria cubre el turno (según horario de temporada).
            ini_t, fin_t = turno.horas(fecha)
            elegibles = []
            for c in all_coaches:
                if c.id in vac_ids:
                    continue
                ovr = coach_ovr.get(c.id)
                if ovr is not None and not ovr.disponible_en(ini_t, fin_t):
                    continue
                elegibles.append(c)
            players = _available_players(semana, dia, turno, sponsors)
            result = solve_pairing(
                PairingInput(
                    players=players,
                    courts=courts,
                    vetoes=vetoes,
                    recent_partners=recent,
                    time_limit_s=cfg.time_limit_s,
                    w_assign=cfg.peso_asignacion,
                    w_satellite=cfg.peso_satelite,
                    w_central=cfg.peso_central,
                    w_repeat=cfg.peso_repeticion,
                    apply_neighbor=cfg.aplicar_vecindad,
                )
            )
            # Regenerar = rehacer el turno desde cero (incluye celdas editadas a
            # mano/por swap), para no chocar con el unique al reasignar.
            Asignacion.objects.filter(
                semana=semana, dia=dia, turno=turno
            ).delete()
            for court_id, member_ids in result.courts.items():
                coach_id = _assign_coaches(
                    member_ids, sponsors, elegibles, coach_niveles, player_div,
                    player_responsables, coach_share, player_sessions, load,
                )
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
                    # Historial para acercarse a los % objetivo (#12).
                    player_sessions[jid] += 1
                    if coach_id:
                        coach_share[(jid, coach_id)] += 1
                if courts_by_id[court_id].is_satellite:
                    report["overflow"].append(
                        {"dia": dia, "turno": turno.codigo, "pista": court_id}
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
