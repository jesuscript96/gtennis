from django.db import models

from academy.models import Entrenador, Jugador, Pista, Turno


class Estado(models.TextChoices):
    """The state matrix (PRD §03). Colours mirror the academy's real Excel."""

    DISPONIBLE = "DISPONIBLE", "Disponible"          # green
    AUSENCIA_JUGADOR = "AUSENCIA_JUGADOR", "Ausencia jugador"  # red
    CALENTAMIENTO = "CALENTAMIENTO", "Calentamiento"  # yellow
    EN_TORNEO = "EN_TORNEO", "En torneo"              # orange
    CLIMATOLOGIA = "CLIMATOLOGIA", "Climatología"      # blue
    AUSENCIA_COACH = "AUSENCIA_COACH", "Ausencia coach"  # purple


class SubtipoAusencia(models.TextChoices):
    LESION = "LESION", "Lesión"
    ENFERMEDAD = "ENFERMEDAD", "Baja por enfermedad"
    ESTUDIOS = "ESTUDIOS", "Estudios"
    PRUEBA_MEDICA = "PRUEBA_MEDICA", "Prueba médica"
    VACACIONES = "VACACIONES", "Vacaciones"
    MILONGA = "MILONGA", "Milonga"


class Ambito(models.TextChoices):
    """Temporalidad de una disponibilidad/ausencia."""

    DIA = "DIA", "Todo el día"
    MANANA = "MANANA", "Toda la mañana"
    TARDE = "TARDE", "Toda la tarde"
    M1 = "M1", "Turno M1"
    M2 = "M2", "Turno M2"
    T1 = "T1", "Turno T1"
    T2 = "T2", "Turno T2"


# Players excluded from auto-pairing for the shift/day.
# EN_TORNEO and AUSENCIA_JUGADOR are no longer excluded — they are
# deprioritised so they fill courts only after fully-available players.
ESTADOS_EXCLUYENTES = {
    Estado.CLIMATOLOGIA,
}

# States that reduce priority in the pairing objective.
ESTADOS_DEPRIORIZADOS = {
    Estado.AUSENCIA_JUGADOR,
    Estado.EN_TORNEO,
}

DIAS = [
    (0, "Lunes"), (1, "Martes"), (2, "Miércoles"),
    (3, "Jueves"), (4, "Viernes"), (5, "Sábado"),
]


class Semana(models.Model):
    """A weekly cuadrante. The engine produces a draft; Iván publishes it."""

    class EstadoSemana(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        PUBLICADO = "PUBLICADO", "Publicado"

    fecha_inicio = models.DateField(unique=True, help_text="Lunes de la semana")
    estado = models.CharField(
        max_length=12, choices=EstadoSemana.choices, default=EstadoSemana.BORRADOR
    )
    generado_at = models.DateTimeField(null=True, blank=True)
    publicado_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Semana"
        verbose_name_plural = "Semanas"
        ordering = ["-fecha_inicio"]

    def __str__(self):
        return f"Semana {self.fecha_inicio} ({self.get_estado_display()})"


class Disponibilidad(models.Model):
    """Coach-entered override of a player's state for a given day/shift. The
    default (no row) means DISPONIBLE. This is the Friday 17:00 input."""

    semana = models.ForeignKey(
        Semana, on_delete=models.CASCADE, related_name="disponibilidades"
    )
    jugador = models.ForeignKey(Jugador, on_delete=models.CASCADE)
    dia = models.PositiveSmallIntegerField(choices=DIAS)
    # Temporalidad: todo el día / toda la mañana / toda la tarde / un turno.
    ambito = models.CharField(
        max_length=10, choices=Ambito.choices, default=Ambito.DIA
    )
    # Legacy (ya no se usa para el alcance; lo resuelve `ambito`).
    turno = models.ForeignKey(
        Turno, on_delete=models.CASCADE, null=True, blank=True
    )
    estado = models.CharField(max_length=20, choices=Estado.choices)
    subtipo = models.CharField(
        max_length=20, choices=SubtipoAusencia.choices, blank=True
    )
    nota = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Disponibilidad"
        verbose_name_plural = "Disponibilidades"
        unique_together = ("semana", "jugador", "dia", "ambito")

    def __str__(self):
        return f"{self.jugador} · D{self.dia} · {self.get_estado_display()}"


class Asignacion(models.Model):
    """One engine-produced cell: a player on a court, in a shift, on a day.
    Two (or up to 4 in Sta. Bárbara) per (semana, dia, turno, pista)."""

    semana = models.ForeignKey(
        Semana, on_delete=models.CASCADE, related_name="asignaciones"
    )
    dia = models.PositiveSmallIntegerField(choices=DIAS)
    turno = models.ForeignKey(Turno, on_delete=models.PROTECT)
    pista = models.ForeignKey(Pista, on_delete=models.PROTECT)
    jugador = models.ForeignKey(Jugador, on_delete=models.CASCADE)
    entrenador = models.ForeignKey(
        Entrenador, on_delete=models.SET_NULL, null=True, blank=True
    )
    estado = models.CharField(
        max_length=20, choices=Estado.choices, default=Estado.DISPONIBLE
    )
    # True if a Super Admin overrode the engine for this cell.
    manual = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Asignación"
        verbose_name_plural = "Asignaciones"
        unique_together = ("semana", "dia", "turno", "jugador")
        ordering = ["dia", "turno__orden", "pista"]

    def __str__(self):
        return f"D{self.dia} {self.turno.codigo} {self.pista}: {self.jugador}"


class ConfiguracionMotor(models.Model):
    """Singleton: tunable weights and parameters of the pairing engine (PRD
    criteria). Editable from the admin / management panel without code changes.
    Soft criteria are weights; some hard rules can be toggled/parametrised."""

    peso_asignacion = models.PositiveIntegerField(
        default=1000, help_text="Prioridad de que todos jueguen (dominante)."
    )
    peso_satelite = models.PositiveIntegerField(
        default=5, help_text="Penalización por usar una pista satélite."
    )
    peso_central = models.PositiveIntegerField(
        default=100, help_text="Bonus por jugador asignado a pista no satélite (rellenar GTennis primero)."
    )
    peso_repeticion = models.PositiveIntegerField(
        default=10, help_text="Penalización por repetir pareja (rotación)."
    )
    max_dias_misma_pista = models.PositiveSmallIntegerField(
        default=2, help_text="Repeticiones a partir de las cuales se penaliza fuerte."
    )
    aplicar_vecindad = models.BooleanField(
        default=True, help_text="Aplicar la regla de división N±1."
    )
    time_limit_s = models.PositiveSmallIntegerField(
        default=10, help_text="Tiempo máx. del solver por turno (segundos)."
    )

    class Meta:
        verbose_name = "Configuración del motor"
        verbose_name_plural = "Configuración del motor"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Configuración del motor"
