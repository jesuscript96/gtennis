from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Only Super Admins and Coaches log in. Players never authenticate
    (they are passive data managed by their coach / the Super Admin).
    """

    class Role(models.TextChoices):
        SUPERADMIN = "SUPERADMIN", "Super Administrador"
        COACH = "COACH", "Coach"
        ENTRENADOR = "ENTRENADOR", "Entrenador"

    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.ENTRENADOR
    )

    @property
    def is_superadmin(self):
        return self.role == self.Role.SUPERADMIN or self.is_superuser

    @property
    def is_coach(self):
        """Rol intermedio (#16): por encima del entrenador, por debajo de la
        dirección. No incluye a los Super Admin (usa is_direccion para 've todo')."""
        return self.role == self.Role.COACH and not self.is_superadmin

    @property
    def is_direccion(self):
        """Dirección deportiva: puede crear coaches y ve todo. Hoy = Super Admin."""
        return self.is_superadmin

    def __str__(self):
        return self.get_full_name() or self.username
