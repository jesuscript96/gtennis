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
        if user.is_superadmin or (self.evaluador_id and self.evaluador_id == user.id):
            return True
        # Competición de tardes (27/10/2026): sus entrenadores de tarde y gestión
        # deportiva corrigen cualquiera (todos evalúan a todos; la validación corrige).
        from academy.permissions import evalua_tenis_solo_informes
        return bool(self.jugador.escuela_id and self.jugador.escuela.solo_informes
                    and evalua_tenis_solo_informes(user))


class CarpetaJugador(models.Model):
    """La carpeta de un jugador en la unidad compartida de informes de Drive."""

    jugador = models.OneToOneField("academy.Jugador", on_delete=models.CASCADE, related_name="carpeta_drive")
    folder_id = models.CharField(max_length=120)

    class Meta:
        verbose_name = "carpeta de Drive"
        verbose_name_plural = "carpetas de Drive"

    def __str__(self):
        return f"{self.jugador} → {self.folder_id}"


class EvaluacionFisica(models.Model):
    """La parte física del informe de un jugador, hecha por el preparador
    físico (o gestión deportiva): 11 notas del 1 al 5 y tres textos. Irá en el
    mismo PDF que la evaluación de tenis cuando se monte la validación."""

    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        TERMINADA = "TERMINADA", "Terminada"

    jugador = models.ForeignKey("academy.Jugador", on_delete=models.CASCADE, related_name="evaluaciones_fisicas")
    evaluador = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="evaluaciones_fisicas_hechas",
    )
    nombre_evaluador = models.CharField(max_length=120)
    fecha = models.DateField(default=timezone.localdate)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.BORRADOR)
    # {"fis_aceleracion": 4, …}: las 11 claves de `catalogo.CRITERIOS_FISICO`, del 1 al 5.
    puntuaciones = models.JSONField(default=dict, blank=True)
    # {"puntos_fuertes": "…", "a_mejorar": "…", "notas_fisio": "…"}
    textos = models.JSONField(default=dict, blank=True)

    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)
    terminada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-fecha", "-creada"]
        verbose_name = "evaluación física"
        verbose_name_plural = "evaluaciones físicas"

    def __str__(self):
        return f"{self.jugador} · físico · {self.fecha:%d-%m-%Y}"

    def puede_editar(self, user):
        from academy.permissions import gestion_deportiva
        return bool(gestion_deportiva(user) or (self.evaluador_id and self.evaluador_id == user.id))


class Informe(models.Model):
    """El informe trimestral de un jugador de Competición de tardes: une su
    evaluación de tenis y su evaluación física en un solo PDF que valida
    gestión deportiva (27/10/2026).

    Estados: a medias (falta alguna parte) → pendiente de validar (las dos
    terminadas) → validado, o devuelto a quien tiene que corregir. Si se
    corrige una parte de un informe ya validado, vuelve a pendiente (versión
    nueva). El siguiente trimestre empieza un informe nuevo.
    """

    class Estado(models.TextChoices):
        EN_CURSO = "EN_CURSO", "A medias"
        PENDIENTE = "PENDIENTE", "Pendiente de validar"
        DEVUELTO = "DEVUELTO", "Devuelto"
        VALIDADO = "VALIDADO", "Validado"

    jugador = models.ForeignKey("academy.Jugador", on_delete=models.CASCADE, related_name="informes")
    tenis = models.OneToOneField(Evaluacion, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="informe")
    fisica = models.OneToOneField(EvaluacionFisica, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="informe")
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.EN_CURSO)
    version = models.PositiveSmallIntegerField(default=1)

    # Devolución: qué partes («tenis», «fisico») y por qué.
    devuelto_partes = models.JSONField(default=list, blank=True)
    nota_devolucion = models.TextField(blank=True)
    devuelto_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                     blank=True, related_name="informes_devueltos")
    devuelto_en = models.DateTimeField(null=True, blank=True)

    validado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                     blank=True, related_name="informes_validados")
    validado_en = models.DateTimeField(null=True, blank=True)
    # A quién se enviará cuando el envío por correo esté activo: [{"email", "quien"}].
    destinatarios = models.JSONField(default=list, blank=True)
    # Textos de la parte física pasados al idioma del informe si no es español.
    textos_fisico_traducidos = models.JSONField(default=dict, blank=True)

    drive_file_id = models.CharField(max_length=120, blank=True)
    drive_url = models.URLField(blank=True)
    drive_carpeta = models.CharField(max_length=20, blank=True)  # «pendientes» | «validados»

    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creado"]
        verbose_name = "informe"
        verbose_name_plural = "informes"

    def __str__(self):
        return f"{self.jugador} · {self.get_estado_display()} · {self.creado:%d-%m-%Y}"

    @property
    def completo(self):
        return bool(self.tenis and self.tenis.estado == Evaluacion.Estado.TERMINADA
                    and self.fisica and self.fisica.estado == EvaluacionFisica.Estado.TERMINADA)


class FotoJugador(models.Model):
    """Foto del jugador para el informe, subida desde la app (ya reducida)."""

    jugador = models.OneToOneField("academy.Jugador", on_delete=models.CASCADE, related_name="foto_informe")
    imagen = models.BinaryField()
    tipo = models.CharField(max_length=40, default="image/jpeg")
    subida_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "foto de jugador"
        verbose_name_plural = "fotos de jugadores"


class CarpetaDrive(models.Model):
    """Carpetas ya creadas en la unidad de informes, por su ruta
    («Competición de tardes/Ana López/Pendientes de validar»)."""

    ruta = models.CharField(max_length=400, unique=True)
    folder_id = models.CharField(max_length=120)

    def __str__(self):
        return self.ruta


class RecordatorioInforme(models.Model):
    """Recordatorio ya dado, para no repetirlo: primera evaluación de un
    jugador nuevo y los de 75 y 90 días desde el último informe validado."""

    class Etapa(models.TextChoices):
        PRIMERA = "PRIMERA", "Primera evaluación"
        D75 = "D75", "75 días"
        D90 = "D90", "90 días"

    jugador = models.ForeignKey("academy.Jugador", on_delete=models.CASCADE, related_name="recordatorios_informe")
    etapa = models.CharField(max_length=8, choices=Etapa.choices)
    # Fecha de la que cuenta (alta o validación del último informe).
    referencia = models.DateField()
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["jugador", "etapa", "referencia"],
                                               name="recordatorio_informe_unico")]
