from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Sede(models.Model):
    """Venue. Central is the base; the rest are satellite overflow venues
    (Sta. Bárbara, Bétera, Liria)."""

    nombre = models.CharField(max_length=80, unique=True)
    es_satelite = models.BooleanField(default=False)
    # Standard density is 2 players/court. Sta. Bárbara may go up to 4
    # ("tocados" / readaptación players).
    densidad_default = models.PositiveSmallIntegerField(default=2)
    densidad_max = models.PositiveSmallIntegerField(default=2)
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
    sede = models.ForeignKey(Sede, on_delete=models.CASCADE, related_name="pistas")
    numero = models.PositiveSmallIntegerField()
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
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Turno"
        verbose_name_plural = "Turnos"
        ordering = ["orden"]

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

    class Meta:
        verbose_name = "Entrenador"
        verbose_name_plural = "Entrenadores"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Jugador(models.Model):
    """Passive data entity — never logs in (PRD §01)."""

    nombre = models.CharField(max_length=120)
    edad = models.PositiveSmallIntegerField(null=True, blank=True)
    es_menor = models.BooleanField(default=False)
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
        if self.edad is not None:
            self.es_menor = self.edad < 18
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre


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
