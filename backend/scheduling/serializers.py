from rest_framework import serializers

from .models import Asignacion, ConfiguracionMotor, Disponibilidad, Semana


class SemanaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Semana
        fields = [
            "id", "fecha_inicio", "estado", "generado_at", "publicado_at",
        ]
        read_only_fields = ["generado_at", "publicado_at"]


class DisponibilidadSerializer(serializers.ModelSerializer):
    jugador_nombre = serializers.CharField(source="jugador.nombre", read_only=True)
    ambito_display = serializers.CharField(source="get_ambito_display", read_only=True)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    subtipo_display = serializers.CharField(source="get_subtipo_display", read_only=True)

    class Meta:
        model = Disponibilidad
        fields = [
            "id", "semana", "jugador", "jugador_nombre", "dia", "ambito",
            "ambito_display", "estado", "estado_display", "subtipo",
            "subtipo_display", "nota",
        ]


class ConfiguracionMotorSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfiguracionMotor
        fields = [
            "peso_asignacion", "peso_satelite", "peso_central",
            "peso_repeticion",
            "max_dias_misma_pista", "aplicar_vecindad", "time_limit_s",
        ]


class AsignacionSerializer(serializers.ModelSerializer):
    jugador_nombre = serializers.CharField(source="jugador.nombre", read_only=True)
    division_nivel = serializers.IntegerField(
        source="jugador.division.nivel", read_only=True, default=None
    )
    entrenador_nombre = serializers.CharField(
        source="entrenador.nombre", read_only=True, default=None
    )
    jugador_foto = serializers.CharField(
        source="jugador.foto_url", read_only=True, default=""
    )
    entrenador_foto = serializers.CharField(
        source="entrenador.foto_url", read_only=True, default=""
    )
    turno_codigo = serializers.CharField(source="turno.codigo", read_only=True)
    sede = serializers.CharField(source="pista.sede.nombre", read_only=True)
    pista_numero = serializers.IntegerField(source="pista.numero", read_only=True)

    class Meta:
        model = Asignacion
        fields = [
            "id", "semana", "dia", "turno", "turno_codigo", "pista",
            "pista_numero", "sede", "jugador", "jugador_nombre", "jugador_foto",
            "division_nivel", "entrenador", "entrenador_nombre", "entrenador_foto",
            "estado", "manual",
        ]
