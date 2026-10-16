from rest_framework import serializers

from academy.models import Entrenador

from .models import Participante, Torneo


class ParticipanteSerializer(serializers.ModelSerializer):
    certeza_display = serializers.CharField(source="get_certeza_display", read_only=True)
    # Opcional: si viene un jugador de la academia, el nombre se copia de su ficha.
    nombre = serializers.CharField(required=False, allow_blank=True, max_length=120)

    class Meta:
        model = Participante
        fields = ["id", "torneo", "jugador", "nombre", "certeza", "certeza_display",
                  "entrenador_ref", "detalle"]
        # La restricción (torneo, nombre) se comprueba abajo, una vez resuelto el
        # nombre a partir de la ficha; el validador automático obligaría a mandarlo.
        validators = []

    def validate(self, data):
        # Si se manda un jugador de la academia sin nombre, el nombre es el suyo.
        jugador = data.get("jugador")
        if not data.get("nombre") and jugador is not None:
            data["nombre"] = jugador.nombre
        if not data.get("nombre") and not (self.instance and self.instance.nombre):
            raise serializers.ValidationError({"nombre": "Indica el jugador o escribe su nombre."})
        torneo = data.get("torneo") or (self.instance and self.instance.torneo)
        nombre = data.get("nombre") or (self.instance and self.instance.nombre)
        repetido = Participante.objects.filter(torneo=torneo, nombre=nombre)
        if self.instance:
            repetido = repetido.exclude(pk=self.instance.pk)
        if repetido.exists():
            raise serializers.ValidationError({"nombre": f"{nombre} ya está apuntado a este torneo."})
        return data


class EntrenadorMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Entrenador
        fields = ["id", "nombre"]


class TorneoSerializer(serializers.ModelSerializer):
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    participantes = ParticipanteSerializer(many=True, read_only=True)
    acompanantes_detalle = EntrenadorMiniSerializer(source="acompanantes", many=True, read_only=True)
    n_jugadores = serializers.SerializerMethodField()
    creado_por_nombre = serializers.SerializerMethodField()

    class Meta:
        model = Torneo
        fields = [
            "id", "nombre", "circuito", "nivel", "lugar", "fecha_inicio", "fecha_fin",
            "cierre_inscripcion", "qualy_inicio", "qualy_fin", "solo_fines_semana", "estado", "estado_display", "acompanantes",
            "acompanantes_detalle", "acompanante_nota", "notas", "fuente", "alias",
            "participantes", "n_jugadores", "creado_por", "creado_por_nombre",
            "created_at", "updated_at",
        ]
        read_only_fields = ["creado_por", "created_at", "updated_at"]

    def get_n_jugadores(self, obj):
        return obj.participantes.count() if not hasattr(obj, "_n_jug") else obj._n_jug

    def get_creado_por_nombre(self, obj):
        u = obj.creado_por
        if u is None:
            return ""
        return u.get_full_name() or u.username

    def validate(self, data):
        ini = data.get("fecha_inicio") or getattr(self.instance, "fecha_inicio", None)
        fin = data.get("fecha_fin") or getattr(self.instance, "fecha_fin", None)
        if ini and fin and fin < ini:
            raise serializers.ValidationError({"fecha_fin": "El torneo no puede acabar antes de empezar."})
        def campo(k):
            return data[k] if k in data else getattr(self.instance, k, None)
        q_ini, q_fin = campo("qualy_inicio"), campo("qualy_fin")
        if q_ini and not q_fin:
            q_fin = data["qualy_fin"] = ini
        if q_fin and not q_ini:
            raise serializers.ValidationError({"qualy_inicio": "Indica también cuándo empieza la previa."})
        if q_ini and q_fin and q_fin < q_ini:
            raise serializers.ValidationError({"qualy_fin": "La previa no puede acabar antes de empezar."})
        if q_fin and ini and q_fin > ini:
            raise serializers.ValidationError({"qualy_fin": "La previa tiene que acabar antes de que empiece el cuadro final (o ese mismo día)."})
        cierre = data.get("cierre_inscripcion")
        if cierre and ini and cierre > fin:
            raise serializers.ValidationError(
                {"cierre_inscripcion": "El cierre de inscripción no puede ser posterior al torneo."})
        return data


class TorneoListaSerializer(TorneoSerializer):
    """Lista: sin la lista completa de participantes, solo los nombres."""
    jugadores = serializers.SerializerMethodField()

    class Meta(TorneoSerializer.Meta):
        fields = [f for f in TorneoSerializer.Meta.fields if f != "participantes"] + ["jugadores"]

    def get_jugadores(self, obj):
        return [{"id": p.id, "nombre": p.nombre, "jugador": p.jugador_id, "certeza": p.certeza}
                for p in obj.participantes.all()]
