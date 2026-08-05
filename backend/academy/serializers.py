from rest_framework import serializers

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


class PistaSerializer(serializers.ModelSerializer):
    sede_nombre = serializers.CharField(source="sede.nombre", read_only=True)

    class Meta:
        model = Pista
        fields = ["id", "sede", "sede_nombre", "numero", "activa"]


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
        fields = ["id", "codigo", "nombre", "bloque", "hora_inicio", "hora_fin", "orden"]


class DivisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Division
        fields = ["id", "nivel", "nombre"]


class EntrenadorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Entrenador
        fields = [
            "id", "nombre", "activo", "disponibilidad_notas", "disponible_semana",
            "foto_url", "gestiona_todos_jugadores",
        ]


class JugadorSerializer(serializers.ModelSerializer):
    division_nivel = serializers.IntegerField(
        source="division.nivel", read_only=True, default=None
    )
    entrenador_nombre = serializers.CharField(
        source="entrenador_responsable.nombre", read_only=True, default=None
    )

    class Meta:
        model = Jugador
        fields = [
            "id", "nombre", "codigo_cliente", "categoria", "edad",
            "fecha_nacimiento", "es_menor", "email", "telefono",
            "consentimiento_rgpd", "division", "division_nivel",
            "entrenador_responsable", "entrenador_nombre", "foto_url",
            "activo", "notas",
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
