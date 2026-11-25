from django.contrib import admin

from .models import CambioTorneo, CategoriaJugador, CorreoTorneos, NormasTorneos, Participante, Torneo


class ParticipanteInline(admin.TabularInline):
    model = Participante
    extra = 0
    autocomplete_fields = ["jugador"]


@admin.register(Torneo)
class TorneoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "circuito", "nivel", "qualy_inicio", "fecha_inicio", "fecha_fin",
                    "solo_fines_semana", "cierre_inscripcion", "estado")
    list_filter = ("circuito", "estado")
    search_fields = ("nombre", "lugar", "alias")
    filter_horizontal = ("acompanantes",)
    inlines = [ParticipanteInline]


@admin.register(CategoriaJugador)
class CategoriaJugadorAdmin(admin.ModelAdmin):
    list_display = ("jugador", "categoria")
    autocomplete_fields = ["jugador"]


@admin.register(CambioTorneo)
class CambioTorneoAdmin(admin.ModelAdmin):
    list_display = ("descripcion", "creado_por", "creado_at")
    list_filter = ("creado_por",)


@admin.register(CorreoTorneos)
class CorreoTorneosAdmin(admin.ModelAdmin):
    list_display = ("jugador", "mes", "estado", "validado_por", "enviado_en", "envio_error")
    list_filter = ("mes", "estado")
    search_fields = ("jugador__nombre",)
    autocomplete_fields = ["jugador"]


@admin.register(NormasTorneos)
class NormasTorneosAdmin(admin.ModelAdmin):
    list_display = ("__str__", "actualizado_por", "actualizado_en")
