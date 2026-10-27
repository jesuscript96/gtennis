from django.contrib import admin

from .models import CarpetaDrive, CarpetaJugador, Evaluacion, EvaluacionFisica, FotoJugador, Informe, RecordatorioInforme


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


@admin.register(Informe)
class InformeAdmin(admin.ModelAdmin):
    list_display = ("jugador", "estado", "version", "validado_en", "creado")
    list_filter = ("estado",)
    search_fields = ("jugador__nombre",)
    raw_id_fields = ("jugador", "tenis", "fisica", "devuelto_por", "validado_por")
    readonly_fields = ("creado", "actualizado")


@admin.register(FotoJugador)
class FotoJugadorAdmin(admin.ModelAdmin):
    list_display = ("jugador", "subida_por", "actualizada")
    exclude = ("imagen",)
    raw_id_fields = ("jugador", "subida_por")


@admin.register(CarpetaDrive)
class CarpetaDriveAdmin(admin.ModelAdmin):
    list_display = ("ruta", "folder_id")


@admin.register(RecordatorioInforme)
class RecordatorioInformeAdmin(admin.ModelAdmin):
    list_display = ("jugador", "etapa", "referencia")
    list_filter = ("etapa",)
