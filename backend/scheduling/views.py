from datetime import datetime, timezone

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from academy.models import Sede, Turno
from engine.service import generate, regenerate_afternoon

from .models import Asignacion, ConfiguracionMotor, Disponibilidad, Semana
from .serializers import (
    AsignacionSerializer,
    ConfiguracionMotorSerializer,
    DisponibilidadSerializer,
    SemanaSerializer,
)


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


class SemanaViewSet(viewsets.ModelViewSet):
    queryset = Semana.objects.all()
    serializer_class = SemanaSerializer

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
