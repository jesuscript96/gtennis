from rest_framework import serializers

from .models import (
    Aviso,
    Coach,
    Contrato,
    Division,
    Entrenador,
    Escuela,
    Feedback,
    Invitado,
    HorarioEntrenador,
    HorarioJugador,
    Jugador,
    Pista,
    PreferenciaSuperficie,
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
            "hora_inicio_verano", "hora_fin_verano", "orden", "activo",
        ]


class DivisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Division
        fields = ["id", "nivel", "nombre"]


class EntrenadorSerializer(serializers.ModelSerializer):
    divisiones_habilitadas_display = serializers.SerializerMethodField()
    turnos_display = serializers.SerializerMethodField()

    class Meta:
        model = Entrenador
        fields = [
            "id", "nombre", "activo", "disponibilidad_notas", "disponible_semana",
            "foto_url", "gestiona_todos_jugadores", "divisiones_habilitadas",
            "divisiones_habilitadas_display", "turno_manana", "turno_tarde",
            "turnos_display",
        ]

    def get_turnos_display(self, obj):
        codigos = [t.codigo for t in (obj.turno_manana, obj.turno_tarde) if t]
        return " + ".join(codigos) if codigos else "Cualquiera"

    def get_divisiones_habilitadas_display(self, obj):
        niveles = sorted(obj.divisiones_habilitadas.values_list("nivel", flat=True))
        return "Todas" if not niveles else ", ".join(f"D{n}" for n in niveles)


class CoachSerializer(serializers.ModelSerializer):
    entrenadores_display = serializers.SerializerMethodField()
    usuario_username = serializers.CharField(source="user.username", read_only=True, default=None)

    class Meta:
        model = Coach
        fields = [
            "id", "nombre", "activo", "user", "usuario_username",
            "entrenadores", "entrenadores_display",
        ]

    def get_entrenadores_display(self, obj):
        nombres = list(obj.entrenadores.values_list("nombre", flat=True))
        return ", ".join(nombres) if nombres else "—"


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


class GuardaHorarioJugador:
    """Guarda el horario semanal del alumno reemplazándolo entero.

    Lo comparten la ficha completa (dirección) y la vista de turnos (el
    entrenador): el horario es el mismo dato y tiene que guardarse igual lo
    escriba quien lo escriba. Lo que no venga en la petición es que ese día ya
    no entrena; sin la clave `horario`, el horario no se toca.
    """

    def _guardar_horario(self, instance, filas):
        if filas is None:
            return
        instance.horario.all().delete()
        for f in filas:
            HorarioJugador.objects.create(jugador=instance, **f)

    def update(self, instance, validated_data):
        filas = validated_data.pop("horario", None)
        instance = super().update(instance, validated_data)
        self._guardar_horario(instance, filas)
        return instance


class HorarioJugadorSerializer(serializers.ModelSerializer):
    """Una fila del horario semanal: qué franja de mañana y cuál de tarde."""

    class Meta:
        model = HorarioJugador
        fields = ["dia", "turno_manana", "turno_tarde"]


class JugadorSerializer(GuardaHorarioJugador, serializers.ModelSerializer):
    division_nivel = serializers.IntegerField(
        source="division.nivel", read_only=True, default=None
    )
    entrenador_nombre = serializers.CharField(
        source="entrenador_responsable.nombre", read_only=True, default=None
    )
    escuela_nombre = serializers.CharField(
        source="escuela.nombre", read_only=True, default=None
    )
    horario = HorarioJugadorSerializer(many=True, required=False)

    class Meta:
        model = Jugador
        fields = [
            "id", "nombre", "codigo_cliente", "categoria", "edad",
            "fecha_nacimiento", "es_menor", "email", "telefono",
            "consentimiento_rgpd", "division", "division_nivel",
            "entrenador_responsable", "entrenador_nombre", "escuela",
            "escuela_nombre", "foto_url", "activo", "notas",
            "fecha_alta", "fecha_baja", "turno_manana", "turno_tarde", "horario",
        ]
        # `edad` sigue siendo escribible por los alumnos antiguos de los que
        # solo consta el número, pero en cuanto hay `fecha_nacimiento` manda la
        # fecha: `Jugador.save` recalcula la edad en cada guardado.


class JugadorTurnosSerializer(GuardaHorarioJugador, serializers.ModelSerializer):
    """Vista del jugador para un ENTRENADOR.

    El entrenador no gestiona la ficha del alumno — ni datos personales, ni
    división, ni escuela, ni contactos. Lo único que declara es CUÁNDO entrena:
    su franja de mañana, la de tarde, y si algún día cambia. Por eso aquí solo
    viaja el nombre (para saber de quién se habla) y el horario.

    Las ausencias van por su propio endpoint (`/api/disponibilidades/`).
    """

    horario = HorarioJugadorSerializer(many=True, required=False)

    class Meta:
        model = Jugador
        fields = ["id", "nombre", "turno_manana", "turno_tarde", "horario"]
        read_only_fields = ["id", "nombre"]


class HorarioEntrenadorSerializer(serializers.ModelSerializer):
    class Meta:
        model = HorarioEntrenador
        fields = ["id", "dia", "manana", "tarde"]


class MiJornadaSerializer(serializers.Serializer):
    """La semana del entrenador tal y como la ve él: siete filas, una por día,
    con dos casillas. Se devuelven SIEMPRE los cinco días laborables aunque no
    haya fila guardada, para que la pantalla sea una rejilla y no una lista a
    la que hay que ir añadiendo cosas."""

    dia = serializers.IntegerField()
    nombre = serializers.CharField()
    manana = serializers.BooleanField()
    tarde = serializers.BooleanField()


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
    turno_unico_codigo = serializers.CharField(
        source="turno_unico.codigo", read_only=True, default=None
    )

    class Meta:
        model = Escuela
        fields = [
            "id", "nombre", "activa", "orden",
            "turno_unico", "turno_unico_codigo", "solo_central",
        ]


class PreferenciaSuperficieSerializer(serializers.ModelSerializer):
    jugador_nombre = serializers.CharField(source="jugador.nombre", read_only=True)
    superficie_display = serializers.CharField(
        source="get_superficie_display", read_only=True
    )

    class Meta:
        model = PreferenciaSuperficie
        fields = [
            "id", "jugador", "jugador_nombre", "superficie", "superficie_display",
            "fecha_desde", "fecha_hasta", "estricta",
        ]


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
    jugar_con_nombre = serializers.CharField(
        source="jugar_con.nombre", read_only=True, default=None
    )

    class Meta:
        model = Invitado
        fields = [
            "id", "nombre", "entrenador_solicitante", "entrenador_nombre",
            "grupo_anfitrion", "grupo_nombre", "estado", "estado_display",
            "aprobado_por", "jugador_creado", "nota",
            "division", "edad", "superficie_pref",
            "jugar_con", "jugar_con_nombre", "pareja_estricta", "created_at",
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
