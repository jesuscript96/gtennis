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
    # Las franjas de escuela de tarde existen en el cuadrante pero todavía no
    # entran en el reparto automático. Se apagan sin borrarlas.
    activo = models.BooleanField(
        default=True, help_text="Si no, el motor no reparte en este turno."
    )

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
    # Histórico: las divisiones que entrenaba. Desde septiembre de 2026 la
    # división solo empareja alumnos y con quién entrena cada uno lo dicen sus
    # porcentajes (`ResponsableJugador`); el motor ya no lo mira.
    divisiones_habilitadas = models.ManyToManyField(
        "Division",
        blank=True,
        related_name="entrenadores",
    )
    # En qué franja da clase, igual que el alumno. Vacío = cualquiera: entra
    # siempre que haya jugadores suyos disponibles, que es el caso normal.
    # Para "los martes no vengo por la tarde" está `HorarioEntrenador`, que va
    # por día; esto es la franja fija de toda la semana.
    turno_manana = models.ForeignKey(
        "Turno", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="entrenadores_manana",
        limit_choices_to={"codigo__in": ["M1", "M2"]},
        help_text="M1 (8:30) o M2 (10:30). Vacío = cualquiera.",
    )
    turno_tarde = models.ForeignKey(
        "Turno", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="entrenadores_tarde",
        limit_choices_to={"codigo__in": ["T1", "T2"]},
        help_text="T1 (14:15) o T2 (15:30). Vacío = cualquiera.",
    )

    class Meta:
        verbose_name = "Entrenador"
        verbose_name_plural = "Entrenadores"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

    def jugadores_permitidos(self):
        """Queryset de jugadores activos que este entrenador puede gestionar.
        Fuente única: ResponsableJugador (cualquier prioridad). Se mantiene la
        unión con `jugadores_gestionados` por compatibilidad."""
        from django.db.models import Q

        activos = Jugador.objects.filter(activo=True)
        if self.gestiona_todos_jugadores:
            return activos
        return activos.filter(
            Q(entrenador_responsable=self)
            | Q(responsables__entrenador=self)
            | Q(entrenadores_gestores=self)
        ).distinct()

    def puede_gestionar(self, jugador):
        """¿Puede este entrenador declarar ausencias de `jugador`?"""
        if self.gestiona_todos_jugadores:
            return True
        return self.jugadores_permitidos().filter(pk=jugador.pk).exists()


class HorarioEntrenador(models.Model):
    """Qué bloques trabaja un entrenador cada día de la semana.

    Es su patrón estable: "los martes solo por la mañana", "los viernes no
    vengo". Por defecto trabaja mañana y tarde, así que NO hace falta crear
    filas para quien tiene jornada completa — sin fila, ambas cuentan como
    disponibles.

    No confundir con `DisponibilidadEntrenador`, que es la excepción de una
    semana concreta (un torneo, una tarde libre), ni con
    `VacacionesEntrenador`, que es un periodo largo con fechas.
    """

    DIAS = [
        (0, "Lunes"), (1, "Martes"), (2, "Miércoles"),
        (3, "Jueves"), (4, "Viernes"), (5, "Sábado"),
    ]

    entrenador = models.ForeignKey(
        Entrenador, on_delete=models.CASCADE, related_name="horario"
    )
    dia = models.PositiveSmallIntegerField(choices=DIAS)
    manana = models.BooleanField(default=True, verbose_name="Trabaja por la mañana")
    tarde = models.BooleanField(default=True, verbose_name="Trabaja por la tarde")

    class Meta:
        verbose_name = "Jornada del entrenador"
        verbose_name_plural = "Jornada semanal"
        unique_together = ("entrenador", "dia")
        ordering = ["entrenador", "dia"]

    def trabaja(self, bloque):
        return self.manana if bloque == Turno.Bloque.MANANA else self.tarde

    def __str__(self):
        partes = [b for b, v in (("mañana", self.manana), ("tarde", self.tarde)) if v]
        return f"{self.entrenador} · {self.get_dia_display()}: {' y '.join(partes) or 'libre'}"


class Coach(models.Model):
    """Rol intermedio (#16): por encima del entrenador y por debajo de la
    dirección deportiva. Tiene un conjunto de entrenadores a su cargo y ve a
    todos los jugadores de esos entrenadores."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="coach",
    )
    nombre = models.CharField(max_length=120)
    activo = models.BooleanField(default=True)
    entrenadores = models.ManyToManyField(
        "Entrenador", blank=True, related_name="coaches",
    )

    class Meta:
        verbose_name = "Coach"
        verbose_name_plural = "Coaches"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


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
    # La fecha de nacimiento es el dato que se teclea; la edad se recalcula
    # sola en cada `save()` y se guarda para poder filtrar y ordenar por ella.
    # Se mantiene escribible porque de los alumnos antiguos solo consta la edad.
    fecha_nacimiento = models.DateField(null=True, blank=True)
    edad = models.PositiveSmallIntegerField(null=True, blank=True)
    es_menor = models.BooleanField(default=False)
    # Día exacto en que el alumno entra en la academia. Hay altas a mitad de
    # mes ("entra el 16") y hasta ese día el motor no debe meterlo en ningún
    # entrenamiento. Vacío = ya estaba, entra desde siempre.
    fecha_alta = models.DateField(
        null=True, blank=True, verbose_name="Fecha de alta",
        help_text="Desde qué día entra en los entrenamientos. Vacío = desde siempre.",
    )
    fecha_baja = models.DateField(
        null=True, blank=True, verbose_name="Fecha de baja",
        help_text="Último día que entrena. Vacío = sigue en activo.",
    )
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
    # --- Dosis de entrenamiento (#18) --------------------------------------
    # Cuántas sesiones le tocan a este jugador. El motor reparte hasta cubrir
    # el objetivo semanal de todos antes de dar una segunda vuelta, y nunca
    # pone a nadie más veces al día de las que marca `sesiones_dia_max`.
    # Vacío = usa el valor por defecto de ConfiguracionMotor.
    sesiones_semana = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Sesiones/semana objetivo. Vacío = valor por defecto del motor.",
    )
    sesiones_dia_max = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Máximo de sesiones el mismo día. Vacío = valor por defecto.",
    )
    # En qué franja entra este jugador. Por defecto entrena dos turnos al día,
    # uno de mañana y otro de tarde; estos campos fijan cuáles. Vacío = el
    # motor elige la que mejor encaje dentro del bloque.
    turno_manana = models.ForeignKey(
        "Turno", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="jugadores_manana",
        limit_choices_to={"codigo__in": ["M1", "M2"]},
        help_text="M1 (8:30) o M2 (10:30). Vacío = cualquiera.",
    )
    turno_tarde = models.ForeignKey(
        "Turno", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="jugadores_tarde",
        limit_choices_to={"codigo__in": ["T1", "T2"]},
        help_text="T1 (14:15) o T2 (15:30). Vacío = cualquiera.",
    )
    # La regla de vecindad (±1 división) no cambia; esto decide hacia qué lado
    # tira cuando puede elegir. OJO al sentido: la División 1 es la MÁS ALTA,
    # así que «hacia arriba» es emparejarle con la división de número menor.
    class ParejaDivision(models.TextChoices):
        ARRIBA = "ARRIBA", "Hacia arriba (división mejor, D-1)"
        ABAJO = "ABAJO", "Hacia abajo (división de debajo, D+1)"

    # Nulo = le da igual. Se deja nulo y no vacío porque el formulario de la
    # app manda «—» como null.
    pareja_division = models.CharField(
        max_length=6, choices=ParejaDivision.choices, null=True, blank=True,
        verbose_name="Se empareja preferentemente",
        help_text="Siempre dentro de ±1 división. Vacío = le da igual.",
    )

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

    def en_alta(self, fecha):
        """¿Está este jugador dado de alta el día `fecha`?

        El alta a mitad de mes es lo normal en la academia: el alumno figura ya
        en la ficha pero no debe salir en el cuadrante hasta el día que empieza.
        """
        if self.fecha_alta is not None and fecha < self.fecha_alta:
            return False
        if self.fecha_baja is not None and fecha > self.fecha_baja:
            return False
        return True

    def repartir_porcentajes(self):
        """Devuelve sus porcentajes a la regla de dirección (`academy.pesos`):
        los secundarios (prioridad ≥ 2) con el mínimo y los principales a partes
        iguales con lo que queda."""
        from .pesos import reparto_por_defecto

        resp = list(self.responsables.filter(activo=True).order_by("prioridad", "id"))
        reparto = {
            e: (p, c) for e, p, c in reparto_por_defecto(
                [r.entrenador_id for r in resp if r.prioridad <= 1],
                [r.entrenador_id for r in resp if r.prioridad > 1],
            )
        }
        for r in resp:
            prioridad, pct = reparto[r.entrenador_id]
            if (r.prioridad, r.porcentaje_objetivo) != (prioridad, pct):
                r.prioridad, r.porcentaje_objetivo = prioridad, pct
                r.save(update_fields=["prioridad", "porcentaje_objetivo"])


class HorarioJugador(models.Model):
    """Qué franjas entrena un jugador cada día de la semana.

    El alumno hace por defecto dos turnos al día, uno de mañana y otro de
    tarde, pero no siempre los mismos: puede venir a primera hora los lunes y
    a segunda los miércoles. Esto es el patrón semanal estable, no las
    ausencias de una semana concreta — para eso está `Disponibilidad`.

    Sin fila para un día, valen `Jugador.turno_manana` / `turno_tarde`; y si
    esos también están vacíos, el motor elige la franja que mejor encaje.
    Dejar un turno a nulo con la fila creada significa "ese día no entrena en
    ese bloque".
    """

    DIAS = [
        (0, "Lunes"), (1, "Martes"), (2, "Miércoles"),
        (3, "Jueves"), (4, "Viernes"), (5, "Sábado"),
    ]

    jugador = models.ForeignKey(
        "Jugador", on_delete=models.CASCADE, related_name="horario"
    )
    dia = models.PositiveSmallIntegerField(choices=DIAS)
    turno_manana = models.ForeignKey(
        "Turno", on_delete=models.CASCADE, null=True, blank=True,
        related_name="horarios_manana",
        limit_choices_to={"bloque": "MANANA", "activo": True,
                          "codigo__in": ["M1", "M2"]},
        verbose_name="Turno de mañana",
    )
    turno_tarde = models.ForeignKey(
        "Turno", on_delete=models.CASCADE, null=True, blank=True,
        related_name="horarios_tarde",
        limit_choices_to={"bloque": "TARDE", "activo": True,
                          "codigo__in": ["T1", "T2"]},
        verbose_name="Turno de tarde",
    )
    # Hay tres respuestas por bloque, no dos, y el turno a nulo solo sabía decir
    # una: "ese día no entrena por la tarde" y "ese día entrena por la tarde en
    # la franja que salga" se escribían igual. Así, declarar que un alumno no
    # viene un martes por la tarde le sacaba también de las mañanas del martes.
    entrena_manana = models.BooleanField(
        default=True, verbose_name="Entrena por la mañana",
        help_text="Si no, ese día no entrena por la mañana. Con el turno vacío, "
                  "entrena en la franja que mejor encaje.",
    )
    entrena_tarde = models.BooleanField(
        default=True, verbose_name="Entrena por la tarde",
        help_text="Si no, ese día no entrena por la tarde. Con el turno vacío, "
                  "entrena en la franja que mejor encaje.",
    )

    class Meta:
        verbose_name = "Horario del jugador"
        verbose_name_plural = "Horario semanal"
        unique_together = ("jugador", "dia")
        ordering = ["jugador", "dia"]

    def clean(self):
        if self.turno_manana and self.turno_manana.bloque != Turno.Bloque.MANANA:
            raise ValidationError(
                f"{self.turno_manana.codigo} no es un turno de mañana."
            )
        if self.turno_tarde and self.turno_tarde.bloque != Turno.Bloque.TARDE:
            raise ValidationError(
                f"{self.turno_tarde.codigo} no es un turno de tarde."
            )

    def __str__(self):
        m = self.turno_manana.codigo if self.turno_manana else "—"
        t = self.turno_tarde.codigo if self.turno_tarde else "—"
        return f"{self.jugador} · {self.get_dia_display()}: {m} / {t}"


class ResponsableJugador(models.Model):
    """Con quién entrena un alumno y en qué proporción (`academy.pesos`).

    Prioridad 1 es su principal y 2 un secundario, que lleva como mínimo un
    10%. El porcentaje es la parte de sus entrenamientos con este entrenador, y
    el motor se acerca a él a lo largo de la semana. Quién le gestiona es otra
    cosa: `Jugador.entrenador_responsable`. Sin porcentajes, entrena con su
    responsable."""

    jugador = models.ForeignKey(
        Jugador, on_delete=models.CASCADE, related_name="responsables"
    )
    entrenador = models.ForeignKey(
        Entrenador, on_delete=models.CASCADE, related_name="jugadores_responsable"
    )
    # 1 = principal; 2 = secundario.
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

    class Tipo(models.TextChoices):
        # Duro: el entrenador va con ese jugador siempre que coincidan.
        DURO = "DURO", "Duro · siempre con él"
        # Blando: primero su grupo; con el jugador del contrato solo cuando
        # hacerlo no deja otra pista sin entrenador.
        BLANDO = "BLANDO", "Blando · cuando pueda"

    tipo = models.CharField(
        max_length=6, choices=Tipo.choices, default=Tipo.DURO,
        help_text="Duro: siempre con él. Blando: primero su grupo, y con este "
                  "jugador cuando no deje ninguna pista sin entrenador.",
    )

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

    # Qué se pierde: el día entero, un bloque o una franja. Espejo de
    # `scheduling.models.Ambito` (no se importa: scheduling depende de academy).
    class Ambito(models.TextChoices):
        DIA = "DIA", "Todo el día"
        MANANA = "MANANA", "Toda la mañana"
        TARDE = "TARDE", "Toda la tarde"
        M1 = "M1", "Turno M1"
        M2 = "M2", "Turno M2"
        JP = "JP", "Junior Program"
        T1 = "T1", "Turno T1"
        T2 = "T2", "Turno T2"

    ambito = models.CharField(
        max_length=10, choices=Ambito.choices, default=Ambito.DIA,
        help_text="Todo el día, un bloque o una franja concreta.",
    )

    def afecta_turno(self, turno):
        """¿Deja al entrenador fuera de este turno?"""
        return self.ambito in (self.Ambito.DIA, turno.bloque, turno.codigo)

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


class PreferenciaSuperficie(models.Model):
    """Preferencia de superficie de un jugador (#1): tierra batida o pista
    rápida, por un periodo (fecha_desde/hasta) o indefinida. Si es estricta, el
    motor no lo asigna a pistas de otra superficie."""

    jugador = models.ForeignKey(
        Jugador, on_delete=models.CASCADE, related_name="preferencias_superficie"
    )
    superficie = models.CharField(max_length=10, choices=Pista.Superficie.choices)
    fecha_desde = models.DateField(null=True, blank=True)
    fecha_hasta = models.DateField(null=True, blank=True)
    estricta = models.BooleanField(
        default=True,
        help_text="Si está marcada, el motor nunca lo pone en otra superficie.",
    )

    class Meta:
        verbose_name = "Preferencia de superficie"
        verbose_name_plural = "Preferencias de superficie"
        ordering = ["jugador", "-fecha_desde"]

    def activa_en(self, fecha):
        if self.fecha_desde and fecha < self.fecha_desde:
            return False
        if self.fecha_hasta and fecha > self.fecha_hasta:
            return False
        return True

    def __str__(self):
        return f"{self.jugador} → {self.get_superficie_display()}"


class PreferenciaPareja(models.Model):
    """Pareja preferida (#5): dos jugadores que deben (HARD, misma pista) o
    preferentemente (SOFT, bonus) entrenar juntos. Nace de invitados o de
    peticiones manuales."""

    class Tipo(models.TextChoices):
        HARD = "HARD", "Obligatoria (misma pista)"
        SOFT = "SOFT", "Preferente (bonus)"

    jugador = models.ForeignKey(
        Jugador, on_delete=models.CASCADE, related_name="parejas_pref"
    )
    jugador_objetivo = models.ForeignKey(
        Jugador, on_delete=models.CASCADE, related_name="parejas_pref_objetivo"
    )
    tipo = models.CharField(max_length=4, choices=Tipo.choices, default=Tipo.HARD)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Preferencia de pareja"
        verbose_name_plural = "Preferencias de pareja"
        unique_together = ("jugador", "jugador_objetivo")

    def __str__(self):
        return f"{self.jugador} + {self.jugador_objetivo} ({self.tipo})"


class Escuela(models.Model):
    """Escuela/programa dentro del club (#6): p. ej. Alto Rendimiento y Junior
    Program, que en verano comparten pistas en horarios distintos."""

    nombre = models.CharField(max_length=80, unique=True)
    activa = models.BooleanField(default=True)
    orden = models.PositiveSmallIntegerField(default=0)
    # #6: si se fija, los jugadores de esta escuela SOLO entrenan en ese turno
    # (p. ej. Junior Program solo en M2) y no salen en el resto de turnos.
    turno_unico = models.ForeignKey(
        "Turno", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="escuelas_exclusivas",
    )
    # #6: sus jugadores solo se ubican en el Resort (nunca en clubs satélite).
    solo_central = models.BooleanField(default=False)

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
    # Datos propios del invitado (#5): al aprobar, el jugador temporal se crea
    # con estos datos y no hereda ciegamente los del grupo anfitrión.
    division = models.ForeignKey(
        "Division", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    edad = models.PositiveSmallIntegerField(null=True, blank=True)
    superficie_pref = models.CharField(
        max_length=10, choices=Pista.Superficie.choices, blank=True
    )
    # Pareja preferida: con qué jugador quiere entrenar (#5).
    jugar_con = models.ForeignKey(
        Jugador, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    pareja_estricta = models.BooleanField(default=True)
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
        HECHO = "HECHO", "Implementado"
        AJENO = "AJENO", "Ajeno a esta plataforma"
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
