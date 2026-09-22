from django.conf import settings
from django.db import models


class Cliente(models.Model):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cliente"
    )
    empresa = models.ForeignKey(
        "empresas.Empresa", on_delete=models.PROTECT, related_name="clientes"
    )
    cadastrado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.usuario.get_full_name()} — {self.empresa}"
