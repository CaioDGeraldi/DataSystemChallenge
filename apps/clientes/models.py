from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Cliente(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="clientes"
    )
    empresa = models.ForeignKey(
        "empresas.Empresa", on_delete=models.PROTECT, related_name="clientes"
    )
    cadastrado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["usuario", "empresa"], name="cliente_usuario_empresa_unico")
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
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.usuario.get_full_name()} — {self.empresa}"
