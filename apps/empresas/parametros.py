"""Valores padrão e contratos tipados da política de fidelidade do MVP."""
from dataclasses import dataclass
from decimal import Decimal


PRECISOES_PONTOS = (0, 1, 2, 4)
MODOS_ARREDONDAMENTO_PONTOS = ("HALF_UP", "DOWN", "UP")


@dataclass(frozen=True)
class ParametrosFidelidade:
    precisao_pontos: int
    modo_arredondamento_pontos: str
    pontos_por_real: Decimal
    validade_pontos_meses: int
    resgate_minimo_pontos: int
    incremento_resgate_pontos: int
    valor_monetario_por_ponto: Decimal
    periodo_cliente_ativo_dias: int


PADROES_FIDELIDADE = ParametrosFidelidade(
    precisao_pontos=2,
    modo_arredondamento_pontos="HALF_UP",
    pontos_por_real=Decimal("1.00"),
    validade_pontos_meses=12,
    resgate_minimo_pontos=100,
    incremento_resgate_pontos=100,
    valor_monetario_por_ponto=Decimal("0.05"),
    periodo_cliente_ativo_dias=180,
)


@dataclass(frozen=True)
class ConfiguracaoEfetiva(ParametrosFidelidade):
    empresa_id: int
    loja_id: int | None
