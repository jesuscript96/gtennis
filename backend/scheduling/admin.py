from django.contrib import admin

from .models import Asignacion, ConfiguracionMotor, Disponibilidad, Semana


@admin.register(ConfiguracionMotor)
class ConfiguracionMotorAdmin(admin.ModelAdmin):
    list_display = (
        "peso_asignacion", "peso_satelite", "peso_repeticion",
        "max_dias_misma_pista", "aplicar_vecindad", "time_limit_s",
    )

    def has_add_permission(self, request):
        return not ConfiguracionMotor.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Semana)
class SemanaAdmin(admin.ModelAdmin):
    list_display = ("fecha_inicio", "estado", "generado_at", "publicado_at")
    list_filter = ("estado",)


@admin.register(Disponibilidad)
class DisponibilidadAdmin(admin.ModelAdmin):
    list_display = ("semana", "jugador", "dia", "turno", "estado", "subtipo")
    list_filter = ("semana", "dia", "estado")
    autocomplete_fields = ("jugador",)


@admin.register(Asignacion)
class AsignacionAdmin(admin.ModelAdmin):
    list_display = (
        "semana", "dia", "turno", "pista", "jugador", "entrenador",
        "estado", "manual",
    )
    list_filter = ("semana", "dia", "turno", "pista__sede", "estado", "manual")
    autocomplete_fields = ("jugador",)
