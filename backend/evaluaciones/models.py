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

    # {"drive_preparation": 4, …}: las 34 claves de `catalogo.CRITERIOS`, del 1 a `escala`.
    puntuaciones = models.JSONField(default=dict, blank=True)
    # Nota máxima de cada criterio (12/11/2026): Alto rendimiento puntúa del
    # 1 al 10; Competición de tardes y lo anterior, del 1 al 5. db_default:
    # durante el despliegue el código anterior crea evaluaciones sin esta columna.
    escala = models.PositiveSmallIntegerField(default=5, db_default=5)
    # {"drive": {"original": "…", "pulido": "…", "idioma": "ES"}, …, "competicion": {…}}
    # `original` es lo que escribió o dictó el entrenador; `pulido`, lo que va al informe.
    comentarios = models.JSONField(default=dict, blank=True)
    fortalezas = models.JSONField(default=list, blank=True)  # 3 frases
    mejoras = models.JSONField(default=list, blank=True)     # 3 frases
    # Lo que escribió el entrenador (02/11/2026); `fortalezas` y `mejoras` son
    # esas mismas frases pasadas a limpio por Claude.
    fortalezas_original = models.JSONField(default=list, blank=True)
    mejoras_original = models.JSONField(default=list, blank=True)
    # Los textos ya traducidos para el PDF de la familia, si no es en español
    # (`traduccion.py`): {"firma", "textos"}. Se rehace si cambia algo.
    traduccion = models.JSONField(default=dict, blank=True)

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

    def _informe_cerrado(self):
        inf = getattr(self, "informe", None)
        return inf is not None and inf.estado == Informe.Estado.VALIDADO

    def puede_editar(self, user):
        """Quién cambia esta evaluación (10/11/2026): su autor, quien coordina
        Competición de tardes y quien valida (corrige antes de aprobar). Un
        informe ya aprobado no se toca: primero se reabre."""
        from academy.permissions import coordina_informes, es_direccion, evalua_tenis_solo_informes
        from .informes import puede_validar

        if self._informe_cerrado():
            return False
        if es_direccion(user) or (self.evaluador_id and self.evaluador_id == user.id):
            return True
        # Quien valida ese informe (en Alto rendimiento, solo dirección).
        inf = getattr(self, "informe", None)
        if inf is not None and puede_validar(user, inf):
            return True
        # Competición de tardes: «todos evalúan a todos» (29/10/2026). Quien
        # coordina y el equipo de tenis siguen o corrigen la parte de tenis de
        # otro mientras el informe no esté aprobado (p. ej. si el coordinador
        # reasigna al jugador con la evaluación a medias). Borrarla, no.
        return bool(self.jugador.escuela_id and self.jugador.escuela.solo_informes
                    and (coordina_informes(user) or evalua_tenis_solo_informes(user)))

    def puede_borrar(self, user):
        """Solo el autor y quien coordina; en un informe aprobado, nadie."""
        from academy.permissions import coordina_informes, es_direccion
        if self._informe_cerrado():
            return False
        de_tardes = bool(self.jugador.escuela_id and self.jugador.escuela.solo_informes)
        return bool(es_direccion(user) or (self.evaluador_id and self.evaluador_id == user.id)
                    or (de_tardes and coordina_informes(user)))


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
    # Como en `Evaluacion.traduccion`: los textos en el idioma de la familia.
    traduccion = models.JSONField(default=dict, blank=True)

    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)
    terminada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-fecha", "-creada"]
        verbose_name = "evaluación física"
        verbose_name_plural = "evaluaciones físicas"

    def __str__(self):
        return f"{self.jugador} · físico · {self.fecha:%d-%m-%Y}"

    def _informe_cerrado(self):
        inf = getattr(self, "informe", None)
        return inf is not None and inf.estado == Informe.Estado.VALIDADO

    def puede_editar(self, user):
        """Su autor, dirección y quien valida (abre y corrige las dos partes,
        decisión 11). Un informe aprobado no se toca: primero se reabre."""
        from academy.permissions import es_direccion, valida_informes
        if self._informe_cerrado():
            return False
        return bool(es_direccion(user) or valida_informes(user)
                    or (self.evaluador_id and self.evaluador_id == user.id))

    def puede_borrar(self, user):
        from academy.permissions import coordina_informes, es_direccion
        if self._informe_cerrado():
            return False
        return bool(es_direccion(user) or coordina_informes(user)
                    or (self.evaluador_id and self.evaluador_id == user.id))


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
    # A quién se envía por correo: [{"email", "quien"}].
    destinatarios = models.JSONField(default=list, blank=True)
    # Envío a la familia (10/11/2026, decisión 13).
    enviado_en = models.DateTimeField(null=True, blank=True)
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name="informes_enviados")
    # db_default: la versión anterior crea informes sin esta columna (despliegue).
    envio_error = models.CharField(max_length=300, blank=True, default="", db_default="")
    # Textos de la parte física pasados al idioma del informe si no es español.
    # Sin uso desde el 02/11/2026: la traducción va en `EvaluacionFisica.traduccion`.
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
    def circuito(self):
        """«tardes» (tenis + físico) o «alto_rendimiento» (solo tenis). Desde el
        10/11/2026 los dos pasan por la validación (decisión 12)."""
        j = self.jugador
        return "tardes" if (j.escuela_id and j.escuela.solo_informes) else "alto_rendimiento"

    @property
    def completo(self):
        tenis = bool(self.tenis and self.tenis.estado == Evaluacion.Estado.TERMINADA)
        if self.circuito == "alto_rendimiento":
            return tenis
        return bool(tenis and self.fisica and self.fisica.estado == EvaluacionFisica.Estado.TERMINADA)


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


class AsignacionInforme(models.Model):
    """Qué entrenador de tenis hace los informes de un jugador de Competición
    de tardes. Lo reparte el coordinador (29/10/2026): al asignado le llegan
    los recordatorios y lo ve en «Mis jugadores»; los demás entrenadores de
    tarde pueden evaluarle igual."""

    jugador = models.OneToOneField("academy.Jugador", on_delete=models.CASCADE, related_name="asignacion_informe")
    evaluador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                  related_name="informes_asignados")
    asignado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+")
    actualizado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.jugador} → {self.evaluador}"


class MiembroTardes(models.Model):
    """Quién hace los informes de Competición de tardes, y de qué parte. Lo da
    de alta y de baja el coordinador desde la app (02/11/2026); antes era una
    lista fija en el código."""

    class Funcion(models.TextChoices):
        TENIS = "TENIS", "Tenis"
        FISICO = "FISICO", "Preparación física"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tardes")
    funcion = models.CharField(max_length=8, choices=Funcion.choices)
    anadido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["usuario", "funcion"], name="miembro_tardes_unico")]

    def __str__(self):
        return f"{self.usuario} · {self.get_funcion_display()}"


class DatosInforme(models.Model):
    """Lo que el informe necesita de la familia y no está en la ficha: el
    idioma del PDF que se le envía y un segundo correo (02/11/2026). El
    primero es `Jugador.email`."""

    class Idioma(models.TextChoices):
        ES = "ES", "Español"
        EN = "EN", "Inglés"

    jugador = models.OneToOneField("academy.Jugador", on_delete=models.CASCADE, related_name="datos_informe")
    idioma = models.CharField(max_length=2, choices=Idioma.choices, default=Idioma.ES)
    quien_1 = models.CharField(max_length=40, blank=True)
    email_2 = models.EmailField(blank=True)
    quien_2 = models.CharField(max_length=40, blank=True)

    def __str__(self):
        return f"{self.jugador} · {self.idioma}"
