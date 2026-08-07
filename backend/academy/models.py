from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Sede(models.Model):
    """Venue. Central is the base; the rest are satellite overflow venues
    (Sta. Bárbara, Bétera, Liria)."""

    nombre = models.CharField(max_length=80, unique=True)
    es_satelite = models.BooleanField(default=False)
    # Auto-pairing fills 2 players/court by default; a court can be pushed
    # manually up to `densidad_max` (4) to force-add a "no disponible" player.
    densidad_default = models.PositiveSmallIntegerField(default=2)
    densidad_max = models.PositiveSmallIntegerField(default=4)
    # Order in which satellites receive overflow.
    orden_desbordamiento = models.PositiveSmallIntegerField(default=0)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Sede"
        verbose_name_plural = "Sedes"
        ordering = ["es_satelite", "orden_desbordamiento", "nombre"]

    def __str__(self):
        return self.nombre


class Pista(models.Model):
    class Superficie(models.TextChoices):
        TIERRA = "TIERRA", "Tierra batida"
        RESINA = "RESINA", "Resina"

    sede = models.ForeignKey(Sede, on_delete=models.CASCADE, related_name="pistas")
    numero = models.PositiveSmallIntegerField()
    superficie = models.CharField(
        max_length=10, choices=Superficie.choices, default=Superficie.RESINA
    )
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Pista"
        verbose_name_plural = "Pistas"
        unique_together = ("sede", "numero")
        ordering = ["sede", "numero"]

    def __str__(self):
        return f"{self.sede.nombre} · Pista {self.numero}"


class Turno(models.Model):
    """The 4 fixed daily shifts (PRD §02)."""

    class Bloque(models.TextChoices):
        MANANA = "MANANA", "Mañana"
        TARDE = "TARDE", "Tarde"

    codigo = models.CharField(max_length=4, unique=True)  # M1, M2, T1, T2
    nombre = models.CharField(max_length=40)
    bloque = models.CharField(max_length=10, choices=Bloque.choices)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    # Horario de temporada de verano (julio y agosto). Si está vacío se usa el
    # horario normal todo el año.
    hora_inicio_verano = models.TimeField(null=True, blank=True)
    hora_fin_verano = models.TimeField(null=True, blank=True)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Turno"
        verbose_name_plural = "Turnos"
        ordering = ["orden"]

    @staticmethod
    def es_temporada_verano(fecha):
        return fecha is not None and fecha.month in (7, 8)

    def horas(self, fecha=None):
        """(hora_inicio, hora_fin) efectivas para una fecha: horario de verano
        en julio/agosto si está definido, si no el horario normal."""
        from datetime import date

        fecha = fecha or date.today()
        if self.es_temporada_verano(fecha) and self.hora_inicio_verano and self.hora_fin_verano:
            return self.hora_inicio_verano, self.hora_fin_verano
        return self.hora_inicio, self.hora_fin

    def __str__(self):
        return f"{self.codigo} ({self.hora_inicio:%H:%M}-{self.hora_fin:%H:%M})"


class Division(models.Model):
    """Competitive level. Neighbour rule (PRD §4.1): a player of division N may
    only pair with divisions N-1, N, N+1."""

    nivel = models.PositiveSmallIntegerField(unique=True)
    nombre = models.CharField(max_length=40, blank=True)

    class Meta:
        verbose_name = "División"
        verbose_name_plural = "Divisiones"
        ordering = ["nivel"]

    def __str__(self):
        return self.nombre or f"División {self.nivel}"


class Entrenador(models.Model):
    """Active user with a cluster of ~7-8 players."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entrenador",
    )
    nombre = models.CharField(max_length=120)
    activo = models.BooleanField(default=True)
    # Free-text availability until structured via Sésame (e.g. "M, J, V y S").
    disponibilidad_notas = models.CharField(max_length=200, blank=True)
    # Manual fallback button (PRD §06): overrides Sésame for the current week.
    disponible_semana = models.BooleanField(default=True)
    # Photo in EU object storage (S3-compatible); signed-URL ref.
    foto_url = models.URLField(blank=True)

    # --- Scope de gestión (declarar ausencias) -----------------------------
    # Si True, este entrenador puede gestionar a TODOS los jugadores activos
    # (caso de Sergio hoy). Si False, solo los de `jugadores_gestionados`.
    gestiona_todos_jugadores = models.BooleanField(
        default=False,
        help_text="Acceso a declarar ausencias de todos los jugadores.",
    )
    # Subconjunto explícito de jugadores que este entrenador puede gestionar
    # cuando no tiene acceso total. Independiente del `cluster` de emparejamiento
    # (entrenador_responsable), que es una relación distinta del motor.
    jugadores_gestionados = models.ManyToManyField(
        "Jugador",
        blank=True,
        related_name="entrenadores_gestores",
    )
    # Divisiones que este entrenador está capacitado para entrenar (#3).
    # Vacío = habilitado para todas las divisiones.
    divisiones_habilitadas = models.ManyToManyField(
        "Division",
        blank=True,
        related_name="entrenadores",
    )

    class Meta:
        verbose_name = "Entrenador"
        verbose_name_plural = "Entrenadores"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

    def niveles_habilitados(self):
        """Set de niveles de división que puede entrenar; None = todas."""
        niveles = set(self.divisiones_habilitadas.values_list("nivel", flat=True))
        return niveles or None

    def puede_entrenar_niveles(self, niveles):
        """¿Cubre este entrenador todos los niveles dados? (None en la pista =
        jugador sin clasificar, no restringe)."""
        habil = self.niveles_habilitados()
        if habil is None:
            return True
        return all(n is None or n in habil for n in niveles)

    def jugadores_permitidos(self):
        """Queryset de jugadores activos que este entrenador puede gestionar."""
        activos = Jugador.objects.filter(activo=True)
        if self.gestiona_todos_jugadores:
            return activos
        return activos.filter(entrenadores_gestores=self)

    def puede_gestionar(self, jugador):
        """¿Puede este entrenador declarar ausencias de `jugador`?"""
        if self.gestiona_todos_jugadores:
            return True
        return self.jugadores_gestionados.filter(pk=jugador.pk).exists()


class Jugador(models.Model):
    """Passive data entity — never logs in (PRD §01)."""

    class Categoria(models.TextChoices):
        ALTO_RENDIMIENTO = "ALTO_RENDIMIENTO", "Alto rendimiento"
        PROFESIONAL = "PROFESIONAL", "Profesional nacional"

    nombre = models.CharField(max_length=120)
    # Código de cliente del software de gestión de la escuela. Clave estable
    # para reconciliar contra los Excel de alumnos (fuente de la verdad).
    codigo_cliente = models.PositiveIntegerField(
        null=True, blank=True, unique=True, db_index=True
    )
    # Escuela a la que pertenece (Alto Rendimiento / Junior Program, #6).
    escuela = models.ForeignKey(
        "Escuela", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="jugadores",
    )
    categoria = models.CharField(
        max_length=20, choices=Categoria.choices, blank=True
    )
    edad = models.PositiveSmallIntegerField(null=True, blank=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    es_menor = models.BooleanField(default=False)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=60, blank=True)
    # GDPR Art. 9 + minors: explicit consent required to store health states.
    consentimiento_rgpd = models.BooleanField(default=False)
    division = models.ForeignKey(
        Division, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="jugadores",
    )
    entrenador_responsable = models.ForeignKey(
        Entrenador, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="cluster",
    )
    # Photo lives in EU object storage (S3-compatible); we keep a signed-URL ref.
    foto_url = models.URLField(blank=True)
    activo = models.BooleanField(default=True)
    notas = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Jugador"
        verbose_name_plural = "Jugadores"
        ordering = ["nombre"]

    def save(self, *args, **kwargs):
        # La fecha de nacimiento manda: si está, recalcula la edad actual.
        if self.fecha_nacimiento is not None:
            from datetime import date

            today = date.today()
            self.edad = (
                today.year
                - self.fecha_nacimiento.year
                - (
                    (today.month, today.day)
                    < (self.fecha_nacimiento.month, self.fecha_nacimiento.day)
                )
            )
        if self.edad is not None:
            self.es_menor = self.edad < 18
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre


class ResponsableJugador(models.Model):
    """Relación ponderada jugador–entrenador (#2/#12). Un jugador puede tener
    varios entrenadores responsables con una prioridad y un % objetivo de
    entrenos deseado con cada uno. Complementa (y prevalece sobre) el campo
    simple `Jugador.entrenador_responsable`."""

    jugador = models.ForeignKey(
        Jugador, on_delete=models.CASCADE, related_name="responsables"
    )
    entrenador = models.ForeignKey(
        Entrenador, on_delete=models.CASCADE, related_name="jugadores_responsable"
    )
    # 1 = principal; números mayores = menor prioridad.
    prioridad = models.PositiveSmallIntegerField(default=1)
    # % de entrenos que se desea que este jugador haga con este entrenador.
    porcentaje_objetivo = models.PositiveSmallIntegerField(
        default=0, help_text="0-100. La suma por jugador no debería pasar de 100."
    )
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Responsable de jugador"
        verbose_name_plural = "Responsables de jugador"
        unique_together = ("jugador", "entrenador")
        ordering = ["jugador", "prioridad"]

    def clean(self):
        if self.porcentaje_objetivo > 100:
            raise ValidationError("El porcentaje no puede superar 100.")

    def __str__(self):
        return f"{self.jugador} → {self.entrenador} (P{self.prioridad}, {self.porcentaje_objetivo}%)"


class Rencilla(models.Model):
    """Explicit cross-veto (PRD §4.2). Hard constraint: these two players are
    never placed on the same court or training group, regardless of division."""

    jugador_a = models.ForeignKey(
        Jugador, on_delete=models.CASCADE, related_name="rencillas_a"
    )
    jugador_b = models.ForeignKey(
        Jugador, on_delete=models.CASCADE, related_name="rencillas_b"
    )
    activa = models.BooleanField(default=True)
    motivo = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Rencilla"
        verbose_name_plural = "Rencillas (vetos)"
        unique_together = ("jugador_a", "jugador_b")

    def clean(self):
        if self.jugador_a_id == self.jugador_b_id:
            raise ValidationError("Una rencilla necesita dos jugadores distintos.")

    def save(self, *args, **kwargs):
        # Normalise ordering so (A,B) and (B,A) collapse to one row.
        if self.jugador_a_id and self.jugador_b_id and self.jugador_a_id > self.jugador_b_id:
            self.jugador_a_id, self.jugador_b_id = self.jugador_b_id, self.jugador_a_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.jugador_a} ✗ {self.jugador_b}"


class Contrato(models.Model):
    """Sponsorship contract (PRD §4.4): an elite player must be paired with a
    specific coach in >=1 morning shift and >=1 afternoon shift, when both are
    available."""

    jugador = models.ForeignKey(
        Jugador, on_delete=models.CASCADE, related_name="contratos"
    )
    entrenador = models.ForeignKey(
        Entrenador, on_delete=models.CASCADE, related_name="contratos"
    )
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Contrato de patrocinio"
        verbose_name_plural = "Contratos de patrocinio"
        unique_together = ("jugador", "entrenador")

    def __str__(self):
        return f"{self.jugador} → {self.entrenador}"


class VacacionesEntrenador(models.Model):
    """Periodo de vacaciones/baja larga de un entrenador (#11). El motor lo
    excluye de la generación en las fechas dentro del rango."""

    entrenador = models.ForeignKey(
        Entrenador, on_delete=models.CASCADE, related_name="vacaciones"
    )
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    motivo = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Vacaciones de entrenador"
        verbose_name_plural = "Vacaciones de entrenadores"
        ordering = ["fecha_inicio"]

    def clean(self):
        if self.fecha_fin < self.fecha_inicio:
            raise ValidationError("La fecha de fin no puede ser anterior al inicio.")

    def cubre(self, fecha):
        return self.fecha_inicio <= fecha <= self.fecha_fin

    def __str__(self):
        return f"{self.entrenador} · {self.fecha_inicio}–{self.fecha_fin}"


class Escuela(models.Model):
    """Escuela/programa dentro del club (#6): p. ej. Alto Rendimiento y Junior
    Program, que en verano comparten pistas en horarios distintos."""

    nombre = models.CharField(max_length=80, unique=True)
    activa = models.BooleanField(default=True)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Escuela"
        verbose_name_plural = "Escuelas"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


class Aviso(models.Model):
    """Aviso in-app que se muestra en el perfil del usuario (sin notificaciones
    externas). Lo usan los movimientos de escuela (#4), invitados (#5) y
    mantenimiento (#13)."""

    class Tipo(models.TextChoices):
        MOVIMIENTO = "MOVIMIENTO", "Movimiento de escuela"
        INVITADO = "INVITADO", "Invitado"
        MANTENIMIENTO = "MANTENIMIENTO", "Mantenimiento"
        GENERAL = "GENERAL", "General"

    # Destinatario concreto (un entrenador) o, si para_direccion=True, la
    # dirección deportiva (cualquier Super Admin lo ve).
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
        related_name="avisos",
    )
    para_direccion = models.BooleanField(default=False)
    tipo = models.CharField(max_length=14, choices=Tipo.choices, default=Tipo.GENERAL)
    titulo = models.CharField(max_length=160)
    mensaje = models.TextField(blank=True)
    leido = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Aviso"
        verbose_name_plural = "Avisos"
        ordering = ["leido", "-created_at"]

    def __str__(self):
        return f"[{self.get_tipo_display()}] {self.titulo}"


class Invitado(models.Model):
    """Jugador invitado por un entrenador para un día de entrenamiento (#5).
    Requiere aprobación del Director Deportivo (Super Admin) antes de entrar en
    los entrenamientos."""

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        APROBADO = "APROBADO", "Aprobado"
        RECHAZADO = "RECHAZADO", "Rechazado"

    nombre = models.CharField(max_length=120)
    entrenador_solicitante = models.ForeignKey(
        Entrenador, on_delete=models.CASCADE, related_name="invitados"
    )
    # Grupo anfitrión: un jugador del grupo del entrenador donde encajar al
    # invitado (para que el sistema lo ubique con esos jugadores).
    grupo_anfitrion = models.ForeignKey(
        Jugador, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invitados_anfitrion",
    )
    estado = models.CharField(
        max_length=10, choices=Estado.choices, default=Estado.PENDIENTE
    )
    aprobado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invitados_aprobados",
    )
    # Jugador temporal creado al aprobar, para poder ubicarlo en el cuadrante.
    jugador_creado = models.OneToOneField(
        Jugador, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invitado_origen",
    )
    nota = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Invitado"
        verbose_name_plural = "Invitados"
        ordering = ["estado", "-created_at"]

    def __str__(self):
        return f"{self.nombre} ({self.get_estado_display()})"


class TareaMantenimiento(models.Model):
    """Tarea de mantenimiento del club (#13). Con aviso in-app; el aviso al
    móvil del personal queda para cuando exista un canal de notificación."""

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        EN_CURSO = "EN_CURSO", "En curso"
        HECHA = "HECHA", "Hecha"

    titulo = models.CharField(max_length=160)
    descripcion = models.TextField(blank=True)
    responsable = models.CharField(max_length=120, blank=True)
    fecha_limite = models.DateField(null=True, blank=True)
    estado = models.CharField(
        max_length=10, choices=Estado.choices, default=Estado.PENDIENTE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tarea de mantenimiento"
        verbose_name_plural = "Tareas de mantenimiento"
        ordering = ["estado", "fecha_limite", "-created_at"]

    def __str__(self):
        return self.titulo


class Feedback(models.Model):
    """Peticiones / feedback del club: quién lo pide, qué prioridad merece y
    qué se solicita. Backlog editable por Super Admin y entrenadores."""

    class Prioridad(models.TextChoices):
        ALTA = "ALTA", "Alta"
        MEDIA = "MEDIA", "Media"
        BAJA = "BAJA", "Baja"

    class EstadoFeedback(models.TextChoices):
        NUEVO = "NUEVO", "Nuevo"
        EN_PROGRESO = "EN_PROGRESO", "En progreso"
        HECHO = "HECHO", "Hecho"
        DESCARTADO = "DESCARTADO", "Descartado"

    # Quién da el feedback / hace la petición (texto libre; puede ser alguien
    # que no tiene usuario en el sistema).
    autor = models.CharField(max_length=120)
    prioridad = models.CharField(
        max_length=6, choices=Prioridad.choices, default=Prioridad.MEDIA
    )
    titulo = models.CharField(max_length=160, blank=True)
    # Qué se solicita.
    descripcion = models.TextField()
    estado = models.CharField(
        max_length=12, choices=EstadoFeedback.choices, default=EstadoFeedback.NUEVO
    )
    # Usuario logueado que registró la entrada (si lo hubo).
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="feedback_creados",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Feedback / petición"
        verbose_name_plural = "Feedback y peticiones"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_prioridad_display()}] {self.titulo or self.descripcion[:40]}"
