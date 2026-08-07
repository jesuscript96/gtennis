from rest_framework import serializers

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


class PistaSerializer(serializers.ModelSerializer):
    sede_nombre = serializers.CharField(source="sede.nombre", read_only=True)

    class Meta:
        model = Pista
        fields = ["id", "sede", "sede_nombre", "numero", "superficie", "activa"]


class SedeSerializer(serializers.ModelSerializer):
    pistas = PistaSerializer(many=True, read_only=True)

    class Meta:
        model = Sede
        fields = [
            "id", "nombre", "es_satelite", "densidad_default", "densidad_max",
            "orden_desbordamiento", "activa", "pistas",
        ]


class TurnoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Turno
        fields = [
            "id", "codigo", "nombre", "bloque", "hora_inicio", "hora_fin",
            "hora_inicio_verano", "hora_fin_verano", "orden",
        ]


class DivisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Division
        fields = ["id", "nivel", "nombre"]


class EntrenadorSerializer(serializers.ModelSerializer):
    divisiones_habilitadas_display = serializers.SerializerMethodField()

    class Meta:
        model = Entrenador
        fields = [
            "id", "nombre", "activo", "disponibilidad_notas", "disponible_semana",
            "foto_url", "gestiona_todos_jugadores", "divisiones_habilitadas",
            "divisiones_habilitadas_display",
        ]

    def get_divisiones_habilitadas_display(self, obj):
        niveles = sorted(obj.divisiones_habilitadas.values_list("nivel", flat=True))
        return "Todas" if not niveles else ", ".join(f"D{n}" for n in niveles)


class VacacionesEntrenadorSerializer(serializers.ModelSerializer):
    entrenador_nombre = serializers.CharField(
        source="entrenador.nombre", read_only=True
    )

    class Meta:
        model = VacacionesEntrenador
        fields = [
            "id", "entrenador", "entrenador_nombre", "fecha_inicio", "fecha_fin",
            "motivo",
        ]


class JugadorSerializer(serializers.ModelSerializer):
    division_nivel = serializers.IntegerField(
        source="division.nivel", read_only=True, default=None
    )
    entrenador_nombre = serializers.CharField(
        source="entrenador_responsable.nombre", read_only=True, default=None
    )
    escuela_nombre = serializers.CharField(
        source="escuela.nombre", read_only=True, default=None
    )

    class Meta:
        model = Jugador
        fields = [
            "id", "nombre", "codigo_cliente", "categoria", "edad",
            "fecha_nacimiento", "es_menor", "email", "telefono",
            "consentimiento_rgpd", "division", "division_nivel",
            "entrenador_responsable", "entrenador_nombre", "escuela",
            "escuela_nombre", "foto_url", "activo", "notas",
        ]


class RencillaSerializer(serializers.ModelSerializer):
    jugador_a_nombre = serializers.CharField(source="jugador_a.nombre", read_only=True)
    jugador_b_nombre = serializers.CharField(source="jugador_b.nombre", read_only=True)

    class Meta:
        model = Rencilla
        fields = [
            "id", "jugador_a", "jugador_a_nombre", "jugador_b",
            "jugador_b_nombre", "activa", "motivo",
        ]


class ResponsableJugadorSerializer(serializers.ModelSerializer):
    jugador_nombre = serializers.CharField(source="jugador.nombre", read_only=True)
    entrenador_nombre = serializers.CharField(
        source="entrenador.nombre", read_only=True
    )

    class Meta:
        model = ResponsableJugador
        fields = [
            "id", "jugador", "jugador_nombre", "entrenador", "entrenador_nombre",
            "prioridad", "porcentaje_objetivo", "activo",
        ]


class EscuelaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Escuela
        fields = ["id", "nombre", "activa", "orden"]


class AvisoSerializer(serializers.ModelSerializer):
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)

    class Meta:
        model = Aviso
        fields = [
            "id", "usuario", "para_direccion", "tipo", "tipo_display", "titulo",
            "mensaje", "leido", "created_at",
        ]
        read_only_fields = ["created_at"]


class InvitadoSerializer(serializers.ModelSerializer):
    entrenador_nombre = serializers.CharField(
        source="entrenador_solicitante.nombre", read_only=True
    )
    grupo_nombre = serializers.CharField(
        source="grupo_anfitrion.nombre", read_only=True, default=None
    )
    estado_display = serializers.CharField(
        source="get_estado_display", read_only=True
    )

    class Meta:
        model = Invitado
        fields = [
            "id", "nombre", "entrenador_solicitante", "entrenador_nombre",
            "grupo_anfitrion", "grupo_nombre", "estado", "estado_display",
            "aprobado_por", "jugador_creado", "nota", "created_at",
        ]
        read_only_fields = ["estado", "aprobado_por", "jugador_creado", "created_at"]
        extra_kwargs = {"entrenador_solicitante": {"required": False}}


class TareaMantenimientoSerializer(serializers.ModelSerializer):
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)

    class Meta:
        model = TareaMantenimiento
        fields = [
            "id", "titulo", "descripcion", "responsable", "fecha_limite",
            "estado", "estado_display", "created_at",
        ]
        read_only_fields = ["created_at"]


class FeedbackSerializer(serializers.ModelSerializer):
    prioridad_display = serializers.CharField(
        source="get_prioridad_display", read_only=True
    )
    estado_display = serializers.CharField(
        source="get_estado_display", read_only=True
    )
    creado_por_nombre = serializers.CharField(
        source="creado_por.username", read_only=True, default=None
    )

    class Meta:
        model = Feedback
        fields = [
            "id", "autor", "prioridad", "prioridad_display", "titulo",
            "descripcion", "estado", "estado_display", "creado_por",
            "creado_por_nombre", "created_at",
        ]
        read_only_fields = ["creado_por", "created_at"]


class ContratoSerializer(serializers.ModelSerializer):
    jugador_nombre = serializers.CharField(source="jugador.nombre", read_only=True)
    entrenador_nombre = serializers.CharField(
        source="entrenador.nombre", read_only=True
    )

    class Meta:
        model = Contrato
        fields = [
            "id", "jugador", "jugador_nombre", "entrenador",
            "entrenador_nombre", "activo",
        ]
