from django.contrib.auth.models import UserManager
from django.core.exceptions import ValidationError

from .validators import normalizar_cpf


class UsuarioManager(UserManager):
    def get_by_natural_key(self, cpf):
        try:
            cpf_normalizado = normalizar_cpf(cpf)
        except ValidationError as exc:
            raise self.model.DoesNotExist() from exc
        return self.get(**{self.model.USERNAME_FIELD: cpf_normalizado})

    def create_user(self, cpf, password=None, **extra_fields):
        usuario = self.model(cpf=normalizar_cpf(cpf), **extra_fields)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_superuser(self, cpf, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields["is_staff"] is not True:
            raise ValueError("O superusuário deve ter is_staff=True.")
        if extra_fields["is_superuser"] is not True:
            raise ValueError("O superusuário deve ter is_superuser=True.")

        return self.create_user(cpf, password, **extra_fields)
