from django.contrib import admin

from .models import CambioTorneo, Participante, Torneo


class ParticipanteInline(admin.TabularInline):
    model = Participante
    extra = 0
    autocomplete_fields = ["jugador"]


@admin.register(Torneo)
class TorneoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "circuito", "nivel", "fecha_inicio", "fecha_fin", "cierre_inscripcion", "estado")
    list_filter = ("circuito", "estado")
    search_fields = ("nombre", "lugar", "alias")
    filter_horizontal = ("acompanantes",)
    inlines = [ParticipanteInline]


@admin.register(CambioTorneo)
class CambioTorneoAdmin(admin.ModelAdmin):
    list_display = ("descripcion", "creado_por", "creado_at")
    list_filter = ("creado_por",)
