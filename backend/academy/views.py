from django.db.models import Case, IntegerField, Value, When
from rest_framework import filters, viewsets

from .models import (
    Contrato,
    Division,
    Entrenador,
    Feedback,
    Jugador,
    Pista,
    Rencilla,
    Sede,
    Turno,
)
from .serializers import (
    ContratoSerializer,
    DivisionSerializer,
    EntrenadorSerializer,
    FeedbackSerializer,
    JugadorSerializer,
    PistaSerializer,
    RencillaSerializer,
    SedeSerializer,
    TurnoSerializer,
)


class SedeViewSet(viewsets.ModelViewSet):
    queryset = Sede.objects.prefetch_related("pistas").all()
    serializer_class = SedeSerializer


class PistaViewSet(viewsets.ModelViewSet):
    queryset = Pista.objects.select_related("sede").all()
    serializer_class = PistaSerializer


class TurnoViewSet(viewsets.ModelViewSet):
    queryset = Turno.objects.all()
    serializer_class = TurnoSerializer


class DivisionViewSet(viewsets.ModelViewSet):
    queryset = Division.objects.all()
    serializer_class = DivisionSerializer


class EntrenadorViewSet(viewsets.ModelViewSet):
    queryset = Entrenador.objects.all()
    serializer_class = EntrenadorSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nombre"]
    ordering_fields = ["nombre", "activo"]


class JugadorViewSet(viewsets.ModelViewSet):
    queryset = Jugador.objects.select_related("division", "entrenador_responsable").all()
    serializer_class = JugadorSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nombre"]
    ordering_fields = ["nombre", "edad"]


class RencillaViewSet(viewsets.ModelViewSet):
    queryset = Rencilla.objects.all()
    serializer_class = RencillaSerializer


class ContratoViewSet(viewsets.ModelViewSet):
    queryset = Contrato.objects.all()
    serializer_class = ContratoSerializer


class FeedbackViewSet(viewsets.ModelViewSet):
    # Orden por severidad (Alta > Media > Baja) y luego por más reciente.
    queryset = Feedback.objects.annotate(
        _sev=Case(
            When(prioridad="ALTA", then=Value(0)),
            When(prioridad="MEDIA", then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        )
    ).order_by("_sev", "-created_at")
    serializer_class = FeedbackSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["autor", "titulo", "descripcion"]
    ordering_fields = ["created_at", "prioridad", "estado"]

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(creado_por=user)
