from decimal import Decimal

from django.core.exceptions import ValidationError as DomainValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.usuarios.validators import normalizar_cpf, validar_cpf
from apps.fidelidade.calculos_resgate import MAX_PONTOS_RESGATE


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


class IdentificadorResgateField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError('Informe um identificador textual.')
        return super().to_internal_value(data)


class RegistrarCompraSerializer(serializers.Serializer):
    resgate_identificador_externo = IdentificadorResgateField(
        max_length=255, trim_whitespace=True, required=False,
        help_text='Resgate histórico da mesma Loja e Cliente, não estornado nem vinculado. O desconto vem do histórico.',
    )
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

    def to_internal_value(self, data):
        if isinstance(data, dict):
            extras = set(data) - set(self.fields)
            if extras:
                raise serializers.ValidationError({campo: 'Campo não permitido.' for campo in extras})
        return super().to_internal_value(data)

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


class FidelidadeCompraSerializer(serializers.Serializer):
    pontos_base = serializers.DecimalField(
        max_digits=24, decimal_places=4, coerce_to_string=True,
        help_text="Produto do valor elegível pela taxa aplicada, string com quatro casas decimais.",
    )
    pontos_concedidos = serializers.DecimalField(
        max_digits=24, decimal_places=4, coerce_to_string=True,
        help_text="Concessão após política da Empresa, string com quatro casas decimais.",
    )
    expira_em = serializers.DateTimeField()


class ResgateCompraSerializer(serializers.Serializer):
    identificador_externo = serializers.CharField()
    pontos_resgatados = serializers.IntegerField()
    valor_desconto = serializers.DecimalField(max_digits=32, decimal_places=2, coerce_to_string=True)


class ValoresCompraSerializer(serializers.Serializer):
    bruto = serializers.CharField()
    desconto_total = serializers.CharField()
    final = serializers.CharField()
    elegivel_pontos = serializers.CharField()


class PontosCompraSerializer(serializers.Serializer):
    base = serializers.CharField()
    apos_campanha = serializers.CharField()
    bonus_nivel = serializers.CharField()
    bonus_retorno = serializers.CharField()
    total = serializers.CharField()


class BeneficiosCompraSerializer(serializers.Serializer):
    nivel_desconto = serializers.CharField(allow_null=True)
    nivel_bonus = serializers.CharField(allow_null=True)
    beneficios_nivel_aplicaveis = serializers.BooleanField()
    retorno = serializers.BooleanField()
    bonus_nivel_percentual = serializers.CharField()
    desconto_nivel_percentual = serializers.CharField()
    bonus_retorno_percentual = serializers.CharField()
    desconto_retorno_percentual = serializers.CharField()
    multiplicador_campanha = serializers.CharField()
    ordem_aplicacao_resgate = serializers.CharField()
    base_calculo_pontos = serializers.CharField()


class ExplicacaoCompraSerializer(serializers.Serializer):
    valores = ValoresCompraSerializer()
    pontos = PontosCompraSerializer()
    beneficios = BeneficiosCompraSerializer()


class CompraSerializer(serializers.Serializer):
    resgate = ResgateCompraSerializer(allow_null=True)
    resumo = serializers.SerializerMethodField(help_text='Resultado histórico explicável; null para legado sem snapshot de benefícios.')

    @extend_schema_field(ExplicacaoCompraSerializer(allow_null=True))
    def get_resumo(self, compra):
        from apps.fidelidade.apresentacao_compras import explicar_compra
        return explicar_compra(compra)

    id = serializers.IntegerField()
    identificador_externo = serializers.CharField(max_length=255)
    loja = LojaCompraSerializer()
    cliente = ClienteCompraSerializer()
    valor = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=True)
    ocorrida_em = serializers.DateTimeField()
    criada_em = serializers.DateTimeField()
    fidelidade = FidelidadeCompraSerializer(
        source="lote_pontos", read_only=True, allow_null=True,
        help_text="Resultado histórico; decimais com quatro casas. Null para Compra legada sem Lote. Retry não recalcula.",
    )


@extend_schema_field({'type': 'integer', 'minimum': 1, 'maximum': MAX_PONTOS_RESGATE})
class PontosResgateField(serializers.IntegerField):
    def to_internal_value(self, data):
        if type(data) is not int:
            raise serializers.ValidationError('Envie pontos como inteiro JSON, sem float ou string.')
        return super().to_internal_value(data)


class RegistrarResgateSerializer(serializers.Serializer):
    loja_id = serializers.IntegerField(min_value=1)
    identificador_externo = IdentificadorResgateField(
        max_length=255, trim_whitespace=True,
        help_text='String não vazia após strip, case preservado; única por Loja.',
    )
    cliente_cpf = serializers.CharField(help_text='CPF válido de Cliente da Empresa da Loja, como na Compra.')
    pontos = PontosResgateField(
        min_value=1, max_value=MAX_PONTOS_RESGATE,
        help_text='Inteiro JSON positivo de até 20 dígitos. Não aceita float nem string.',
    )

    validate_cliente_cpf = RegistrarCompraSerializer.validate_cliente_cpf

    def to_internal_value(self, data):
        if isinstance(data, dict):
            extras = set(data) - set(self.fields)
            if extras:
                raise serializers.ValidationError({campo: 'Campo não permitido; Resgate não aceita backdating.' for campo in extras})
        return super().to_internal_value(data)


class ResgateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    identificador_externo = serializers.CharField(max_length=255)
    loja = LojaCompraSerializer()
    cliente = ClienteCompraSerializer()
    pontos_resgatados = PontosResgateField(min_value=1, max_value=MAX_PONTOS_RESGATE)
    valor_desconto = serializers.DecimalField(max_digits=32, decimal_places=2, coerce_to_string=True)
    resgatado_em = serializers.DateTimeField()


class ConsultaFidelidadeQuerySerializer(serializers.Serializer):
    loja_id = serializers.IntegerField(min_value=1)
    cliente_cpf = serializers.CharField()

    validate_cliente_cpf = RegistrarCompraSerializer.validate_cliente_cpf


class ClienteFidelidadeSerializer(serializers.Serializer):
    cpf = serializers.CharField()
    nome = serializers.CharField(allow_blank=True)


class AtividadeFidelidadeSerializer(serializers.Serializer):
    ativo = serializers.BooleanField()
    ultima_compra_em = serializers.DateTimeField(allow_null=True)
    periodo_cliente_ativo_dias = serializers.IntegerField(min_value=1)


class BeneficiosNivelConsultaSerializer(serializers.Serializer):
    bonus_pontos_percentual = serializers.CharField()
    desconto_percentual = serializers.CharField()
    aplicaveis = serializers.BooleanField()


class NivelAtualConsultaSerializer(serializers.Serializer):
    nome = serializers.CharField()
    pontos_minimos = serializers.CharField()
    beneficios = BeneficiosNivelConsultaSerializer()


class NivelConsultaSerializer(serializers.Serializer):
    pontos_historicos = serializers.CharField()
    atual = NivelAtualConsultaSerializer(allow_null=True)


class SaldoFidelidadeSerializer(serializers.Serializer):
    pontos = serializers.CharField()


class PromocaoRetornoConsultaSerializer(serializers.Serializer):
    aplicavel = serializers.BooleanField()
    bonus_pontos_percentual = serializers.CharField()
    desconto_percentual = serializers.CharField()


class DisponibilidadeResgateSerializer(serializers.Serializer):
    possivel = serializers.BooleanField(help_text='Há quantidade utilizável nas condições consultadas; não reserva saldo.')
    maximo_pontos = serializers.IntegerField(min_value=0)
    maximo_desconto = serializers.CharField(help_text='Equivalente monetário do máximo de pontos utilizável, com duas casas.')
    limite_resgate_percentual = serializers.CharField(help_text='Percentual corporativo sobre o valor bruto, com quatro casas.')


class ParametrosResgateConsultaSerializer(DisponibilidadeResgateSerializer):
    minimo_pontos = serializers.IntegerField(min_value=1)
    incremento_pontos = serializers.IntegerField(min_value=1)
    valor_monetario_por_ponto = serializers.CharField()


class FidelidadeClienteSerializer(serializers.Serializer):
    cliente = ClienteFidelidadeSerializer()
    atividade = AtividadeFidelidadeSerializer()
    nivel = NivelConsultaSerializer()
    saldo = SaldoFidelidadeSerializer()
    promocao_retorno = PromocaoRetornoConsultaSerializer()
    resgate = ParametrosResgateConsultaSerializer()


class SimularCompraSerializer(serializers.Serializer):
    loja_id = serializers.IntegerField(min_value=1)
    cliente_cpf = serializers.CharField(
        help_text="CPF válido de Cliente já vinculado à Empresa da Loja.",
    )
    valor = ValorCompraField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("9999999999.99"),
        help_text=(
            "String decimal positiva, até duas casas, entre 0.01 e "
            "9999999999.99. Não enviar float."
        ),
    )

    validate_cliente_cpf = RegistrarCompraSerializer.validate_cliente_cpf

    def to_internal_value(self, data):
        if isinstance(data, dict):
            extras = set(data) - set(self.fields)
            if extras:
                raise serializers.ValidationError(
                    {
                        campo: (
                            "Campo não permitido na simulação de Compra."
                        )
                        for campo in extras
                    },
                )
        return super().to_internal_value(data)


class NivelReferenciaSimulacaoSerializer(serializers.Serializer):
    nome = serializers.CharField()
    pontos_minimos = serializers.CharField()


class AtividadeSimulacaoSerializer(serializers.Serializer):
    ativo = serializers.BooleanField()
    retorno = serializers.BooleanField()
    ultima_compra_em = serializers.DateTimeField(allow_null=True)


class NivelSimulacaoSerializer(serializers.Serializer):
    atual = NivelReferenciaSimulacaoSerializer(allow_null=True)
    bonus_pontos = NivelReferenciaSimulacaoSerializer(allow_null=True)
    beneficios_aplicaveis = serializers.BooleanField()
    bonus_pontos_percentual = serializers.CharField()
    desconto_percentual = serializers.CharField()


class CampanhaSimulacaoSerializer(serializers.Serializer):
    aplicavel = serializers.BooleanField()
    nome = serializers.CharField(allow_null=True)
    multiplicador_pontos = serializers.CharField()


class ValoresSimulacaoSerializer(serializers.Serializer):
    bruto = serializers.CharField()
    desconto_total = serializers.CharField()
    final = serializers.CharField()
    elegivel_pontos = serializers.CharField()


class PontosSimulacaoSerializer(serializers.Serializer):
    base = serializers.CharField()
    apos_campanha = serializers.CharField()
    bonus_nivel = serializers.CharField()
    bonus_retorno = serializers.CharField()
    total_estimado = serializers.CharField()


class SimulacaoCompraSerializer(serializers.Serializer):
    saldo = SaldoFidelidadeSerializer()
    resgate = DisponibilidadeResgateSerializer()
    cliente = ClienteFidelidadeSerializer()
    simulada_em = serializers.DateTimeField()
    atividade = AtividadeSimulacaoSerializer()
    nivel = NivelSimulacaoSerializer()
    campanha = CampanhaSimulacaoSerializer()
    promocao_retorno = PromocaoRetornoConsultaSerializer()
    valores = ValoresSimulacaoSerializer()
    pontos = PontosSimulacaoSerializer()


class SimularResgateSerializer(serializers.Serializer):
    loja_id = serializers.IntegerField(min_value=1)
    cliente_cpf = serializers.CharField()
    pontos = PontosResgateField(min_value=1, max_value=MAX_PONTOS_RESGATE)

    validate_cliente_cpf = RegistrarCompraSerializer.validate_cliente_cpf

    def to_internal_value(self, data):
        if isinstance(data, dict):
            extras = set(data) - set(self.fields)
            if extras:
                raise serializers.ValidationError({
                    campo: 'Campo não permitido na simulação de Resgate.' for campo in extras
                })
        return super().to_internal_value(data)


class SaldoSimulacaoResgateSerializer(serializers.Serializer):
    atual = serializers.CharField()
    projetado = serializers.CharField()


class SimulacaoResgateSerializer(serializers.Serializer):
    cliente = ClienteFidelidadeSerializer()
    simulada_em = serializers.DateTimeField()
    pontos_resgatados = PontosResgateField(min_value=1, max_value=MAX_PONTOS_RESGATE)
    valor_desconto = serializers.DecimalField(max_digits=32, decimal_places=2, coerce_to_string=True)
    saldo = SaldoSimulacaoResgateSerializer()


class EstornarResgateSerializer(serializers.Serializer):
    loja_id = serializers.IntegerField(min_value=1)
    resgate_identificador_externo = IdentificadorResgateField(max_length=255, trim_whitespace=True)
    identificador_externo = IdentificadorResgateField(max_length=255, trim_whitespace=True)

    def to_internal_value(self, data):
        if isinstance(data, dict):
            extras = set(data) - set(self.fields)
            if extras:
                raise serializers.ValidationError({campo: 'Campo não permitido no estorno.' for campo in extras})
        return super().to_internal_value(data)


class EstornoResgateSerializer(serializers.Serializer):
    identificador_externo = serializers.CharField(max_length=255)
    resgate_identificador_externo = serializers.CharField(source='resgate.identificador_externo')
    loja = LojaCompraSerializer()
    cliente = ClienteCompraSerializer()
    pontos_estornados = PontosResgateField(source='resgate.pontos_resgatados', min_value=1, max_value=MAX_PONTOS_RESGATE)
    valor_desconto_original = serializers.DecimalField(
        source='resgate.valor_desconto', max_digits=32, decimal_places=2, coerce_to_string=True,
    )
    devolve_pontos_aplicado = serializers.BooleanField()
    estornado_em = serializers.DateTimeField()
