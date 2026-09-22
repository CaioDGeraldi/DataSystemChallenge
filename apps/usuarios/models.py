from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UsuarioManager
from .validators import normalizar_cpf, validar_cpf


class Usuario(AbstractUser):
    username = None
    cpf = models.CharField("CPF", max_length=11, unique=True, validators=[validar_cpf])

    USERNAME_FIELD = "cpf"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UsuarioManager()

    def clean(self):
        self.cpf = normalizar_cpf(self.cpf)
        super().clean()

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
