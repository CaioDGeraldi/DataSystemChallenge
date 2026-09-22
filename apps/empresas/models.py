from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.usuarios.validators import normalizar_cpf, validar_cpf

from .validators import normalizar_cnpj, validar_cnpj


class Empresa(models.Model):
    nome = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    cnpj = models.CharField("CNPJ", max_length=14, unique=True, validators=[validar_cnpj])
    criado_em = models.DateTimeField(auto_now_add=True)

    def clean(self):
        self.cnpj = normalizar_cnpj(self.cnpj)
        super().clean()
        if self.pk is not None:
            original = type(self)._base_manager.using(self._state.db).filter(pk=self.pk).values_list("slug", flat=True).first()
            if original is not None and self.slug != original:
                raise ValidationError({"slug": "O slug não pode ser alterado após a criação."})

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


class ConviteMembro(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="convites")
    cpf = models.CharField("CPF", max_length=11, validators=[validar_cpf])
    papel = models.CharField(max_length=13, choices=MembroEmpresa.Papel.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    criado_por = models.ForeignKey(MembroEmpresa, on_delete=models.PROTECT, related_name="convites_criados")
    criado_em = models.DateTimeField(default=timezone.now, editable=False)
    expira_em = models.DateTimeField(editable=False)
    aceito_em = models.DateTimeField(null=True, blank=True)
    revogado_em = models.DateTimeField(null=True, blank=True)

    @property
    def estado(self):
        if self.aceito_em is not None:
            return "aceito"
        if self.revogado_em is not None:
            return "revogado"
        if timezone.now() >= self.expira_em:
            return "expirado"
        return "pendente"

    @property
    def pode_revogar(self):
        return self.estado == "pendente"

    def clean(self):
        super().clean()
        self.cpf = normalizar_cpf(self.cpf)
        if self.criado_por_id and self.empresa_id:
            empresa = MembroEmpresa.objects.filter(pk=self.criado_por_id).values_list("empresa_id", flat=True).first()
            if empresa is not None and empresa != self.empresa_id:
                raise ValidationError({"criado_por": "O criador deve pertencer à Empresa do convite."})
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).values_list("empresa_id", flat=True).first()
            if original is not None and original != self.empresa_id:
                raise ValidationError({"empresa": "A Empresa não pode ser alterada após a criação."})
            if self.papel != MembroEmpresa.Papel.GESTOR and self.acessos_lojas.exists():
                raise ValidationError({"papel": "Somente convites de Gestor podem possuir Lojas."})

    def save(self, *args, **kwargs):
        self.cpf = normalizar_cpf(self.cpf)
        if self._state.adding and self.expira_em is None:
            self.expira_em = self.criado_em + timedelta(days=7)
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Convite {self.pk} — {self.empresa} ({self.get_papel_display()})"


class ConviteAcessoLoja(models.Model):
    convite = models.ForeignKey(ConviteMembro, on_delete=models.PROTECT, related_name="acessos_lojas")
    loja = models.ForeignKey(Loja, on_delete=models.PROTECT, related_name="acessos_convites")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["convite", "loja"], name="convite_loja_unico")
        ]

    def clean(self):
        super().clean()
        convite = ConviteMembro.objects.filter(pk=self.convite_id).first()
        loja_empresa = Loja.objects.filter(pk=self.loja_id).values_list("empresa_id", flat=True).first()
        if convite is not None:
            if convite.papel != MembroEmpresa.Papel.GESTOR:
                raise ValidationError({"convite": "Somente convites de Gestor recebem Lojas."})
            if loja_empresa is not None and loja_empresa != convite.empresa_id:
                raise ValidationError({"loja": "A Loja deve pertencer à Empresa do convite."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
