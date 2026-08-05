from django.contrib import admin

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


class PistaInline(admin.TabularInline):
    model = Pista
    extra = 0


@admin.register(Sede)
class SedeAdmin(admin.ModelAdmin):
    list_display = ("nombre", "es_satelite", "densidad_default", "densidad_max", "activa")
    list_editable = ("densidad_default", "densidad_max", "activa")
    inlines = [PistaInline]


@admin.register(Turno)
class TurnoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "bloque", "hora_inicio", "hora_fin", "orden")
    ordering = ("orden",)


@admin.register(Division)
class DivisionAdmin(admin.ModelAdmin):
    list_display = ("nivel", "nombre")


@admin.register(Entrenador)
class EntrenadorAdmin(admin.ModelAdmin):
    list_display = (
        "nombre", "activo", "disponible_semana", "gestiona_todos_jugadores",
        "disponibilidad_notas",
    )
    list_editable = ("activo", "disponible_semana", "gestiona_todos_jugadores")
    search_fields = ("nombre",)
    filter_horizontal = ("jugadores_gestionados",)


@admin.register(Jugador)
class JugadorAdmin(admin.ModelAdmin):
    list_display = (
        "nombre", "codigo_cliente", "categoria", "edad", "es_menor", "division",
        "entrenador_responsable", "consentimiento_rgpd", "activo",
    )
    list_filter = (
        "categoria", "division", "entrenador_responsable", "es_menor", "activo",
    )
    list_editable = ("division", "entrenador_responsable", "consentimiento_rgpd")
    search_fields = ("nombre", "codigo_cliente", "email")


@admin.register(Rencilla)
class RencillaAdmin(admin.ModelAdmin):
    list_display = ("jugador_a", "jugador_b", "activa", "motivo")
    list_filter = ("activa",)
    autocomplete_fields = ("jugador_a", "jugador_b")


@admin.register(Contrato)
class ContratoAdmin(admin.ModelAdmin):
    list_display = ("jugador", "entrenador", "activo")
    list_filter = ("activo",)
    autocomplete_fields = ("jugador", "entrenador")


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("prioridad", "estado", "autor", "titulo", "created_at")
    list_filter = ("prioridad", "estado")
    list_editable = ("estado",)
    search_fields = ("autor", "titulo", "descripcion")
    readonly_fields = ("creado_por", "created_at")
