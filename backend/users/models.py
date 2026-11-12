from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Los jugadores no entran: solo el personal del club.

    Perfiles (orden de la aplicación, 10/11/2026): Dirección, Head coach,
    Entrenador y Preparador físico, más Administración (altas, datos de
    jugadores y envío de informes; sin motor ni cuadrante). Lo que antes eran
    excepciones por persona son ahora funciones que dirección asigna desde
    Club (`Funcion`).
    """

    class Role(models.TextChoices):
        SUPERADMIN = "SUPERADMIN", "Dirección"
        COACH = "COACH", "Head coach"
        ENTRENADOR = "ENTRENADOR", "Entrenador"
        # 21/10/2026: hace la parte física de los informes (Josep Mari). No
        # entra al cuadrante ni a las faltas: solo a Rendimiento.
        PREPARADOR = "PREPARADOR", "Preparador físico"
        # 10/11/2026 (decisión 10): altas y datos de jugadores y envío de
        # informes a las familias. Sin motor ni cuadrante.
        ADMINISTRACION = "ADMINISTRACION", "Administración"

    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.ENTRENADOR
    )

    @property
    def is_superadmin(self):
        return self.role == self.Role.SUPERADMIN or self.is_superuser

    @property
    def is_coach(self):
        """Head coach: por encima del entrenador, por debajo de la dirección."""
        return self.role == self.Role.COACH and not self.is_superadmin

    @property
    def is_preparador(self):
        return self.role == self.Role.PREPARADOR and not self.is_superadmin

    @property
    def is_administracion(self):
        return self.role == self.Role.ADMINISTRACION and not self.is_superadmin

    @property
    def is_direccion(self):
        return self.is_superadmin

    @property
    def perfil(self):
        """Nombre corto del perfil para la interfaz."""
        if self.is_superadmin:
            return "direccion"
        return {
            self.Role.COACH: "head_coach",
            self.Role.PREPARADOR: "preparador",
            self.Role.ADMINISTRACION: "administracion",
        }.get(self.role, "entrenador")

    def codigos_funcion(self):
        """Funciones asignadas (cacheadas por petición)."""
        cache = getattr(self, "_funciones_cache", None)
        if cache is None:
            cache = set(self.funciones.values_list("codigo", flat=True)) if self.pk else set()
            self._funciones_cache = cache
        return cache

    def __str__(self):
        return self.get_full_name() or self.username


class Funcion(models.Model):
    """Una función que dirección asigna a una persona desde Club, sin tocar el
    programa (10/11/2026). Sustituye a las listas de nombres escritas en el
    código. Dirección las tiene todas sin necesidad de marcarlas.

    «Evalúa tenis o física de tardes» no está aquí: es el equipo de
    Competición de tardes (`evaluaciones.MiembroTardes`)."""

    class Codigo(models.TextChoices):
        TOCA_CUADRANTE = "TOCA_CUADRANTE", "Toca el cuadrante"
        APRUEBA_INVITADOS = "APRUEBA_INVITADOS", "Aprueba invitados"
        COORDINA_TARDES = "COORDINA_TARDES", "Coordina Competición de tardes"
        VALIDA_INFORMES = "VALIDA_INFORMES", "Valida informes"
        ENVIA_INFORMES = "ENVIA_INFORMES", "Envía informes a las familias"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="funciones")
    codigo = models.CharField(max_length=24, choices=Codigo.choices)
    asignada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name="+")
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["usuario", "codigo"], name="funcion_unica")]
        ordering = ["usuario__username", "codigo"]

    def __str__(self):
        return f"{self.usuario} · {self.get_codigo_display()}"


class ArchivoMigracion(models.Model):
    """Lo que una migración de datos cambia o borra, tal como estaba antes
    (11/11/2026, orden de la aplicación). Sirve para deshacerla exactamente sin
    depender de una copia de seguridad y para que no se pierda nada aunque
    nunca se deshaga: las filas borradas siguen aquí, enteras.

    `accion`: «borrado» (la fila entera en `datos`), «cambiado» (los campos que
    tenía antes) o «creado» (solo la clave, para poder quitarla al deshacer)."""

    migracion = models.CharField(max_length=80, db_index=True)
    modelo = models.CharField(max_length=80)
    pk_original = models.CharField(max_length=40, blank=True)
    accion = models.CharField(max_length=10)
    datos = models.JSONField(default=dict, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "archivo de migración"
        verbose_name_plural = "archivo de migraciones"
        ordering = ["id"]

    def __str__(self):
        return f"{self.migracion} · {self.accion} {self.modelo} {self.pk_original}"
