from django.contrib import admin

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


class PistaInline(admin.TabularInline):
    model = Pista
    extra = 0
    fields = ("numero", "superficie", "activa")


@admin.register(Sede)
class SedeAdmin(admin.ModelAdmin):
    list_display = ("nombre", "es_satelite", "densidad_default", "densidad_max", "activa")
    list_editable = ("densidad_default", "densidad_max", "activa")
    inlines = [PistaInline]


@admin.register(Turno)
class TurnoAdmin(admin.ModelAdmin):
    list_display = (
        "codigo", "nombre", "bloque", "hora_inicio", "hora_fin",
        "hora_inicio_verano", "hora_fin_verano", "orden",
    )
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
    filter_horizontal = ("jugadores_gestionados", "divisiones_habilitadas")


@admin.register(Jugador)
class JugadorAdmin(admin.ModelAdmin):
    list_display = (
        "nombre", "codigo_cliente", "categoria", "escuela", "edad", "es_menor",
        "division", "entrenador_responsable", "activo",
    )
    list_filter = (
        "categoria", "escuela", "division", "entrenador_responsable", "es_menor",
        "activo",
    )
    list_editable = ("division", "entrenador_responsable", "escuela")
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


@admin.register(ResponsableJugador)
class ResponsableJugadorAdmin(admin.ModelAdmin):
    list_display = ("jugador", "entrenador", "prioridad", "porcentaje_objetivo", "activo")
    list_filter = ("activo", "entrenador")
    list_editable = ("prioridad", "porcentaje_objetivo", "activo")
    autocomplete_fields = ("jugador", "entrenador")


@admin.register(VacacionesEntrenador)
class VacacionesEntrenadorAdmin(admin.ModelAdmin):
    list_display = ("entrenador", "fecha_inicio", "fecha_fin", "motivo")
    list_filter = ("entrenador",)
    date_hierarchy = "fecha_inicio"


@admin.register(TareaMantenimiento)
class TareaMantenimientoAdmin(admin.ModelAdmin):
    list_display = ("titulo", "responsable", "fecha_limite", "estado", "created_at")
    list_filter = ("estado",)
    list_editable = ("estado",)
    search_fields = ("titulo", "descripcion", "responsable")


@admin.register(Escuela)
class EscuelaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "orden", "activa")
    list_editable = ("orden", "activa")


@admin.register(Aviso)
class AvisoAdmin(admin.ModelAdmin):
    list_display = ("tipo", "titulo", "usuario", "para_direccion", "leido", "created_at")
    list_filter = ("tipo", "leido", "para_direccion")


@admin.register(Invitado)
class InvitadoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "entrenador_solicitante", "estado", "aprobado_por", "created_at")
    list_filter = ("estado",)


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("prioridad", "estado", "autor", "titulo", "created_at")
    list_filter = ("prioridad", "estado")
    list_editable = ("estado",)
    search_fields = ("autor", "titulo", "descripcion")
    readonly_fields = ("creado_por", "created_at")
