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
    # Lo contrario de una ausencia: el entrenador apunta que ese día, en esa
    # franja, el alumno viene aunque su horario no lo diga.
    EXTRA = "EXTRA", "Viene además"  # teal


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
    M1 = "M1", "Turno M1 (8:30-10:00)"
    M2 = "M2", "Turno M2 (10:30-12:30)"
    JP = "JP", "Junior Program (12:30-14:30)"
    T1 = "T1", "Turno T1 (14:15-15:30)"
    T2 = "T2", "Turno T2 (15:30-17:30)"


# Estados que dejan al jugador fuera del emparejamiento automático ese
# día/turno. AUSENCIA_JUGADOR entra aquí: si el entrenador ha declarado que el
# alumno está lesionado, enfermo, de vacaciones o de exámenes, no está en el
# club y no puede ocupar una plaza de pista. Antes solo se le bajaba la
# prioridad, con lo que marcar una ausencia no la sacaba del cuadrante y el
# parte de los viernes no servía de nada.
ESTADOS_EXCLUYENTES = {
    Estado.CLIMATOLOGIA,
    Estado.AUSENCIA_JUGADOR,
}

# Estados que solo restan prioridad: el jugador sigue por el club y llena
# hueco después de los plenamente disponibles.
ESTADOS_DEPRIORIZADOS = {
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


class AusenciaJugador(models.Model):
    """Una ausencia larga de un jugador, con fecha de ida y de vuelta.

    `Disponibilidad` sirve para el parte de una semana concreta: una fila por
    jugador y día. Para una lesión de tres semanas eso son quince filas a mano,
    y el entrenador no las va a meter. Aquí se declara una sola vez —del 2 de
    noviembre al 15 de diciembre— y el motor la respeta todos los días que
    caigan dentro, sin importar de qué semana sean.

    El ámbito permite que sea parcial: todo el día, solo las mañanas, o una
    franja concreta ("los martes por la tarde no puede, tiene fisio").
    """

    jugador = models.ForeignKey(
        "academy.Jugador", on_delete=models.CASCADE, related_name="ausencias"
    )
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    ambito = models.CharField(
        max_length=10, choices=Ambito.choices, default=Ambito.DIA,
        help_text="Todo el día, una parte de la jornada o una franja concreta.",
    )
    estado = models.CharField(
        max_length=20, choices=Estado.choices, default=Estado.AUSENCIA_JUGADOR
    )
    subtipo = models.CharField(
        max_length=20, choices=SubtipoAusencia.choices, blank=True
    )
    # Franja horaria concreta, para las ausencias de un solo día: "el miércoles
    # no está de 8:30 a 10:00" o "llega a las 10:30". Vacías = todo el ámbito.
    # No tienen sentido en un rango largo: una lesión de tres semanas no es de
    # ocho a diez, y el formulario solo las pide cuando ida y vuelta coinciden.
    hora_desde = models.TimeField(
        null=True, blank=True, help_text="Solo para ausencias de un día."
    )
    hora_hasta = models.TimeField(null=True, blank=True)
    nota = models.CharField(max_length=200, blank=True)
    declarada_por = models.ForeignKey(
        "academy.Entrenador", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ausencias_declaradas",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ausencia por fechas"
        verbose_name_plural = "Ausencias por fechas"
        ordering = ["-fecha_inicio"]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.fecha_fin < self.fecha_inicio:
            raise ValidationError("La vuelta no puede ser anterior a la ida.")
        if (self.hora_desde or self.hora_hasta) and self.fecha_fin != self.fecha_inicio:
            raise ValidationError(
                "Las horas solo valen para una ausencia de un único día."
            )
        if self.hora_desde and self.hora_hasta and self.hora_hasta <= self.hora_desde:
            raise ValidationError("La hora de fin debe ser posterior a la de inicio.")

    def cubre(self, fecha):
        return self.fecha_inicio <= fecha <= self.fecha_fin

    def afecta(self, hora_inicio, hora_fin):
        """¿Pisa esta ausencia un turno que va de `hora_inicio` a `hora_fin`?

        Sin horas, la ausencia cubre el ámbito entero. Con horas, solo los
        turnos que se solapan con la ventana: así "llega a las 10:30" deja
        fuera la franja de 8:30 y respeta la de 10:30.
        """
        if not self.hora_desde and not self.hora_hasta:
            return True
        desde = self.hora_desde or hora_inicio
        hasta = self.hora_hasta or hora_fin
        return desde < hora_fin and hasta > hora_inicio

    def __str__(self):
        return f"{self.jugador} · {self.fecha_inicio}–{self.fecha_fin} ({self.get_estado_display()})"


class DisponibilidadEntrenador(models.Model):
    """Disponibilidad de un entrenador para un día de la semana (#10). Lo puede
    editar el propio entrenador desde su perfil. Sin fila = disponible todo el
    día. Permite 'de torneo por la tarde pero entreno por la mañana' con una
    ventana horaria [hora_desde, hora_hasta]."""

    class EstadoCoach(models.TextChoices):
        DISPONIBLE = "DISPONIBLE", "Disponible"
        TORNEO = "TORNEO", "En torneo (parcial)"
        AUSENTE = "AUSENTE", "No disponible"

    semana = models.ForeignKey(
        Semana, on_delete=models.CASCADE, related_name="disponibilidades_entrenador"
    )
    entrenador = models.ForeignKey(
        Entrenador, on_delete=models.CASCADE, related_name="disponibilidades"
    )
    dia = models.PositiveSmallIntegerField(choices=DIAS)
    estado = models.CharField(
        max_length=12, choices=EstadoCoach.choices, default=EstadoCoach.DISPONIBLE
    )
    # Ventana en la que SÍ puede entrenar (vacío = todo el día). Con estado
    # TORNEO se usa para acotar las horas realmente disponibles.
    hora_desde = models.TimeField(null=True, blank=True)
    hora_hasta = models.TimeField(null=True, blank=True)
    nota = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Disponibilidad de entrenador"
        verbose_name_plural = "Disponibilidades de entrenador"
        unique_together = ("semana", "entrenador", "dia")

    def disponible_en(self, hora_inicio, hora_fin):
        """¿Está disponible durante todo el turno [hora_inicio, hora_fin]?"""
        if self.estado == self.EstadoCoach.AUSENTE:
            return False
        if self.hora_desde and hora_inicio < self.hora_desde:
            return False
        if self.hora_hasta and hora_fin > self.hora_hasta:
            return False
        return True

    def __str__(self):
        return f"{self.entrenador} · D{self.dia} · {self.get_estado_display()}"


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
        default=True, help_text="Aplicar la regla de vecindad de divisiones."
    )
    vecindad_max = models.PositiveSmallIntegerField(
        default=1,
        help_text="Diferencia máxima de división dentro de una pista. A 1 "
                  "(N±1) quedan fuera el 30% de las parejas que la dirección "
                  "deportiva forma de verdad; a 2, solo el 9%.",
    )
    time_limit_s = models.PositiveSmallIntegerField(
        default=10, help_text="Tiempo máx. del solver por turno (segundos)."
    )
    # --- Dosis de entrenamiento (#18) --------------------------------------
    # No hay cupo semanal: se da por hecho que todos vienen todos los días, y
    # lo que no, se declara (ausencias, horario). Solo quedan los topes del día.
    sesiones_dia_max_default = models.PositiveSmallIntegerField(
        default=2, help_text="Máximo de sesiones el mismo día por jugador."
    )
    sesiones_bloque_max = models.PositiveSmallIntegerField(
        default=1,
        help_text="Máximo de sesiones en el mismo bloque (mañana o tarde). "
                  "En los cuadrantes reales, de 249 jugadores con doble sesión "
                  "en un día, 248 la hacen mañana+tarde y solo 1 dos mañanas.",
    )
    peso_densidad = models.PositiveIntegerField(
        default=400,
        help_text="Penalización por cada jugador por encima de la densidad "
                  "normal de la pista (2). Permite subir a 3-4 solo cuando "
                  "hace falta para que alguien entrene.",
    )
    peso_pareja = models.PositiveIntegerField(
        default=5000,
        help_text="Bonus por juntar una pareja preferente. Va en la misma "
                  "escala que peso_asignacion x prioridad: desempata entre "
                  "compañeros igual de válidos sin llegar a dejar a nadie fuera.",
    )
    peso_pista_abierta = models.PositiveIntegerField(
        default=500,
        help_text="Coste de abrir una pista. Hace que el motor agrupe de dos "
                  "en dos en vez de repartir clases individuales.",
    )
    peso_equilibrio_franjas = models.PositiveIntegerField(
        default=200,
        help_text="Cuánto cuesta cada jugador de desequilibrio entre las "
                  "franjas de un bloque (8:30 y 10:30; 14:15 y 15:30). Se "
                  "reparten en proporción a los entrenadores de cada franja. "
                  "Por debajo de lo que cuesta abrir una pista, para no partir "
                  "parejas en individuales solo por cuadrar.",
    )
    peso_carga_entrenador = models.PositiveIntegerField(
        default=4,
        help_text="Cuánto pesa equilibrar la carga entre entrenadores frente "
                  "a respetar los % objetivo de cada jugador.",
    )
    permitir_individuales = models.BooleanField(
        default=True,
        help_text="Permitir pistas de un solo jugador (clase particular) "
                  "cuando no hay con quién emparejarlo.",
    )
    usar_satelites = models.BooleanField(
        default=True,
        help_text="Desbordar a los clubs satélite cuando el Resort se llena. "
                  "En verano se desactiva: lo que no cabe queda en el banquillo.",
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
