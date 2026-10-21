from rest_framework import serializers

from . import catalogo
from .models import Evaluacion, EvaluacionFisica


class EvaluacionSerializer(serializers.ModelSerializer):
    jugador_nombre = serializers.CharField(source="jugador.nombre", read_only=True)
    puntuados = serializers.SerializerMethodField()
    puede_editar = serializers.SerializerMethodField()

    class Meta:
        model = Evaluacion
        fields = ["id", "jugador", "jugador_nombre", "evaluador", "nombre_evaluador", "fecha", "idioma",
                  "estado", "puntuaciones", "comentarios", "fortalezas", "mejoras", "puntuados",
                  "puede_editar", "drive_url", "creada", "actualizada", "terminada_en"]
        read_only_fields = ["evaluador", "nombre_evaluador", "estado", "drive_url", "creada",
                            "actualizada", "terminada_en"]

    def get_puntuados(self, ev):
        return sum(1 for k in catalogo.CRITERIOS if k in ev.puntuaciones)

    def get_puede_editar(self, ev):
        req = self.context.get("request")
        return bool(req and ev.puede_editar(req.user))

    def validate_jugador(self, jugador):
        if self.instance and self.instance.jugador_id != jugador.id:
            raise serializers.ValidationError("Una evaluación no se cambia de jugador.")
        return jugador

    def validate_puntuaciones(self, valor):
        if not isinstance(valor, dict):
            raise serializers.ValidationError("Formato no válido.")
        for clave, nota in valor.items():
            if clave not in catalogo.CRITERIOS:
                raise serializers.ValidationError(f"Criterio desconocido: {clave}.")
            if not isinstance(nota, int) or isinstance(nota, bool) or not 1 <= nota <= 5:
                raise serializers.ValidationError(f"{clave}: la nota va del 1 al 5.")
        return valor

    def validate_comentarios(self, valor):
        if not isinstance(valor, dict):
            raise serializers.ValidationError("Formato no válido.")
        for clave, com in valor.items():
            if clave not in catalogo.POR_CLAVE and clave != catalogo.COMPETICION:
                raise serializers.ValidationError(f"Bloque desconocido: {clave}.")
            if not isinstance(com, dict) or not all(isinstance(com.get(k, ""), str) for k in ("original", "pulido")):
                raise serializers.ValidationError(f"{clave}: formato no válido.")
        return valor

    def _tres_frases(self, valor):
        if not isinstance(valor, list) or len(valor) > 3 or not all(isinstance(f, str) for f in valor):
            raise serializers.ValidationError("Van hasta tres frases.")
        return [f.strip() for f in valor]

    validate_fortalezas = _tres_frases
    validate_mejoras = _tres_frases

    def update(self, instance, data):
        # Cada paso del asistente manda solo su bloque: se mezcla con lo que ya había.
        if "puntuaciones" in data:
            data["puntuaciones"] = {**instance.puntuaciones, **data["puntuaciones"]}
        if "comentarios" in data:
            nuevos = {k: {**(instance.comentarios.get(k) or {}), **v} for k, v in data["comentarios"].items()}
            data["comentarios"] = {**instance.comentarios, **nuevos}
        return super().update(instance, data)


class EvaluacionFisicaSerializer(serializers.ModelSerializer):
    jugador_nombre = serializers.CharField(source="jugador.nombre", read_only=True)
    puntuados = serializers.SerializerMethodField()
    puede_editar = serializers.SerializerMethodField()

    class Meta:
        model = EvaluacionFisica
        fields = ["id", "jugador", "jugador_nombre", "evaluador", "nombre_evaluador", "fecha", "estado",
                  "puntuaciones", "textos", "puntuados", "puede_editar", "creada", "actualizada", "terminada_en"]
        read_only_fields = ["evaluador", "nombre_evaluador", "estado", "creada", "actualizada", "terminada_en"]

    def get_puntuados(self, ev):
        return sum(1 for k in catalogo.CRITERIOS_FISICO if k in ev.puntuaciones)

    def get_puede_editar(self, ev):
        req = self.context.get("request")
        return bool(req and ev.puede_editar(req.user))

    def validate_jugador(self, jugador):
        if self.instance and self.instance.jugador_id != jugador.id:
            raise serializers.ValidationError("Una evaluación no se cambia de jugador.")
        return jugador

    def validate_puntuaciones(self, valor):
        if not isinstance(valor, dict):
            raise serializers.ValidationError("Formato no válido.")
        for clave, nota in valor.items():
            if clave not in catalogo.CRITERIOS_FISICO:
                raise serializers.ValidationError(f"Criterio desconocido: {clave}.")
            if not isinstance(nota, int) or isinstance(nota, bool) or not 1 <= nota <= 5:
                raise serializers.ValidationError(f"{clave}: la nota va del 1 al 5.")
        return valor

    def validate_textos(self, valor):
        claves = {k for k, _ in catalogo.TEXTOS_FISICO}
        if not isinstance(valor, dict) or any(k not in claves or not isinstance(v, str) for k, v in valor.items()):
            raise serializers.ValidationError("Formato no válido.")
        return {k: v.strip() for k, v in valor.items()}

    def update(self, instance, data):
        # Cada paso manda solo lo suyo: se mezcla con lo que ya había.
        if "puntuaciones" in data:
            data["puntuaciones"] = {**instance.puntuaciones, **data["puntuaciones"]}
        if "textos" in data:
            data["textos"] = {**instance.textos, **data["textos"]}
        return super().update(instance, data)
