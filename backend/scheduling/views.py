from datetime import datetime, timedelta, timezone

from django.utils import timezone as djtz
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from academy.models import Sede, Turno
from engine.service import generate, regenerate_afternoon

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
        dia = now.weekday()  # 0=Mon .. 6=Sun
        t = now.time()
        turnos = list(Turno.objects.all().order_by("orden"))
        actual = proximo = None
        mins = None
        if dia <= 5:
            for tr in turnos:
                if tr.hora_inicio <= t <= tr.hora_fin:
                    actual = tr
                    break
            if actual is None:
                for tr in turnos:
                    if t < tr.hora_inicio:
                        proximo = tr
                        delta = (datetime.combine(now.date(), tr.hora_inicio)
                                 - datetime.combine(now.date(), t))
                        mins = int(delta.total_seconds() // 60)
                        break
        mostrado = actual or proximo
        status = "en_curso" if actual else ("proximo" if proximo else "cerrado")

        monday = now.date() - timedelta(days=dia)
        semana = Semana.objects.filter(fecha_inicio=monday).first()
        asignaciones = []
        if semana and mostrado and dia <= 5:
            qs = (
                Asignacion.objects.filter(semana=semana, dia=dia, turno=mostrado)
                .select_related("jugador", "jugador__division", "entrenador",
                                "turno", "pista", "pista__sede")
            )
            asignaciones = AsignacionSerializer(qs, many=True).data

        return Response({
            "status": status,
            "ahora": now.strftime("%H:%M"),
            "dia": dia,
            "dia_nombre": dict(DIAS).get(dia, "Domingo"),
            "turno_actual": {"codigo": actual.codigo} if actual else None,
            "proximo": {"codigo": proximo.codigo, "en_minutos": mins} if proximo else None,
            "turno_mostrado": mostrado.codigo if mostrado else None,
            "semana": SemanaSerializer(semana).data if semana else None,
            "sedes": _sedes_payload(),
            "turnos": _turnos_payload(),
            "asignaciones": asignaciones,
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


class DisponibilidadViewSet(viewsets.ModelViewSet):
    serializer_class = DisponibilidadSerializer

    def get_queryset(self):
        qs = Disponibilidad.objects.all()
        semana = self.request.query_params.get("semana")
        return qs.filter(semana=semana) if semana else qs


class AsignacionViewSet(viewsets.ModelViewSet):
    """Read + manual override by Super Admin (sets manual=True)."""

    serializer_class = AsignacionSerializer
    queryset = Asignacion.objects.select_related(
        "jugador", "jugador__division", "entrenador", "turno", "pista", "pista__sede"
    ).all()

    def perform_update(self, serializer):
        serializer.save(manual=True)
