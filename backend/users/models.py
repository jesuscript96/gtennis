from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Only Super Admins and Coaches log in. Players never authenticate
    (they are passive data managed by their coach / the Super Admin).
    """

    class Role(models.TextChoices):
        SUPERADMIN = "SUPERADMIN", "Super Administrador"
        ENTRENADOR = "ENTRENADOR", "Entrenador"

    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.ENTRENADOR
    )

    @property
    def is_superadmin(self):
        return self.role == self.Role.SUPERADMIN or self.is_superuser

    def __str__(self):
        return self.get_full_name() or self.username
