from rest_framework import serializers

from .models import (
    AusenciaJugador,
    Asignacion,
    ConfiguracionMotor,
    Disponibilidad,
    DisponibilidadEntrenador,
    Semana,
)


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
            "subtipo_display", "nota", "tardia",
        ]
        read_only_fields = ["tardia"]


class DisponibilidadEntrenadorSerializer(serializers.ModelSerializer):
    entrenador_nombre = serializers.CharField(
        source="entrenador.nombre", read_only=True
    )
    estado_display = serializers.CharField(
        source="get_estado_display", read_only=True
    )

    class Meta:
        model = DisponibilidadEntrenador
        fields = [
            "id", "semana", "entrenador", "entrenador_nombre", "dia", "estado",
            "estado_display", "hora_desde", "hora_hasta", "nota",
        ]
        # El entrenador se fija según el usuario (coach) salvo Super Admin.
        extra_kwargs = {"entrenador": {"required": False}}


class ConfiguracionMotorSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfiguracionMotor
        fields = [
            "peso_asignacion", "peso_satelite", "peso_central",
            "peso_repeticion", "peso_equilibrio_franjas", "peso_resina", "peso_pista_division", "peso_division_entrenador",
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
    pista_superficie = serializers.CharField(source="pista.superficie", read_only=True)
    # Falta declarada para esa franja después de colocarle: sale tachado, sin
    # mover a nadie (01/10/2026). Nulo si viene.
    falta = serializers.SerializerMethodField()

    class Meta:
        model = Asignacion
        fields = [
            "id", "semana", "dia", "turno", "turno_codigo", "pista",
            "pista_numero", "pista_superficie", "sede", "jugador", "jugador_nombre",
            "jugador_foto", "division_nivel", "entrenador", "entrenador_nombre",
            "entrenador_foto", "estado", "manual", "falta",
        ]

    def get_falta(self, obj):
        return falta_de(obj, self.context.setdefault("_faltas", {}))


def falta_de(asignacion, cache):
    """La falta que tapa esta asignación, o None. `cache` guarda las faltas de
    cada día para no consultarlas fila a fila."""
    from datetime import timedelta

    from engine.service import _overrides, override_efectivo

    from .models import ESTADOS_EXCLUYENTES

    clave = (asignacion.semana_id, asignacion.dia)
    if clave not in cache:
        semana = asignacion.semana
        cache[clave] = (_overrides(semana, asignacion.dia),
                        semana.fecha_inicio + timedelta(days=asignacion.dia))
    overrides, fecha = cache[clave]
    d = override_efectivo(overrides, asignacion.jugador_id, asignacion.turno, fecha)
    if d is None or d.estado not in ESTADOS_EXCLUYENTES:
        return None
    return {
        "estado": d.estado,
        "motivo": d.get_subtipo_display() if d.subtipo else d.get_estado_display(),
        "tardia": d.tardia,
    }


class AusenciaJugadorSerializer(serializers.ModelSerializer):
    jugador_nombre = serializers.CharField(source="jugador.nombre", read_only=True)

    class Meta:
        model = AusenciaJugador
        fields = [
            "id", "jugador", "jugador_nombre", "fecha_inicio", "fecha_fin",
            "ambito", "hora_desde", "hora_hasta", "estado", "subtipo", "nota",
            "declarada_por", "created_at", "tardia",
        ]
        read_only_fields = ["declarada_por", "created_at", "tardia"]

    def validate(self, data):
        ini = data.get("fecha_inicio") or getattr(self.instance, "fecha_inicio", None)
        fin = data.get("fecha_fin") or getattr(self.instance, "fecha_fin", None)
        if ini and fin and fin < ini:
            raise serializers.ValidationError(
                {"fecha_fin": "La vuelta no puede ser anterior a la ida."}
            )
        hd = data.get("hora_desde"); hh = data.get("hora_hasta")
        if (hd or hh) and ini != fin:
            raise serializers.ValidationError(
                {"hora_desde": "Las horas solo valen para una ausencia de un "
                               "único día. Para un rango, usa el ámbito."}
            )
        if hd and hh and hh <= hd:
            raise serializers.ValidationError(
                {"hora_hasta": "La hora de fin debe ser posterior a la de inicio."}
            )
        return data
