"""Valores padrão e contratos tipados da política de fidelidade do MVP."""
from dataclasses import dataclass
from decimal import Decimal


PRECISOES_PONTOS = (0, 1, 2, 4)
MODOS_ARREDONDAMENTO_PONTOS = ("HALF_UP", "DOWN", "UP")


@dataclass(frozen=True)
class ParametrosFidelidade:
    limite_resgate_percentual: Decimal
    devolver_pontos_ao_estornar_resgate: bool
    precisao_pontos: int
    modo_arredondamento_pontos: str
    pontos_por_real: Decimal
    validade_pontos_meses: int
    resgate_minimo_pontos: int
    incremento_resgate_pontos: int
    valor_monetario_por_ponto: Decimal
    periodo_cliente_ativo_dias: int
    inatividade_suspende_beneficios_nivel: bool
    promocao_retorno_ativa: bool
    beneficio_primeira_compra_apos_inatividade: str
    modo_combinacao_descontos_percentuais: str
    ordem_aplicacao_resgate: str
    base_calculo_pontos: str
    modo_aplicacao_nivel: str
    bonus_pontos_retorno_percentual: Decimal
    desconto_retorno_percentual: Decimal



PADROES_FIDELIDADE = ParametrosFidelidade(
    limite_resgate_percentual=Decimal("100.0000"),
    devolver_pontos_ao_estornar_resgate=True,
    precisao_pontos=2,
    modo_arredondamento_pontos="HALF_UP",
    pontos_por_real=Decimal("1.00"),
    validade_pontos_meses=12,
    resgate_minimo_pontos=100,
    incremento_resgate_pontos=100,
    valor_monetario_por_ponto=Decimal("0.05"),
    periodo_cliente_ativo_dias=180,
    inatividade_suspende_beneficios_nivel=False,
    promocao_retorno_ativa=False,
    beneficio_primeira_compra_apos_inatividade='SEM_BENEFICIOS_NIVEL',
    modo_combinacao_descontos_percentuais='ADITIVO',
    ordem_aplicacao_resgate='DEPOIS_DOS_DESCONTOS_PERCENTUAIS',
    base_calculo_pontos='BRUTO',
    modo_aplicacao_nivel='ANTES_DA_COMPRA',
    bonus_pontos_retorno_percentual=Decimal("0.0000"),
    desconto_retorno_percentual=Decimal("0.0000"),
)


@dataclass(frozen=True)
class ConfiguracaoEfetiva(ParametrosFidelidade):
    empresa_id: int
    loja_id: int | None
