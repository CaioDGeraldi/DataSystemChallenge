from django.conf import settings
from django.core.exceptions import ValidationError
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

    def clean(self):
        super().clean()
        if self.pk is not None:
            empresa_original = (
                type(self)._base_manager.using(self._state.db)
                .filter(pk=self.pk).values_list("empresa_id", flat=True).first()
            )
            if empresa_original is not None and self.empresa_id != empresa_original:
                raise ValidationError({"empresa": "A Empresa não pode ser alterada após a criação."})

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nome} ({self.cidade})"


class MembroEmpresa(models.Model):
    class Papel(models.TextChoices):
        ADMINISTRADOR = "ADMINISTRADOR", "Administrador"
        GESTOR = "GESTOR", "Gestor"

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="membros_empresas"
    )
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="membros")
    papel = models.CharField(max_length=13, choices=Papel.choices)
    ativo = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["usuario", "empresa"], name="membro_usuario_empresa_unico")
        ]

    def clean(self):
        super().clean()
        if self.pk is not None:
            empresa_original = (
                type(self)._base_manager.using(self._state.db)
                .filter(pk=self.pk).values_list("empresa_id", flat=True).first()
            )
            if empresa_original is not None and self.empresa_id != empresa_original:
                raise ValidationError({"empresa": "A Empresa não pode ser alterada após a criação."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.usuario.get_full_name()} — {self.empresa}"


class AcessoLoja(models.Model):
    membro = models.ForeignKey(MembroEmpresa, on_delete=models.PROTECT, related_name="acessos_lojas")
    loja = models.ForeignKey(Loja, on_delete=models.PROTECT, related_name="acessos_membros")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["membro", "loja"], name="acesso_membro_loja_unico")
        ]

    def clean(self):
        super().clean()
        if self.membro_id and self.loja_id:
            membro_empresa = MembroEmpresa.objects.filter(pk=self.membro_id).values_list("empresa_id", flat=True).first()
            loja_empresa = Loja.objects.filter(pk=self.loja_id).values_list("empresa_id", flat=True).first()
            if membro_empresa is not None and loja_empresa is not None and membro_empresa != loja_empresa:
                raise ValidationError({"loja": "A Loja deve pertencer à mesma Empresa do membro."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.membro} — {self.loja}"
