"""Calendario de torneos del club.

Módulo aparte del cuadrante de entrenamientos: comparte jugadores y
entrenadores (tablas de `academy`) pero no toca faltas ni semanas. Un torneo
es una fila con sus fechas, su cierre de inscripción, quién acompaña y quién
va. La vinculación con las faltas del cuadrante queda para más adelante.
"""
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from .categorias import CATEGORIAS


class Torneo(models.Model):
    # «Propuesto (pendiente de validar)» se quitó el 10/11/2026: nadie lo
    # validaba. Lo pendiente de confirmar es el jugador apuntado
    # (`Participante.certeza`), no el torneo.
    class Estado(models.TextChoices):
        VALIDADO = "VALIDADO", "Validado"
        CANCELADO = "CANCELADO", "Cancelado"

    nombre = models.CharField(max_length=160)
    # Circuito tal como se nombra en el club (ITF Junior, MARCA, TTK Warriors…).
    # Texto libre: los circuitos cambian cada temporada.
    circuito = models.CharField(max_length=60, blank=True)
    # Nivel dentro del circuito: J30, M25… Texto libre; casi no se usaba y
    # desde el 03/11/2026 el formulario pide las categorías.
    nivel = models.CharField(max_length=40, blank=True)
    # Categorías de edad («SUB12», «SUB14»… ver categorias.py). Vacío = sin
    # límite de edad.
    categorias = models.JSONField(default=list, blank=True)
    lugar = models.CharField(max_length=120, blank=True)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    cierre_inscripcion = models.DateField(null=True, blank=True)
    # Último día para borrar (retirar) a un jugador inscrito sin que cuente
    # como baja tardía (10/11/2026, petición de Sergio).
    fecha_borrado = models.DateField(null=True, blank=True, verbose_name="Fecha límite de borrado")
    # Previa (clasificación / pre-qualy): días antes del cuadro final. Ocupan
    # semana igual que el torneo, así que cuentan para saber dónde sale.
    qualy_inicio = models.DateField(null=True, blank=True, verbose_name="Previa desde")
    qualy_fin = models.DateField(null=True, blank=True, verbose_name="Previa hasta")
    # Torneos que se juegan solo en fin de semana y se alargan varias semanas
    # (circuitos provinciales, Champions Cup…): entre semana se entrena.
    solo_fines_semana = models.BooleanField(default=False, verbose_name="Solo fines de semana")
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

    # El circuito desde el 25/11/2026: el entrenador apunta (PENDIENTE), su
    # head coach lo valida o lo mueve (VALIDADO_COACH) y dirección da el visto
    # bueno final o lo mueve (CONFIRMADO). Lo que apunta un head coach entra ya
    # validado por él; lo que apunta dirección, confirmado.
    class Certeza(models.TextChoices):
        CONFIRMADO = "CONFIRMADO", "Confirmado"
        VALIDADO_COACH = "VALIDADO_COACH", "Validado por el head coach"
        PENDIENTE = "PENDIENTE", "Pendiente del head coach"
        DEDUCIDO = "DEDUCIDO", "Deducido del Excel"

    torneo = models.ForeignKey(Torneo, on_delete=models.CASCADE, related_name="participantes")
    jugador = models.ForeignKey(
        "academy.Jugador", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="participaciones_torneo",
    )
    nombre = models.CharField(max_length=120)
    certeza = models.CharField(max_length=16, choices=Certeza.choices, default=Certeza.CONFIRMADO)
    # Entrenador de referencia del jugador en el Excel (no implica que viaje).
    entrenador_ref = models.CharField(max_length=120, blank=True)
    detalle = models.CharField(max_length=200, blank=True)
    # Quién lo apuntó (03/11/2026). Los entrenadores apuntan a sus jugadores y
    # quedan pendientes hasta que su head coach o dirección los confirman.
    apuntado_por = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="torneos_apuntados",
    )
    # Quién dio cada visto bueno (25/11/2026).
    validado_coach_por = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="torneos_validados_coach",
    )
    validado_coach_en = models.DateTimeField(null=True, blank=True)
    confirmado_por = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="torneos_confirmados",
    )
    confirmado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Participante"
        verbose_name_plural = "Participantes"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(fields=["torneo", "nombre"], name="participante_unico_por_torneo"),
        ]

    def __str__(self):
        return f"{self.nombre} → {self.torneo}"


class CambioTorneo(models.Model):
    """Foto de los torneos que toca un cambio, tomada justo antes, para
    deshacerlo. Como en el cuadrante: no se guarda «qué se hizo» sino cómo
    estaban; deshacer es devolverlos a la foto.

    `foto` = {id de torneo: estado | None}. None quiere decir que ese torneo no
    existía (un alta): deshacer lo borra.
    """

    MAXIMO = 50  # por usuario

    descripcion = models.CharField(max_length=160)
    foto = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    creado_at = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="cambios_torneos",
    )

    class Meta:
        verbose_name = "Cambio en torneos"
        verbose_name_plural = "Cambios en torneos"
        ordering = ["-creado_at", "-id"]

    def __str__(self):
        return self.descripcion


class CategoriaJugador(models.Model):
    """La categoría de un jugador del que no consta la fecha de nacimiento
    (03/11/2026: de Carlos López Montagud solo se sabe que ya es absoluto).
    Si la ficha tiene fecha de nacimiento, manda la fecha."""

    jugador = models.OneToOneField(
        "academy.Jugador", on_delete=models.CASCADE, related_name="categoria_torneos",
    )
    categoria = models.CharField(max_length=10, choices=[(c[0], c[1]) for c in CATEGORIAS])

    class Meta:
        verbose_name = "Categoría de un jugador sin fecha de nacimiento"
        verbose_name_plural = "Categorías de jugadores sin fecha de nacimiento"

    def __str__(self):
        return f"{self.jugador} → {self.get_categoria_display()}"


class NormasTorneos(models.Model):
    """Las normas de torneos de G Tenis que van al final del correo mensual a
    las familias (25/11/2026). Una sola fila; la escribe dirección."""

    texto = models.TextField(blank=True)
    texto_en = models.TextField(blank=True, help_text="Para las familias en inglés; vacío = el de español")
    actualizado_por = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Normas de torneos"
        verbose_name_plural = "Normas de torneos"

    def __str__(self):
        return "Normas de torneos"

    @classmethod
    def actuales(cls):
        return cls.objects.first() or cls()


class CorreoTorneos(models.Model):
    """El correo del día 1 a la familia de un jugador con sus torneos del mes
    y del siguiente (25/11/2026). Se genera el día 1 y sale cuando lo valida
    su head coach o dirección. Hasta entonces se enseña con los datos del
    momento; al validarlo se guarda tal cual (`contenido`) y eso es lo que sale."""

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Por validar"
        VALIDADO = "VALIDADO", "Validado, saliendo"
        ENVIADO = "ENVIADO", "Enviado"
        DESCARTADO = "DESCARTADO", "No se envía"

    jugador = models.ForeignKey("academy.Jugador", on_delete=models.CASCADE, related_name="correos_torneos")
    # Primer día del mes del correo: cubre ese mes y el siguiente.
    mes = models.DateField()
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    contenido = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    destinatarios = models.JSONField(default=list, blank=True)
    idioma = models.CharField(max_length=2, default="ES")
    validado_por = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    validado_en = models.DateTimeField(null=True, blank=True)
    enviado_en = models.DateTimeField(null=True, blank=True)
    envio_error = models.CharField(max_length=300, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Correo mensual de torneos"
        verbose_name_plural = "Correos mensuales de torneos"
        ordering = ["-mes", "jugador__nombre"]
        constraints = [
            models.UniqueConstraint(fields=["jugador", "mes"], name="correo_torneos_unico_por_mes"),
        ]

    def __str__(self):
        return f"{self.jugador} · {self.mes:%m/%Y}"
