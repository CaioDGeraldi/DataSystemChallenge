from decimal import Decimal

from django.core.exceptions import ValidationError as DomainValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers

from apps.usuarios.validators import normalizar_cpf, validar_cpf


class HealthSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["ok"])


class CredencialSerializer(serializers.Serializer):
    identificador = serializers.CharField()
    nome = serializers.CharField()


class EmpresaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()


class LojaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()
    cidade = serializers.CharField()


class ContextoSerializer(serializers.Serializer):
    credencial = CredencialSerializer()
    empresa = EmpresaSerializer()
    escopo = serializers.ChoiceField(choices=["EMPRESA", "LOJAS"])
    lojas = LojaSerializer(many=True)


class ErroSerializer(serializers.Serializer):
    codigo = serializers.CharField()
    mensagem = serializers.CharField()
    detalhes = serializers.JSONField(required=False)


class EnvelopeErroSerializer(serializers.Serializer):
    erro = ErroSerializer()


class ValorCompraField(serializers.DecimalField):
    def to_internal_value(self, data):
        if isinstance(data, (float, bool)):
            raise serializers.ValidationError("Envie o valor monetário como string decimal, sem float.")
        return super().to_internal_value(data)


class InstanteCompraField(serializers.DateTimeField):
    def to_internal_value(self, data):
        try:
            instante = parse_datetime(data) if isinstance(data, str) else None
        except ValueError:
            instante = None
        # DateTimeField normalmente atribui o timezone padrão a entradas naive.
        if instante is None or timezone.is_naive(instante):
            raise serializers.ValidationError("Informe data/hora ISO 8601 com timezone.")
        return super().to_internal_value(data)


class RegistrarCompraSerializer(serializers.Serializer):
    loja_id = serializers.IntegerField(min_value=1)
    identificador_externo = serializers.CharField(
        max_length=255, trim_whitespace=True,
        help_text="Até 255 caracteres após strip; preserva case e conteúdo interno. Único por Loja.",
    )
    cliente_cpf = serializers.CharField(help_text="CPF válido de Cliente já vinculado à Empresa da Loja.")
    valor = ValorCompraField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01"), max_value=Decimal("9999999999.99"),
        help_text="String decimal positiva, até duas casas, entre 0.01 e 9999999999.99. Não enviar float.",
    )
    ocorrida_em = InstanteCompraField(input_formats=["iso-8601"], help_text="ISO 8601 com timezone explícito.")

    def validate_cliente_cpf(self, value):
        try:
            cpf = normalizar_cpf(value)
            validar_cpf(cpf)
        except DomainValidationError:
            raise serializers.ValidationError("CPF inválido.") from None
        return cpf


class LojaCompraSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()


class ClienteCompraSerializer(serializers.Serializer):
    cpf = serializers.CharField(source="usuario.cpf")


class CompraSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    identificador_externo = serializers.CharField(max_length=255)
    loja = LojaCompraSerializer()
    cliente = ClienteCompraSerializer()
    valor = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=True)
    ocorrida_em = serializers.DateTimeField()
    criada_em = serializers.DateTimeField()
