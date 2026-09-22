from django.conf import settings
from django.db import models

from .validators import normalizar_cnpj, validar_cnpj


class Empresa(models.Model):
    nome = models.CharField(max_length=255)
    cnpj = models.CharField("CNPJ", max_length=14, unique=True, validators=[validar_cnpj])
    criado_em = models.DateTimeField(auto_now_add=True)

    def clean(self):
        self.cnpj = normalizar_cnpj(self.cnpj)
        super().clean()

    def save(self, *args, **kwargs):
        # Normalizar antes da validação de max_length e unicidade dos campos.
        self.cnpj = normalizar_cnpj(self.cnpj)
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.nome


class Loja(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="lojas")
    nome = models.CharField(max_length=255)
    cidade = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.nome} ({self.cidade})"


class Gestor(models.Model):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="gestor"
    )
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="gestores")

    def __str__(self):
        return f"{self.usuario.get_full_name()} — {self.empresa}"
