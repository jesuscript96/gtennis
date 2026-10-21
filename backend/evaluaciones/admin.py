from django.contrib import admin

from .models import CarpetaJugador, Evaluacion, EvaluacionFisica


@admin.register(Evaluacion)
class EvaluacionAdmin(admin.ModelAdmin):
    list_display = ("jugador", "fecha", "nombre_evaluador", "idioma", "estado")
    list_filter = ("estado", "idioma")
    search_fields = ("jugador__nombre", "nombre_evaluador")
    autocomplete_fields = ["jugador"]
    readonly_fields = ("creada", "actualizada", "terminada_en")


@admin.register(CarpetaJugador)
class CarpetaJugadorAdmin(admin.ModelAdmin):
    list_display = ("jugador", "folder_id")
    search_fields = ("jugador__nombre", "folder_id")


@admin.register(EvaluacionFisica)
class EvaluacionFisicaAdmin(admin.ModelAdmin):
    list_display = ("jugador", "fecha", "nombre_evaluador", "estado")
    list_filter = ("estado",)
    search_fields = ("jugador__nombre", "nombre_evaluador")
    autocomplete_fields = ["jugador"]
    readonly_fields = ("creada", "actualizada", "terminada_en")
