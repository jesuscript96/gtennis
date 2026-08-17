from django.db.models import Case, IntegerField, Q, Value, When
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    Aviso,
    Coach,
    Contrato,
    Division,
    Entrenador,
    Escuela,
    Feedback,
    Invitado,
    Jugador,
    Pista,
    PreferenciaPareja,
    PreferenciaSuperficie,
    Rencilla,
    ResponsableJugador,
    Sede,
    TareaMantenimiento,
    Turno,
    VacacionesEntrenador,
)
from .permissions import DireccionOrCoachWrite, ReadOnlyOrDireccion
from .scope import coaches_del_entrenador, entrenadores_visibles, jugadores_visibles
from .serializers import (
    AvisoSerializer,
    CoachSerializer,
    ContratoSerializer,
    DivisionSerializer,
    EntrenadorSerializer,
    EscuelaSerializer,
    FeedbackSerializer,
    InvitadoSerializer,
    JugadorSerializer,
    PistaSerializer,
    PreferenciaSuperficieSerializer,
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
    permission_classes = [ReadOnlyOrDireccion]


class PistaViewSet(viewsets.ModelViewSet):
    queryset = Pista.objects.select_related("sede").all()
    serializer_class = PistaSerializer
    permission_classes = [ReadOnlyOrDireccion]


class TurnoViewSet(viewsets.ModelViewSet):
    queryset = Turno.objects.all()
    serializer_class = TurnoSerializer
    permission_classes = [ReadOnlyOrDireccion]


class DivisionViewSet(viewsets.ModelViewSet):
    queryset = Division.objects.all()
    serializer_class = DivisionSerializer
    permission_classes = [ReadOnlyOrDireccion]


class EntrenadorViewSet(viewsets.ModelViewSet):
    queryset = Entrenador.objects.all()
    serializer_class = EntrenadorSerializer
    permission_classes = [DireccionOrCoachWrite]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nombre"]
    ordering_fields = ["nombre", "activo"]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return super().get_queryset()
        return entrenadores_visibles(user)

    def perform_create(self, serializer):
        # Un coach que da de alta un entrenador lo añade a su propio equipo.
        ent = serializer.save()
        coach = getattr(self.request.user, "coach", None)
        if coach is not None:
            coach.entrenadores.add(ent)


class CoachViewSet(viewsets.ModelViewSet):
    """Gestión de coaches (#16). Solo la dirección deportiva los administra;
    un coach puede consultar su propia ficha."""

    queryset = Coach.objects.prefetch_related("entrenadores").all()
    serializer_class = CoachSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        u = self.request.user
        qs = Coach.objects.prefetch_related("entrenadores")
        if u.is_superadmin:
            return qs
        coach = getattr(u, "coach", None)
        return qs.filter(pk=coach.pk) if coach else qs.none()

    def _assert_direccion(self):
        if not self.request.user.is_superadmin:
            raise PermissionDenied("Solo la dirección deportiva gestiona coaches.")

    def perform_create(self, serializer):
        self._assert_direccion()
        serializer.save()

    def perform_update(self, serializer):
        u = self.request.user
        if not u.is_superadmin:
            coach = getattr(u, "coach", None)
            if coach is None or serializer.instance.pk != coach.pk:
                raise PermissionDenied("No puedes editar este coach.")
        serializer.save()

    def perform_destroy(self, instance):
        self._assert_direccion()
        instance.delete()


class JugadorViewSet(viewsets.ModelViewSet):
    queryset = Jugador.objects.filter(activo=True).select_related("division", "entrenador_responsable").all()
    serializer_class = JugadorSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nombre"]
    ordering_fields = ["nombre", "edad"]

    def get_queryset(self):
        base = Jugador.objects.filter(activo=True).select_related(
            "division", "entrenador_responsable"
        )
        user = self.request.user
        if not user.is_authenticated:
            return base
        return jugadores_visibles(user, base=base)

    def perform_update(self, serializer):
        # #18: al dar de baja (activo True->False) se avisa a dirección in-app.
        antes_activo = serializer.instance.activo
        jugador = serializer.save()
        if antes_activo and not jugador.activo:
            Aviso.objects.create(
                para_direccion=True,
                tipo=Aviso.Tipo.GENERAL,
                titulo=f"Baja de jugador: {jugador.nombre}",
                mensaje=f"{jugador.nombre} se ha dado de baja (marcado como inactivo).",
            )

    @action(detail=True, methods=["post"])
    def reportar_movimiento(self, request, pk=None):
        """#4: un entrenador/coach avisa de que ve a un jugador (suyo o de otra
        escuela) que parece haber cambiado de escuela. Crea avisos a dirección,
        al entrenador responsable y a su coach. No cambia la escuela: es un aviso.
        El scope de get_object() ya restringe a jugadores visibles por el usuario.
        """
        jugador = self.get_object()
        escuela_obs = (request.data.get("escuela_observada") or "").strip()
        nota = (request.data.get("nota") or "").strip()
        titulo = f"Posible movimiento de escuela: {jugador.nombre}"
        partes = []
        if escuela_obs:
            partes.append(f"Escuela observada: {escuela_obs}.")
        if nota:
            partes.append(nota)
        actor = getattr(request.user, "entrenador", None) or getattr(request.user, "coach", None)
        if actor is not None:
            partes.append(f"Reportado por {actor.nombre}.")
        mensaje = " ".join(partes)

        Aviso.objects.create(
            para_direccion=True, tipo=Aviso.Tipo.MOVIMIENTO, titulo=titulo, mensaje=mensaje,
        )
        ent = jugador.entrenador_responsable
        destinatarios = []
        if ent is not None and ent.user_id:
            destinatarios.append(ent.user)
        destinatarios.extend(coaches_del_entrenador(ent))
        for user in destinatarios:
            Aviso.objects.create(
                usuario=user, tipo=Aviso.Tipo.MOVIMIENTO, titulo=titulo, mensaje=mensaje,
            )
        return Response({"ok": True, "avisos_creados": 1 + len(destinatarios)})


class RencillaViewSet(viewsets.ModelViewSet):
    queryset = Rencilla.objects.all()
    serializer_class = RencillaSerializer
    permission_classes = [DireccionOrCoachWrite]


class ContratoViewSet(viewsets.ModelViewSet):
    queryset = Contrato.objects.all()
    serializer_class = ContratoSerializer
    permission_classes = [DireccionOrCoachWrite]


class ResponsableJugadorViewSet(viewsets.ModelViewSet):
    serializer_class = ResponsableJugadorSerializer
    permission_classes = [DireccionOrCoachWrite]
    queryset = ResponsableJugador.objects.select_related(
        "jugador", "entrenador"
    ).all()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        # Fuera de dirección, solo responsables de jugadores dentro del alcance.
        if user.is_authenticated and not user.is_superadmin:
            qs = qs.filter(jugador__in=jugadores_visibles(user))
        jugador = self.request.query_params.get("jugador")
        return qs.filter(jugador=jugador) if jugador else qs

    def perform_create(self, serializer):
        # Al añadir un responsable se re-reparte el % (#12: 70/15/15 auto).
        rj = serializer.save()
        rj.jugador.repartir_porcentajes()

    def perform_destroy(self, instance):
        jugador = instance.jugador
        instance.delete()
        jugador.repartir_porcentajes()


class VacacionesEntrenadorViewSet(viewsets.ModelViewSet):
    queryset = VacacionesEntrenador.objects.select_related("entrenador").all()
    serializer_class = VacacionesEntrenadorSerializer
    permission_classes = [DireccionOrCoachWrite]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["fecha_inicio", "fecha_fin"]

    def get_queryset(self):
        qs = VacacionesEntrenador.objects.select_related("entrenador")
        user = self.request.user
        if user.is_authenticated and not user.is_superadmin:
            coach = getattr(user, "coach", None)
            if coach is not None:
                return qs.filter(entrenador__in=coach.entrenadores.all())
            ent = getattr(user, "entrenador", None)
            return qs.filter(entrenador=ent) if ent else qs.none()
        return qs


class EscuelaViewSet(viewsets.ModelViewSet):
    queryset = Escuela.objects.all()
    serializer_class = EscuelaSerializer
    permission_classes = [ReadOnlyOrDireccion]


class PreferenciaSuperficieViewSet(viewsets.ModelViewSet):
    """Preferencias de superficie por jugador (#1)."""

    serializer_class = PreferenciaSuperficieSerializer
    queryset = PreferenciaSuperficie.objects.select_related("jugador").all()

    def get_queryset(self):
        qs = super().get_queryset()
        jugador = self.request.query_params.get("jugador")
        return qs.filter(jugador=jugador) if jugador else qs


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
        coach = getattr(u, "coach", None)
        if coach is not None:
            return qs.filter(entrenador_solicitante__in=coach.entrenadores.all())
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
        # Notificar siempre al Coach del entrenador solicitante (#5).
        from .scope import coaches_del_entrenador
        for coach_user in coaches_del_entrenador(solicitante):
            Aviso.objects.create(
                usuario=coach_user,
                tipo=Aviso.Tipo.INVITADO,
                titulo=f"Invitado propuesto por {solicitante.nombre}",
                mensaje=f"«{inv.nombre}» — pendiente de aprobación por dirección.",
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
        # Asociación por entrenador solicitante (#5 feedback Sergio): el grupo
        # del invitado se entiende por el entrenador que lo propone, no por un
        # 'grupo_anfitrión'. Derivamos escuela y responsable de ahí.
        solicitante = inv.entrenador_solicitante
        escuela_default = (
            Jugador.objects.filter(
                entrenadores_gestores=solicitante, activo=True
            ).values_list("escuela_id", flat=True).first()
        )
        if escuela_default is None:
            # Si el entrenador no tiene jugadores activos,alto rendimiento por defecto.
            from .models import Escuela
            escuela_default = (
                Escuela.objects.filter(nombre__icontains="alto rendimiento")
                .values_list("id", flat=True).first()
            )
        jugador = Jugador.objects.create(
            nombre=f"{inv.nombre} (invitado)",
            activo=True,
            escuela_id=escuela_default,
            entrenador_responsable=solicitante,
            # Datos propios del invitado si se aportaron (#5).
            division=inv.division,
            edad=inv.edad,
            notas="Invitado (pendiente de ubicar en el cuadrante)",
        )
        # Preferencia de superficie propia del invitado (#1/#5).
        if inv.superficie_pref:
            PreferenciaSuperficie.objects.create(
                jugador=jugador, superficie=inv.superficie_pref, estricta=True,
            )
        # Pareja preferida: que el sistema lo ubique con ese jugador (#5).
        if inv.jugar_con_id:
            PreferenciaPareja.objects.create(
                jugador=jugador,
                jugador_objetivo=inv.jugar_con,
                tipo=(
                    PreferenciaPareja.Tipo.HARD
                    if inv.pareja_estricta
                    else PreferenciaPareja.Tipo.SOFT
                ),
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

    def get_queryset(self):
        qs = super().get_queryset()
        # Filtrado por estado: acepta lista separada por comas
        # (?estado=NUEVO,EN_PROGRESO) para que el frontend pueda agrupar
        # varios estados bajo una misma pestaña.
        estados = self.request.query_params.get("estado")
        if estados:
            qs = qs.filter(estado__in=[e.strip() for e in estados.split(",") if e.strip()])
        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(creado_por=user)
