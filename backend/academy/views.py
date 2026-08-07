from django.db.models import Case, IntegerField, Q, Value, When
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    Aviso,
    Contrato,
    Division,
    Entrenador,
    Escuela,
    Feedback,
    Invitado,
    Jugador,
    Pista,
    Rencilla,
    ResponsableJugador,
    Sede,
    TareaMantenimiento,
    Turno,
    VacacionesEntrenador,
)
from .serializers import (
    AvisoSerializer,
    ContratoSerializer,
    DivisionSerializer,
    EntrenadorSerializer,
    EscuelaSerializer,
    FeedbackSerializer,
    InvitadoSerializer,
    JugadorSerializer,
    PistaSerializer,
    RencillaSerializer,
    ResponsableJugadorSerializer,
    SedeSerializer,
    TareaMantenimientoSerializer,
    TurnoSerializer,
    VacacionesEntrenadorSerializer,
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
    queryset = Jugador.objects.filter(activo=True).select_related("division", "entrenador_responsable").all()
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


class ResponsableJugadorViewSet(viewsets.ModelViewSet):
    serializer_class = ResponsableJugadorSerializer
    queryset = ResponsableJugador.objects.select_related(
        "jugador", "entrenador"
    ).all()

    def get_queryset(self):
        qs = super().get_queryset()
        jugador = self.request.query_params.get("jugador")
        return qs.filter(jugador=jugador) if jugador else qs


class VacacionesEntrenadorViewSet(viewsets.ModelViewSet):
    queryset = VacacionesEntrenador.objects.select_related("entrenador").all()
    serializer_class = VacacionesEntrenadorSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["fecha_inicio", "fecha_fin"]


class EscuelaViewSet(viewsets.ModelViewSet):
    queryset = Escuela.objects.all()
    serializer_class = EscuelaSerializer


class AvisoViewSet(viewsets.ModelViewSet):
    """Avisos in-app mostrados en el perfil. Cada usuario ve los suyos; el Super
    Admin ve además los dirigidos a dirección."""

    serializer_class = AvisoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        u = self.request.user
        qs = Aviso.objects.all()
        if u.is_superadmin:
            return qs.filter(Q(usuario=u) | Q(para_direccion=True))
        return qs.filter(usuario=u)

    @action(detail=True, methods=["post"])
    def leer(self, request, pk=None):
        aviso = self.get_object()
        aviso.leido = True
        aviso.save(update_fields=["leido"])
        return Response({"ok": True})


class InvitadoViewSet(viewsets.ModelViewSet):
    """Invitados propuestos por entrenadores; aprobación por el Super Admin (#5)."""

    serializer_class = InvitadoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        u = self.request.user
        qs = Invitado.objects.select_related(
            "entrenador_solicitante", "grupo_anfitrion"
        )
        if u.is_superadmin:
            return qs
        ent = getattr(u, "entrenador", None)
        return qs.filter(entrenador_solicitante=ent) if ent else qs.none()

    def perform_create(self, serializer):
        u = self.request.user
        ent = getattr(u, "entrenador", None)
        solicitante = serializer.validated_data.get("entrenador_solicitante") or ent
        if solicitante is None:
            raise PermissionDenied("Tu usuario no está enlazado a un entrenador.")
        inv = serializer.save(entrenador_solicitante=solicitante)
        Aviso.objects.create(
            para_direccion=True,
            tipo=Aviso.Tipo.INVITADO,
            titulo=f"Invitado pendiente: {inv.nombre}",
            mensaje=f"{solicitante.nombre} solicita añadir a «{inv.nombre}». Requiere tu aprobación.",
        )

    def _avisar_solicitante(self, inv, titulo, mensaje):
        user = getattr(inv.entrenador_solicitante, "user", None)
        if user:
            Aviso.objects.create(
                usuario=user, tipo=Aviso.Tipo.INVITADO, titulo=titulo, mensaje=mensaje
            )

    @action(detail=True, methods=["post"])
    def aprobar(self, request, pk=None):
        if not request.user.is_superadmin:
            raise PermissionDenied("Solo la dirección deportiva aprueba invitados.")
        inv = self.get_object()
        if inv.estado != Invitado.Estado.PENDIENTE:
            return Response({"error": "El invitado ya está resuelto."}, status=409)
        anfitrion = inv.grupo_anfitrion
        jugador = Jugador.objects.create(
            nombre=f"{inv.nombre} (invitado)",
            activo=True,
            escuela=anfitrion.escuela if anfitrion else None,
            entrenador_responsable=anfitrion.entrenador_responsable if anfitrion else None,
            division=anfitrion.division if anfitrion else None,
            notas="Invitado (pendiente de ubicar en el cuadrante)",
        )
        inv.estado = Invitado.Estado.APROBADO
        inv.aprobado_por = request.user
        inv.jugador_creado = jugador
        inv.save()
        self._avisar_solicitante(
            inv, f"Invitado aprobado: {inv.nombre}",
            "Ya puedes ubicarlo en el cuadrante desde el banquillo.",
        )
        return Response(InvitadoSerializer(inv).data)

    @action(detail=True, methods=["post"])
    def rechazar(self, request, pk=None):
        if not request.user.is_superadmin:
            raise PermissionDenied("Solo la dirección deportiva rechaza invitados.")
        inv = self.get_object()
        if inv.estado != Invitado.Estado.PENDIENTE:
            return Response({"error": "El invitado ya está resuelto."}, status=409)
        inv.estado = Invitado.Estado.RECHAZADO
        inv.aprobado_por = request.user
        inv.save()
        self._avisar_solicitante(
            inv, f"Invitado rechazado: {inv.nombre}", request.data.get("motivo", "")
        )
        return Response(InvitadoSerializer(inv).data)


class TareaMantenimientoViewSet(viewsets.ModelViewSet):
    queryset = TareaMantenimiento.objects.all()
    serializer_class = TareaMantenimientoSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["titulo", "descripcion", "responsable"]
    ordering_fields = ["fecha_limite", "estado", "created_at"]

    def perform_create(self, serializer):
        tarea = serializer.save()
        # Aviso in-app a dirección (sin notificación externa por ahora).
        Aviso.objects.create(
            para_direccion=True,
            tipo=Aviso.Tipo.MANTENIMIENTO,
            titulo=f"Nueva tarea de mantenimiento: {tarea.titulo}",
            mensaje=(f"Responsable: {tarea.responsable}. " if tarea.responsable else "")
            + (f"Límite: {tarea.fecha_limite}." if tarea.fecha_limite else ""),
        )


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
