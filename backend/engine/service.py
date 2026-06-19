"""Bridges the pure pairing core (`pairing.py`) with Django models: gathers the
inputs for a Semana, runs the solver per (day, shift), assigns coaches and
persists Asignacion rows.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

from django.db import transaction

from academy.models import Contrato, Entrenador, Pista, Rencilla, Turno
from scheduling.models import (
    DIAS,
    ESTADOS_EXCLUYENTES,
    Asignacion,
    ConfiguracionMotor,
    Disponibilidad,
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


def _overrides(semana: Semana, dia: int) -> dict[tuple[int, int | None], Disponibilidad]:
    """(jugador_id, turno_id|None) -> Disponibilidad for the day."""
    out = {}
    for d in Disponibilidad.objects.filter(semana=semana, dia=dia):
        out[(d.jugador_id, d.turno_id)] = d
    return out


def _effective_state(overrides, jugador_id, turno_id):
    d = overrides.get((jugador_id, turno_id)) or overrides.get((jugador_id, None))
    return d.estado if d else Estado.DISPONIBLE


def _available_players(semana, dia, turno, sponsors) -> list[Player]:
    from academy.models import Jugador

    overrides = _overrides(semana, dia)
    players = []
    for j in Jugador.objects.filter(activo=True).select_related("division"):
        state = _effective_state(overrides, j.id, turno.id)
        if state in ESTADOS_EXCLUYENTES:
            continue
        coach = next(iter(sponsors.get(j.id, set())), None)
        players.append(
            Player(
                id=j.id,
                division=j.division.nivel if j.division else None,
                sponsor_coach_id=coach,
            )
        )
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


def _assign_coaches(members, sponsors, semana, load: Counter):
    """Pick one coach per court: sponsor of a player on it, else the player's
    responsible coach, else the least-loaded available coach (rotation)."""
    from academy.models import Jugador

    available = list(
        Entrenador.objects.filter(activo=True, disponible_semana=True)
    )
    avail_ids = {e.id for e in available}
    responsible = dict(
        Jugador.objects.filter(id__in=members).values_list(
            "id", "entrenador_responsable_id"
        )
    )
    # 1) sponsor on this court
    for jid in members:
        for cid in sponsors.get(jid, set()):
            if cid in avail_ids:
                load[cid] += 1
                return cid
    # 2) responsible coach
    for jid in members:
        cid = responsible.get(jid)
        if cid in avail_ids:
            load[cid] += 1
            return cid
    # 3) least-loaded available coach (balanced rotation)
    if available:
        chosen = min(available, key=lambda e: load[e.id])
        load[chosen.id] += 1
        return chosen.id
    return None


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

    for dia in dias:
        overrides = _overrides(semana, dia)
        recent = _recent_partners(semana, dia)
        # Strongly penalise pairs that already hit the per-week repeat limit.
        recent = {
            pair: count * (5 if count >= cfg.max_dias_misma_pista else 1)
            for pair, count in recent.items()
        }
        for turno in turnos:
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
                    w_repeat=cfg.peso_repeticion,
                    apply_neighbor=cfg.aplicar_vecindad,
                )
            )
            # Wipe only non-manual cells for this slot, then repopulate.
            Asignacion.objects.filter(
                semana=semana, dia=dia, turno=turno, manual=False
            ).delete()
            for court_id, member_ids in result.courts.items():
                coach_id = _assign_coaches(member_ids, sponsors, semana, load)
                for jid in member_ids:
                    Asignacion.objects.create(
                        semana=semana,
                        dia=dia,
                        turno=turno,
                        pista_id=court_id,
                        jugador_id=jid,
                        entrenador_id=coach_id,
                        estado=_effective_state(overrides, jid, turno.id),
                    )
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
