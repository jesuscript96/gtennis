from django.contrib import admin

from .models import Evaluacion


@admin.register(Evaluacion)
class EvaluacionAdmin(admin.ModelAdmin):
    list_display = ("jugador", "fecha", "nombre_evaluador", "idioma", "estado")
    list_filter = ("estado", "idioma")
    search_fields = ("jugador__nombre", "nombre_evaluador")
    autocomplete_fields = ["jugador"]
    readonly_fields = ("creada", "actualizada", "terminada_en")
