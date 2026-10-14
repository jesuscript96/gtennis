"""Calendario de torneos del club.

Módulo aparte del cuadrante de entrenamientos: comparte jugadores y
entrenadores (tablas de `academy`) pero no toca faltas ni semanas. Un torneo
es una fila con sus fechas, su cierre de inscripción, quién acompaña y quién
va. La vinculación con las faltas del cuadrante queda para más adelante.
"""
from django.db import models


class Torneo(models.Model):
    class Estado(models.TextChoices):
        PROPUESTO = "PROPUESTO", "Propuesto"
        VALIDADO = "VALIDADO", "Validado"
        CANCELADO = "CANCELADO", "Cancelado"

    nombre = models.CharField(max_length=160)
    # Circuito tal como se nombra en el club (ITF Junior, MARCA, TTK Warriors…).
    # Texto libre: los circuitos cambian cada temporada.
    circuito = models.CharField(max_length=60, blank=True)
    # Nivel dentro del circuito: J30, M25, Sub-16, Cadete… Texto libre.
    nivel = models.CharField(max_length=40, blank=True)
    lugar = models.CharField(max_length=120, blank=True)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    cierre_inscripcion = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.VALIDADO)
    # Quién viaja con los jugadores. Vacío = aún no decidido o van solos (ver nota).
    acompanantes = models.ManyToManyField(
        "academy.Entrenador", blank=True, related_name="torneos_acompanados",
    )
    # «Va solo», «Sí, con coach (sin nombre)», «No va coach»… lo que decía el Excel
    # cuando no había un entrenador concreto.
    acompanante_nota = models.CharField(max_length=120, blank=True)
    notas = models.TextField(blank=True)
    # Trazabilidad de la carga desde el Excel CALENDARIO 2026.
    fuente = models.CharField(max_length=300, blank=True)
    alias = models.CharField(max_length=300, blank=True, help_text="También escrito como")
    creado_por = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="torneos_creados",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Torneo"
        verbose_name_plural = "Torneos"
        ordering = ["fecha_inicio", "nombre"]

    def __str__(self):
        return f"{self.nombre} ({self.fecha_inicio:%d/%m}–{self.fecha_fin:%d/%m})"


class Participante(models.Model):
    """Un jugador apuntado a un torneo.

    `jugador` enlaza con la ficha de la academia cuando existe; `nombre` se
    guarda siempre, porque en el calendario del club aparecen jugadores que no
    están (o ya no están) en el cuadrante de entrenamientos.
    """

    class Certeza(models.TextChoices):
        CONFIRMADO = "CONFIRMADO", "Confirmado"
        PENDIENTE = "PENDIENTE", "Pendiente de confirmar"
        DEDUCIDO = "DEDUCIDO", "Deducido del Excel"

    torneo = models.ForeignKey(Torneo, on_delete=models.CASCADE, related_name="participantes")
    jugador = models.ForeignKey(
        "academy.Jugador", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="participaciones_torneo",
    )
    nombre = models.CharField(max_length=120)
    certeza = models.CharField(max_length=10, choices=Certeza.choices, default=Certeza.CONFIRMADO)
    # Entrenador de referencia del jugador en el Excel (no implica que viaje).
    entrenador_ref = models.CharField(max_length=120, blank=True)
    detalle = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Participante"
        verbose_name_plural = "Participantes"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(fields=["torneo", "nombre"], name="participante_unico_por_torneo"),
        ]

    def __str__(self):
        return f"{self.nombre} → {self.torneo}"
