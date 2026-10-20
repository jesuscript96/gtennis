from django.conf import settings
from django.db import models
from django.utils import timezone


class Evaluacion(models.Model):
    """Un Informe de Rendimiento de un jugador, hecho por un entrenador.

    La base de datos es la fuente de la verdad: de aquí salen el `.txt` del
    formato `clave=valor`, la copia en la carpeta de Drive del jugador y, más
    adelante, el PDF para las familias. Se va guardando bloque a bloque como
    borrador para que un corte de cobertura en la pista no haga perder nada.
    """

    class Idioma(models.TextChoices):
        ES = "ES", "Español"
        EN = "EN", "Inglés"

    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        TERMINADA = "TERMINADA", "Terminada"

    jugador = models.ForeignKey("academy.Jugador", on_delete=models.CASCADE, related_name="evaluaciones")
    evaluador = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="evaluaciones_hechas",
    )
    # Se copia al crearla: el informe dice quién evaluó aunque el usuario cambie o se borre.
    nombre_evaluador = models.CharField(max_length=120)
    fecha = models.DateField(default=timezone.localdate)
    idioma = models.CharField(max_length=2, choices=Idioma.choices, default=Idioma.ES)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.BORRADOR)

    # {"drive_preparation": 4, …}: las 34 claves de `catalogo.CRITERIOS`, del 1 al 5.
    puntuaciones = models.JSONField(default=dict, blank=True)
    # {"drive": {"original": "…", "pulido": "…", "idioma": "ES"}, …, "competicion": {…}}
    # `original` es lo que escribió o dictó el entrenador; `pulido`, lo que va al informe.
    comentarios = models.JSONField(default=dict, blank=True)
    fortalezas = models.JSONField(default=list, blank=True)  # 3 frases
    mejoras = models.JSONField(default=list, blank=True)     # 3 frases

    # Copia en Drive (carpeta del jugador). Vacío hasta que se suba.
    drive_file_id = models.CharField(max_length=120, blank=True)
    drive_url = models.URLField(blank=True)

    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)
    terminada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-fecha", "-creada"]
        verbose_name = "evaluación"
        verbose_name_plural = "evaluaciones"

    def __str__(self):
        return f"{self.jugador} · {self.fecha:%d-%m-%Y} · {self.nombre_evaluador}"

    def puede_editar(self, user):
        return bool(user.is_superadmin or (self.evaluador_id and self.evaluador_id == user.id))


class CarpetaJugador(models.Model):
    """La carpeta de un jugador en la unidad compartida de informes de Drive."""

    jugador = models.OneToOneField("academy.Jugador", on_delete=models.CASCADE, related_name="carpeta_drive")
    folder_id = models.CharField(max_length=120)

    class Meta:
        verbose_name = "carpeta de Drive"
        verbose_name_plural = "carpetas de Drive"

    def __str__(self):
        return f"{self.jugador} → {self.folder_id}"
