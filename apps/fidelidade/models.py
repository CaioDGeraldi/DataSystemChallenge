from datetime import datetime
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.empresas.models import CredencialIntegracao, Loja


class Compra(models.Model):
    loja = models.ForeignKey(Loja, on_delete=models.PROTECT, related_name="compras")
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="compras")
    credencial_origem = models.ForeignKey(CredencialIntegracao, on_delete=models.PROTECT, related_name="compras")
    identificador_externo = models.CharField(max_length=255)
    valor = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    ocorrida_em = models.DateTimeField()
    criada_em = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["loja", "identificador_externo"], name="compra_loja_identificador_unico"),
            models.CheckConstraint(condition=models.Q(valor__gt=0), name="compra_valor_positivo"),
        ]

    def clean_fields(self, exclude=None):
        erros = {}
        if "identificador_externo" not in (exclude or ()):
            if isinstance(self.identificador_externo, str):
                self.identificador_externo = self.identificador_externo.strip()
            else:
                erros["identificador_externo"] = "Informe um identificador textual."
        if "valor" not in (exclude or ()) and not isinstance(self.valor, Decimal):
            erros["valor"] = "Informe um Decimal, sem conversão de float."
        if "ocorrida_em" not in (exclude or ()):
            if not isinstance(self.ocorrida_em, datetime) or timezone.is_naive(self.ocorrida_em):
                erros["ocorrida_em"] = "Informe uma data/hora com timezone."
        if erros:
            raise ValidationError(erros)
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        if self.pk is not None:
            campos = (
                "loja", "cliente", "credencial_origem", "identificador_externo",
                "valor", "ocorrida_em", "criada_em",
            )
            original = type(self)._base_manager.using(self._state.db).filter(pk=self.pk).values(*campos).first()
            if original is not None:
                erros = {
                    campo: "O fato histórico não pode ser alterado após a criação."
                    for campo in campos
                    if getattr(self, self._meta.get_field(campo).attname) != original[campo]
                }
                if erros:
                    raise ValidationError(erros)
                # Histórico inalterado não depende da autorização atual da credencial.
                return
        loja = Loja.objects.filter(pk=self.loja_id).first()
        cliente = Cliente.objects.filter(pk=self.cliente_id).first()
        credencial = CredencialIntegracao.objects.filter(pk=self.credencial_origem_id).first()
        if loja is not None and cliente is not None and loja.empresa_id != cliente.empresa_id:
            raise ValidationError({"cliente": "Cliente e Loja devem pertencer à mesma Empresa."})
        if loja is not None and credencial is not None:
            if loja.empresa_id != credencial.empresa_id:
                raise ValidationError({"credencial_origem": "A credencial deve pertencer à Empresa da Loja."})
            from apps.empresas.services import exigir_loja_autorizada

            try:
                exigir_loja_autorizada(credencial, loja)
            except PermissionDenied:
                raise ValidationError({"credencial_origem": "Credencial não autorizada para a Loja."}) from None

    def save(self, *args, **kwargs):
        # A unicidade concorrente é arbitrada pelo INSERT/constraint SQL, não por SELECT prévio.
        # O valor positivo também é validado pelos validators do campo.
        self.full_clean(validate_constraints=False)
        return super().save(*args, **kwargs)
