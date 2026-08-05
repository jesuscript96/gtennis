from datetime import datetime, timedelta, timezone

from django.utils import timezone as djtz
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from academy.models import Entrenador, Jugador, Sede, Turno
from engine.service import _effective_state, _overrides, generate, regenerate_afternoon

from .models import DIAS, Asignacion, ConfiguracionMotor, Disponibilidad, Semana
from .serializers import (
    AsignacionSerializer,
    ConfiguracionMotorSerializer,
    DisponibilidadSerializer,
    SemanaSerializer,
)


def _sedes_payload():
    return [
        {
            "id": s.id,
            "nombre": s.nombre,
            "es_satelite": s.es_satelite,
            "densidad_default": s.densidad_default,
            "pistas": [{"id": p.id, "numero": p.numero} for p in s.pistas.all()],
        }
        for s in Sede.objects.filter(activa=True).prefetch_related("pistas")
    ]


def _turnos_payload():
    return [
        {"id": t.id, "codigo": t.codigo, "bloque": t.bloque,
         "hora_inicio": t.hora_inicio, "hora_fin": t.hora_fin}
        for t in Turno.objects.all()
    ]


class ConfiguracionView(APIView):
    """Singleton config of the engine criteria. GET public, PATCH needs auth."""

    def get(self, request):
        return Response(
            ConfiguracionMotorSerializer(ConfiguracionMotor.get_solo()).data
        )

    def patch(self, request):
        cfg = ConfiguracionMotor.get_solo()
        s = ConfiguracionMotorSerializer(cfg, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)


class AhoraView(APIView):
    """Live 'NOW' view: resolves the current day/shift in Europe/Madrid and
    returns the courts to render for that moment."""

    def get(self, request):
        now = djtz.localtime()
        hoy = now.weekday()  # 0=Mon .. 6=Sun
        t = now.time()
        turnos = list(Turno.objects.all().order_by("orden"))
        empty = {
            "ahora": now.strftime("%H:%M"), "dia": hoy,
            "dia_nombre": dict(DIAS).get(hoy, "Domingo"),
            "turno_actual": None, "proximo": None, "turno_mostrado": None,
            "sedes": _sedes_payload(), "turnos": _turnos_payload(), "asignaciones": [],
        }

        # Semana de referencia: la de esta semana (si está generada) o la última generada.
        monday = now.date() - timedelta(days=hoy)
        semana = Semana.objects.filter(
            fecha_inicio=monday, generado_at__isnull=False
        ).first() or (
            Semana.objects.filter(generado_at__isnull=False)
            .order_by("-fecha_inicio").first()
        )
        if not semana:
            return Response({"status": "sin_semana", "semana": None, **empty})

        dias_con_datos = set(
            Asignacion.objects.filter(semana=semana).values_list("dia", flat=True)
        )
        es_semana_actual = semana.fecha_inicio == monday

        # 1) ¿Hay un turno EN CURSO ahora mismo?
        actual = None
        if es_semana_actual and hoy <= 5 and hoy in dias_con_datos:
            for tr in turnos:
                if tr.hora_inicio <= t <= tr.hora_fin:
                    actual = tr
                    break

        mins = None
        if actual:
            dia_sel, turno_sel, status = hoy, actual, "en_curso"
        else:
            # 2) El PRÓXIMO (día, turno) con datos, empezando desde "ahora".
            slots = [(d, tr) for d in range(6) for tr in turnos]
            start = 0
            if es_semana_actual and hoy <= 5:
                for i, (d, tr) in enumerate(slots):
                    if d > hoy or (d == hoy and tr.hora_inicio > t):
                        start = i
                        break
            dia_sel = turno_sel = None
            for k in range(len(slots)):
                d, tr = slots[(start + k) % len(slots)]
                if d in dias_con_datos:
                    dia_sel, turno_sel = d, tr
                    break
            if dia_sel is None:
                dia_sel, turno_sel = hoy, turnos[0]
            status = "proximo"
            if es_semana_actual and dia_sel == hoy and turno_sel.hora_inicio > t:
                delta = (datetime.combine(now.date(), turno_sel.hora_inicio)
                         - datetime.combine(now.date(), t))
                mins = int(delta.total_seconds() // 60)

        qs = (
            Asignacion.objects.filter(semana=semana, dia=dia_sel, turno=turno_sel)
            .select_related("jugador", "jugador__division", "entrenador",
                            "turno", "pista", "pista__sede")
        )
        return Response({
            "status": status,
            "ahora": now.strftime("%H:%M"),
            "dia": dia_sel,
            "dia_nombre": dict(DIAS).get(dia_sel, "Domingo"),
            "turno_actual": {"codigo": turno_sel.codigo} if status == "en_curso" else None,
            "proximo": ({"codigo": turno_sel.codigo, "en_minutos": mins}
                        if status == "proximo" else None),
            "turno_mostrado": turno_sel.codigo,
            "semana": SemanaSerializer(semana).data,
            "sedes": _sedes_payload(),
            "turnos": _turnos_payload(),
            "asignaciones": AsignacionSerializer(qs, many=True).data,
        })


class SemanaViewSet(viewsets.ModelViewSet):
    queryset = Semana.objects.all()
    serializer_class = SemanaSerializer

    @action(detail=True, methods=["get"])
    def tabla(self, request, pk=None):
        """All assignments of the week, for the structured weekly tables."""
        semana = self.get_object()
        qs = (
            Asignacion.objects.filter(semana=semana)
            .select_related("jugador", "jugador__division", "entrenador",
                            "turno", "pista", "pista__sede")
        )
        return Response({
            "semana": SemanaSerializer(semana).data,
            "dias": [{"idx": i, "nombre": n} for i, n in DIAS],
            "turnos": _turnos_payload(),
            "sedes": _sedes_payload(),
            "asignaciones": AsignacionSerializer(qs, many=True).data,
        })

    @action(detail=True, methods=["post"])
    def generar(self, request, pk=None):
        """Run the pairing engine for the whole week (the Sunday job)."""
        semana = self.get_object()
        report = generate(semana)
        return Response(report)

    @action(detail=True, methods=["post"])
    def regenerar_tarde(self, request, pk=None):
        """Regenerate only the afternoon block of one day (PRD §02)."""
        semana = self.get_object()
        dia = int(request.data.get("dia"))
        report = regenerate_afternoon(semana, dia)
        return Response(report)

    @action(detail=True, methods=["post"])
    def publicar(self, request, pk=None):
        semana = self.get_object()
        semana.estado = Semana.EstadoSemana.PUBLICADO
        semana.publicado_at = datetime.now(timezone.utc)
        semana.save(update_fields=["estado", "publicado_at"])
        return Response(SemanaSerializer(semana).data)

    @action(detail=True, methods=["get"])
    def cuadrante(self, request, pk=None):
        """Grid payload for the frontend, for one day (?dia=0)."""
        semana = self.get_object()
        dia = int(request.query_params.get("dia", 0))
        asignaciones = (
            Asignacion.objects.filter(semana=semana, dia=dia)
            .select_related("jugador", "jugador__division", "entrenador",
                            "turno", "pista", "pista__sede")
        )
        sedes = [
            {
                "id": s.id,
                "nombre": s.nombre,
                "es_satelite": s.es_satelite,
                "pistas": [{"id": p.id, "numero": p.numero} for p in s.pistas.all()],
            }
            for s in Sede.objects.filter(activa=True).prefetch_related("pistas")
        ]
        turnos = [
            {"id": t.id, "codigo": t.codigo, "bloque": t.bloque}
            for t in Turno.objects.all()
        ]
        return Response(
            {
                "semana": SemanaSerializer(semana).data,
                "dia": dia,
                "turnos": turnos,
                "sedes": sedes,
                "asignaciones": AsignacionSerializer(asignaciones, many=True).data,
            }
        )

    @action(detail=True, methods=["get"])
    def panel(self, request, pk=None):
        """Panel lateral para la vista de semana: jugadores agrupados por
        entrenador para un día dado (?dia=0).

        Devuelve dos secciones:
        - por_entrenador: entrenadores disponibles con sus jugadores
        - sin_entrenador: entrenadores no disponibles cuyos jugadores sí lo están
        """
        semana = self.get_object()
        dia = int(request.query_params.get("dia", 0))

        overrides = _overrides(semana, dia)
        assigned_ids = set(
            Asignacion.objects.filter(semana=semana, dia=dia).values_list(
                "jugador_id", flat=True
            )
        )

        # Un turno "ficticio" para resolver el estado a nivel de día.
        # _effective_state prueba turno > bloque > DIA; sin turno concreto,
        # cae al ámbito DIA.
        class _DiaOnly:
            codigo = None
            bloque = None
        dia_state = _DiaOnly()

        coaches = list(Entrenador.objects.filter(activo=True).order_by("nombre"))
        coach_map = {c.id: c for c in coaches}

        players = (
            Jugador.objects.filter(activo=True)
            .select_related("division", "entrenador_responsable")
            .order_by("nombre")
        )

        por_entrenador = []
        sin_entrenador = []

        # Agrupar jugadores por entrenador_responsable
        by_coach = {}
        no_coach = []
        for j in players:
            state = _effective_state(overrides, j.id, dia_state)
            # No se excluye ningún estado: los "no disponibles" (climatología,
            # ausencia, torneo…) deben aparecer en el banquillo para poder
            # forzar su asignación manualmente si se desea.
            entry = {
                "id": j.id,
                "nombre": j.nombre,
                "foto_url": j.foto_url or "",
                "division_nivel": j.division.nivel if j.division else None,
                "estado": state,
                "tiene_asignacion": j.id in assigned_ids,
            }
            cid = j.entrenador_responsable_id
            if cid and cid in coach_map:
                by_coach.setdefault(cid, []).append(entry)
            else:
                no_coach.append(entry)

        for c in coaches:
            jugador_list = by_coach.get(c.id, [])
            if not jugador_list:
                continue
            coach_data = {
                "entrenador": {
                    "id": c.id,
                    "nombre": c.nombre,
                    "foto_url": c.foto_url or "",
                    "disponible": c.disponible_semana,
                },
                "jugadores": jugador_list,
            }
            if c.disponible_semana:
                por_entrenador.append(coach_data)
            else:
                sin_entrenador.append(coach_data)

        # Jugadores sin entrenador responsable asignado
        if no_coach:
            sin_entrenador.append({
                "entrenador": {
                    "id": None,
                    "nombre": "Sin entrenador",
                    "foto_url": "",
                    "disponible": False,
                },
                "jugadores": no_coach,
            })

        # Entrenadores disponibles SIN pista asignada ese día (para el banquillo).
        assigned_coach_ids = set(
            Asignacion.objects.filter(semana=semana, dia=dia)
            .exclude(entrenador=None)
            .values_list("entrenador_id", flat=True)
        )
        entrenadores_libres = [
            {"id": c.id, "nombre": c.nombre, "foto_url": c.foto_url or ""}
            for c in coaches
            if c.disponible_semana and c.id not in assigned_coach_ids
        ]

        return Response({
            "dia": dia,
            "por_entrenador": por_entrenador,
            "sin_entrenador": sin_entrenador,
            "entrenadores_libres": entrenadores_libres,
        })


class DisponibilidadViewSet(viewsets.ModelViewSet):
    """Declarar ausencias/estados de jugadores.

    Acceso (PRD: solo Super Admin y entrenadores inician sesión):
      * Super Admin → cualquier jugador.
      * Entrenador  → solo los jugadores que puede gestionar
                      (todos, si `gestiona_todos_jugadores`, o su subconjunto).
    """

    serializer_class = DisponibilidadSerializer
    permission_classes = [IsAuthenticated]

    def _entrenador(self):
        return getattr(self.request.user, "entrenador", None)

    def _assert_puede(self, jugador):
        user = self.request.user
        if user.is_superadmin:
            return
        entrenador = self._entrenador()
        if entrenador is None:
            raise PermissionDenied("Tu usuario no está enlazado a un entrenador.")
        if not entrenador.puede_gestionar(jugador):
            raise PermissionDenied(
                "No tienes acceso para gestionar a este jugador."
            )

    def get_queryset(self):
        qs = Disponibilidad.objects.select_related("jugador", "semana")
        user = self.request.user
        if not user.is_superadmin:
            entrenador = self._entrenador()
            if entrenador is None:
                return qs.none()
            if not entrenador.gestiona_todos_jugadores:
                qs = qs.filter(jugador__in=entrenador.jugadores_gestionados.all())
        semana = self.request.query_params.get("semana")
        return qs.filter(semana=semana) if semana else qs

    def perform_create(self, serializer):
        self._assert_puede(serializer.validated_data["jugador"])
        serializer.save()

    def perform_update(self, serializer):
        jugador = serializer.validated_data.get(
            "jugador", serializer.instance.jugador
        )
        self._assert_puede(jugador)
        serializer.save()

    def perform_destroy(self, instance):
        self._assert_puede(instance.jugador)
        instance.delete()


class AsignacionViewSet(viewsets.ModelViewSet):
    """Read + manual override by Super Admin (sets manual=True)."""

    serializer_class = AsignacionSerializer
    queryset = Asignacion.objects.select_related(
        "jugador", "jugador__division", "entrenador", "turno", "pista", "pista__sede"
    ).all()

    def perform_update(self, serializer):
        serializer.save(manual=True)

    @action(detail=False, methods=["post"])
    def swap(self, request):
        """Drag & drop swap between two cells. campo='jugador' swaps the two
        players (row-level); campo='entrenador' swaps the coach of the two
        courts (all rows of each pista/turno)."""
        from django.db import transaction
        from academy.models import Jugador

        a_id = request.data.get("a")
        b_id = request.data.get("b")
        campo = request.data.get("campo", "jugador")
        with transaction.atomic():
            A = Asignacion.objects.select_for_update().get(pk=a_id)
            B = Asignacion.objects.select_for_update().get(pk=b_id)

            if campo == "entrenador":
                ca, cb = A.entrenador_id, B.entrenador_id
                Asignacion.objects.filter(
                    semana=A.semana, dia=A.dia, turno=A.turno, pista=A.pista
                ).update(entrenador=cb, manual=True)
                Asignacion.objects.filter(
                    semana=B.semana, dia=B.dia, turno=B.turno, pista=B.pista
                ).update(entrenador=ca, manual=True)
            else:
                ja, jb = A.jugador_id, B.jugador_id
                if ja != jb:
                    # Park A on a free player so the unique (semana,dia,turno,
                    # jugador) constraint never clashes mid-swap.
                    used = set(
                        Asignacion.objects.filter(
                            semana=A.semana, dia=A.dia, turno=A.turno
                        ).values_list("jugador_id", flat=True)
                    )
                    temp = (
                        Jugador.objects.exclude(id__in=used | {ja, jb})
                        .values_list("id", flat=True).first()
                    ) or jb
                    A.jugador_id = temp; A.manual = True; A.save()
                    B.jugador_id = ja; B.manual = True; B.save()
                    A.jugador_id = jb; A.save()
        return Response({"ok": True})

    @action(detail=False, methods=["post"])
    def manual_assign(self, request):
        """Asignar manualmente un jugador a una pista/turno desde el panel.
        Crea una Asignacion con manual=True. Respeta capacidad de la pista
        y evita duplicados (semana, dia, turno, jugador)."""
        from academy.models import Pista

        jugador_id = request.data.get("jugador_id")
        semana_id = request.data.get("semana")
        dia = request.data.get("dia")
        turno_id = request.data.get("turno")
        pista_id = request.data.get("pista")

        if not all([jugador_id, semana_id, dia is not None, turno_id, pista_id]):
            return Response({"error": "Faltan parámetros."}, status=400)

        # ¿Ya asignado a este turno ese día?
        existing = Asignacion.objects.filter(
            semana_id=semana_id, dia=dia, turno_id=turno_id, jugador_id=jugador_id
        ).first()
        if existing:
            return Response(
                {"error": "El jugador ya tiene asignación en este turno."},
                status=409,
            )

        # ¿Capacidad de la pista? El auto-emparejamiento llena hasta
        # `densidad_default` (2), pero manualmente se puede forzar hasta
        # `densidad_max` (4) — p. ej. para colocar a un "no disponible".
        pista = Pista.objects.select_related("sede").get(pk=pista_id)
        tope = pista.sede.densidad_max or pista.sede.densidad_default
        count = Asignacion.objects.filter(
            semana_id=semana_id, dia=dia, turno_id=turno_id, pista_id=pista_id
        ).count()
        if count >= tope:
            return Response(
                {"error": f"La pista está llena ({count}/{tope})."},
                status=409,
            )

        # Estado efectivo del jugador ese día/turno: si está "no disponible",
        # la celda forzada conserva su color/estado en el cuadrante.
        turno = Turno.objects.get(pk=turno_id)
        estado = _effective_state(
            _overrides(Semana.objects.get(pk=semana_id), int(dia)),
            int(jugador_id),
            turno,
        )
        asig = Asignacion.objects.create(
            semana_id=semana_id,
            dia=dia,
            turno_id=turno_id,
            pista_id=pista_id,
            jugador_id=jugador_id,
            estado=estado,
            manual=True,
        )
        return Response(AsignacionSerializer(asig).data, status=201)

    @action(detail=False, methods=["post"])
    def set_coach(self, request):
        """Colocar un entrenador del banquillo en una pista/turno (todas sus
        filas). El que estuviera queda libre para el banquillo."""
        semana_id = request.data.get("semana")
        dia = request.data.get("dia")
        turno_id = request.data.get("turno")
        pista_id = request.data.get("pista")
        entrenador_id = request.data.get("entrenador_id")
        if not all([semana_id, dia is not None, turno_id, pista_id, entrenador_id]):
            return Response({"error": "Faltan parámetros."}, status=400)
        n = Asignacion.objects.filter(
            semana_id=semana_id, dia=dia, turno_id=turno_id, pista_id=pista_id
        ).update(entrenador_id=entrenador_id, manual=True)
        if n == 0:
            return Response(
                {"error": "La pista no tiene jugadores en ese turno."}, status=409
            )
        return Response({"ok": True, "actualizadas": n})
