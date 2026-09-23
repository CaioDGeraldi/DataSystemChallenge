from datetime import datetime
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.empresas.models import CredencialIntegracao, Loja
from apps.empresas.parametros import MODOS_ARREDONDAMENTO_PONTOS, PRECISOES_PONTOS

from .calculos import calcular_expiracao, calcular_pontos


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


class LotePontos(models.Model):
    compra = models.OneToOneField(Compra, on_delete=models.PROTECT, related_name="lote_pontos")
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="lotes_pontos")
    pontos_base = models.DecimalField(max_digits=24, decimal_places=4, validators=[MinValueValidator(Decimal("0"))])
    pontos_concedidos = models.DecimalField(max_digits=24, decimal_places=4, validators=[MinValueValidator(Decimal("0"))])
    pontos_por_real_aplicado = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    precisao_pontos_aplicada = models.PositiveIntegerField(choices=[(v, str(v)) for v in PRECISOES_PONTOS])
    modo_arredondamento_aplicado = models.CharField(max_length=7, choices=[(v, v) for v in MODOS_ARREDONDAMENTO_PONTOS])
    validade_pontos_meses_aplicada = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    adquiridos_em = models.DateTimeField()
    expira_em = models.DateTimeField()
    criado_em = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(pontos_base__gte=0), name="lote_base_nao_negativa"),
            models.CheckConstraint(condition=models.Q(pontos_concedidos__gte=0), name="lote_concessao_nao_negativa"),
            models.CheckConstraint(condition=models.Q(pontos_por_real_aplicado__gte=0), name="lote_taxa_nao_negativa"),
            models.CheckConstraint(condition=models.Q(precisao_pontos_aplicada__in=[0, 1, 2, 4]), name="lote_precisao_valida"),
            models.CheckConstraint(condition=models.Q(modo_arredondamento_aplicado__in=["HALF_UP", "DOWN", "UP"]), name="lote_arredondamento_valido"),
            models.CheckConstraint(condition=models.Q(validade_pontos_meses_aplicada__gt=0), name="lote_validade_positiva"),
        ]

    def clean_fields(self, exclude=None):
        erros = {}
        for campo in ("pontos_base", "pontos_concedidos", "pontos_por_real_aplicado"):
            if campo not in (exclude or ()) and not isinstance(getattr(self, campo), Decimal):
                erros[campo] = "Informe um Decimal, sem conversão de float."
        for campo in ("precisao_pontos_aplicada", "validade_pontos_meses_aplicada"):
            if campo not in (exclude or ()) and type(getattr(self, campo)) is not int:
                erros[campo] = "Informe um número inteiro."
        for campo in ("adquiridos_em", "expira_em", "criado_em"):
            valor = getattr(self, campo)
            if campo not in (exclude or ()) and (not isinstance(valor, datetime) or timezone.is_naive(valor)):
                erros[campo] = "Informe uma data/hora com timezone."
        if erros:
            raise ValidationError(erros)
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        # full_clean chama clean mesmo após erros de campos. Comparações e cálculos
        # precisam de tipos válidos (inclusive para Decimal não finito).
        self.clean_fields()
        campos = tuple(campo.name for campo in self._meta.fields if not campo.primary_key)
        if self.pk is not None:
            original = type(self)._base_manager.using(self._state.db).filter(pk=self.pk).values(*campos).first()
            if original is not None:
                erros = {
                    campo: "O fato histórico não pode ser alterado após a criação."
                    for campo in campos
                    if getattr(self, self._meta.get_field(campo).attname) != original[campo]
                }
                if erros:
                    raise ValidationError(erros)
                return
        # Validar dados persistidos, sem confiar em relações adulteradas em memória.
        compra = Compra.objects.select_related("cliente", "loja").filter(pk=self.compra_id).first()
        if compra is None:
            return  # A validação do FK informa a ausência da Compra.
        if self.cliente_id != compra.cliente_id or compra.cliente.empresa_id != compra.loja.empresa_id:
            raise ValidationError({"cliente": "O Cliente deve ser o mesmo da Compra e pertencer à Empresa da Loja."})
        base, concedidos = calcular_pontos(
            compra.valor, self.pontos_por_real_aplicado,
            self.precisao_pontos_aplicada, self.modo_arredondamento_aplicado,
        )
        esperados = {
            "pontos_base": base, "pontos_concedidos": concedidos,
            "adquiridos_em": compra.ocorrida_em,
            "expira_em": calcular_expiracao(compra.ocorrida_em, self.validade_pontos_meses_aplicada),
        }
        erros = {campo: "O valor deve corresponder à Compra e aos snapshots aplicados."
                 for campo, valor in esperados.items() if getattr(self, campo) != valor}
        if erros:
            raise ValidationError(erros)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
