"""Avaliação única de benefícios, sem escrita e sem dependência do contexto Decimal global."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext

from django.core.exceptions import ValidationError
from django.core.validators import DecimalValidator
from django.utils import timezone

from apps.empresas.parametros import ParametrosFidelidade
from .calculos import ARREDONDAMENTOS, calcular_pontos

ZERO = Decimal('0')


def decimal_valido(valor, *, digitos=None, casas=None, percentual=False):
    if not isinstance(valor, Decimal) or not valor.is_finite() or valor < 0:
        raise ValidationError('Informe Decimal finito e não negativo.')
    if percentual and valor > 100:
        raise ValidationError('Percentuais devem estar entre 0 e 100.')
    if digitos is not None:
        DecimalValidator(digitos, casas)(valor)


@dataclass(frozen=True)
class NivelBeneficios:
    id: int
    nome: str
    pontos_minimos: Decimal
    bonus_pontos_percentual: Decimal
    desconto_percentual: Decimal


@dataclass(frozen=True)
class AvaliacaoFidelidade:
    nivel_anterior: NivelBeneficios | None
    nivel_bonus: NivelBeneficios | None
    ativo_antes: bool
    retorno: bool
    beneficios_nivel_aplicaveis: bool
    bonus_nivel: Decimal
    desconto_nivel: Decimal
    bonus_retorno: Decimal
    desconto_retorno: Decimal
    valor_final: Decimal
    valor_elegivel_pontos: Decimal
    pontos_base: Decimal
    pontos_campanha: Decimal
    pontos_bonus_nivel: Decimal
    pontos_bonus_retorno: Decimal
    pontos_concedidos: Decimal


def avaliar_fidelidade_compra(
    *,
    valor,
    politica,
    instante,
    ultima_compra,
    progresso,
    niveis,
    multiplicador=Decimal('1.0000'),
    desconto_resgate=Decimal('0.00'),
):
    decimal_valido(valor, digitos=12, casas=2)
    decimal_valido(desconto_resgate, digitos=32, casas=2)
    decimal_valido(progresso)
    if not isinstance(instante, datetime) or timezone.is_naive(instante):
        raise ValidationError('Informe instante com timezone.')
    if ultima_compra is not None and (
        not isinstance(ultima_compra, datetime)
        or timezone.is_naive(ultima_compra)
        or ultima_compra > instante
    ):
        raise ValidationError(
            'Última Compra deve ser anterior ou simultânea à operação.',
        )
    if (
        type(politica.periodo_cliente_ativo_dias) is not int
        or politica.periodo_cliente_ativo_dias < 1
    ):
        raise ValidationError('Período de atividade inválido.')
    escolhas = {
        'base_calculo_pontos': ('BRUTO', 'LIQUIDO'),
        'modo_aplicacao_nivel': ('ANTES_DA_COMPRA', 'ATINGIDO_NA_COMPRA'),
        'modo_combinacao_descontos_percentuais': ('ADITIVO', 'SEQUENCIAL'),
        'ordem_aplicacao_resgate': (
            'ANTES_DOS_DESCONTOS_PERCENTUAIS',
            'DEPOIS_DOS_DESCONTOS_PERCENTUAIS',
        ),
        'beneficio_primeira_compra_apos_inatividade': (
            'SEM_BENEFICIOS_NIVEL',
            'COM_BENEFICIOS_NIVEL',
        ),
    }
    for campo, valores in escolhas.items():
        if getattr(politica, campo) not in valores:
            raise ValidationError(f'Política inválida: {campo}.')
    for campo in ('inatividade_suspende_beneficios_nivel', 'promocao_retorno_ativa'):
        if type(getattr(politica, campo)) is not bool:
            raise ValidationError(f'Informe booleano: {campo}.')
    for percentual in (
        politica.bonus_pontos_retorno_percentual,
        politica.desconto_retorno_percentual,
    ):
        decimal_valido(percentual, digitos=7, casas=4, percentual=True)
    niveis = sorted(niveis, key=lambda n: n.pontos_minimos)
    for nivel in niveis:
        decimal_valido(nivel.pontos_minimos, digitos=24, casas=4)
        for percentual in (nivel.bonus_pontos_percentual, nivel.desconto_percentual):
            decimal_valido(percentual, digitos=7, casas=4, percentual=True)

    def classificar(total):
        return next((n for n in reversed(niveis) if n.pontos_minimos <= total), None)

    # Diferença de instantes evita overflow ao somar dias a datas extremas.
    ativo = (
        ultima_compra is not None
        and (instante - ultima_compra) <= timedelta(
            days=min(politica.periodo_cliente_ativo_dias, 999999999),
        )
    )
    retorno = ultima_compra is not None and not ativo
    aplicavel = (
        ultima_compra is None
        or not politica.inatividade_suspende_beneficios_nivel
        or ativo
        or (
            retorno
            and politica.beneficio_primeira_compra_apos_inatividade
            == 'COM_BENEFICIOS_NIVEL'
        )
    )
    anterior = classificar(progresso)
    dn = anterior.desconto_percentual if anterior and aplicavel else ZERO
    br = (
        politica.bonus_pontos_retorno_percentual
        if retorno and politica.promocao_retorno_ativa
        else ZERO
    )
    dr = (
        politica.desconto_retorno_percentual
        if retorno and politica.promocao_retorno_ativa
        else ZERO
    )
    with localcontext(
        Context(
            prec=max(60, len(progresso.as_tuple().digits) + 40),
            rounding=ROUND_HALF_UP,
        ),
    ):
        valor = valor.quantize(Decimal(".01"))
        restante = valor
        if politica.ordem_aplicacao_resgate == 'ANTES_DOS_DESCONTOS_PERCENTUAIS':
            restante = max(ZERO, restante - desconto_resgate)
        if politica.modo_combinacao_descontos_percentuais == 'ADITIVO':
            restante *= 1 - min(Decimal('100'), dn + dr) / 100
        else:
            restante *= (1 - dn / 100) * (1 - dr / 100)
        if politica.ordem_aplicacao_resgate == 'DEPOIS_DOS_DESCONTOS_PERCENTUAIS':
            restante = max(ZERO, restante - desconto_resgate)
        final = restante.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        elegivel = max(ZERO, valor - desconto_resgate) if politica.base_calculo_pontos == 'BRUTO' else final
        base, _ = calcular_pontos(
            elegivel,
            politica.pontos_por_real,
            politica.precisao_pontos,
            politica.modo_arredondamento_pontos,
            multiplicador,
        )
        campanha = base * multiplicador
        nivel_bonus = (
            anterior
            if politica.modo_aplicacao_nivel == 'ANTES_DA_COMPRA'
            else classificar(progresso + campanha)
        )
        bn = (
            nivel_bonus.bonus_pontos_percentual
            if nivel_bonus and aplicavel
            else ZERO
        )
        pontos_nivel, pontos_retorno = base * bn / 100, base * br / 100
        total = (campanha + pontos_nivel + pontos_retorno).quantize(
            Decimal(1).scaleb(-politica.precisao_pontos),
            rounding=ARREDONDAMENTOS[politica.modo_arredondamento_pontos],
        )
        total = total.quantize(Decimal('.0001'))
        decimal_valido(total, digitos=24, casas=4)
        return AvaliacaoFidelidade(
            anterior,
            nivel_bonus,
            ativo,
            retorno,
            aplicavel,
            bn,
            dn,
            br,
            dr,
            final,
            elegivel,
            base,
            campanha,
            pontos_nivel,
            pontos_retorno,
            total,
        )


def _json(valor):
    if isinstance(valor, (Decimal, datetime)):
        return str(valor) if isinstance(valor, Decimal) else valor.isoformat()
    if isinstance(valor, dict):
        return {k: _json(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_json(v) for v in valor]
    return valor


def snapshot_beneficios(avaliacao, politica, progresso, ultima_compra, *, desconto_resgate=Decimal("0.00"), versao=2):
    # Só os dois níveis efetivamente considerados; não guarda catálogo/configuração futura.
    niveis = {
        n.id: asdict(n)
        for n in (avaliacao.nivel_anterior, avaliacao.nivel_bonus)
        if n
    }
    # Estorno não participa da Compra; v1 preserva o formato anterior ao limite.
    campos = (
        nome for nome in ParametrosFidelidade.__dataclass_fields__
        if nome != 'devolver_pontos_ao_estornar_resgate'
        and (versao >= 2 or nome != 'limite_resgate_percentual')
    )
    return _json(
        {
            'versao': versao,
            **({'desconto_resgate': desconto_resgate} if versao >= 2 else {}),
            'politica': {k: getattr(politica, k) for k in campos},
            'progresso_anterior': progresso,
            'ultima_compra': ultima_compra,
            'niveis': list(niveis.values()),
            'resultado': asdict(avaliacao),
        },
    )


def reavaliar_snapshot(snapshot, valor, instante, multiplicador):
    try:
        if snapshot['versao'] not in (1, 2):
            raise ValueError
        dados = dict(snapshot['politica'])
        # Campo novo sem efeito no cálculo de Compra e ausente no histórico v1.
        dados['devolver_pontos_ao_estornar_resgate'] = True
        dados['limite_resgate_percentual'] = Decimal(dados.get('limite_resgate_percentual', '100.0000'))
        for campo in (
            'pontos_por_real',
            'valor_monetario_por_ponto',
            'bonus_pontos_retorno_percentual',
            'desconto_retorno_percentual',
        ):
            dados[campo] = Decimal(dados[campo])
        politica = ParametrosFidelidade(**dados)
        niveis = [
            NivelBeneficios(
                **{
                    k: Decimal(v)
                    if k in (
                        'pontos_minimos',
                        'bonus_pontos_percentual',
                        'desconto_percentual',
                    )
                    else v
                    for k, v in nivel.items()
                },
            )
            for nivel in snapshot['niveis']
        ]
        progresso = Decimal(snapshot['progresso_anterior'])
        ultima = (
            datetime.fromisoformat(snapshot['ultima_compra'])
            if snapshot['ultima_compra']
            else None
        )
        avaliacao = avaliar_fidelidade_compra(
            valor=valor,
            politica=politica,
            instante=instante,
            ultima_compra=ultima,
            progresso=progresso,
            niveis=niveis,
            multiplicador=multiplicador,
            desconto_resgate=Decimal(snapshot.get('desconto_resgate', '0.00')),
        )
        if snapshot != snapshot_beneficios(
            avaliacao, politica, progresso, ultima,
            desconto_resgate=Decimal(snapshot.get('desconto_resgate', '0.00')),
            versao=snapshot['versao'],
        ):
            raise ValueError
        return avaliacao
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise ValidationError('Snapshot de benefícios inválido.') from exc
