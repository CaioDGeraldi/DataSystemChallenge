"""Contratos físicos e cálculo financeiro do Resgate, sem consulta à configuração."""
from decimal import Context, Decimal, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP, localcontext

from django.core.exceptions import ValidationError
from django.core.validators import DecimalValidator


MAX_PONTOS_RESGATE = 10**20 - 1


def normalizar_identificador_resgate(valor):
    if not isinstance(valor, str) or not 1 <= len(valor.strip()) <= 255:
        raise ValidationError({'identificador_externo': 'Informe uma string não vazia de até 255 caracteres após strip.'})
    return valor.strip()


def validar_pontos_solicitados(pontos):
    if type(pontos) is not int or not 1 <= pontos <= MAX_PONTOS_RESGATE:
        raise ValidationError({'pontos': 'Informe um inteiro positivo de até 20 dígitos, sem float.'})
    return Decimal(pontos)


def calcular_desconto(pontos, taxa):
    for campo, valor, digitos, casas in (
        ('pontos_resgatados', pontos, 20, 0),
        ('valor_monetario_por_ponto_aplicado', taxa, 12, 2),
    ):
        if not isinstance(valor, Decimal) or not valor.is_finite() or valor <= 0:
            raise ValidationError({campo: 'Informe um Decimal positivo e finito, sem float.'})
        DecimalValidator(max_digits=digitos, decimal_places=casas)(valor)
    # Produto de até 32 dígitos; independente da precisão/traps do chamador.
    with localcontext(Context(prec=40, rounding=ROUND_HALF_UP)):
        desconto = (pontos * taxa).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        DecimalValidator(max_digits=32, decimal_places=2)(desconto)
        return desconto


def teto_resgate(valor, percentual):
    """Teto em centavos, sempre para baixo: nunca ultrapassa o percentual bruto."""
    with localcontext(Context(prec=60)):
        return (valor * percentual / 100).quantize(Decimal('.01'), rounding=ROUND_DOWN)


def maximo_desconto_compra(valor, politica, desconto_nivel=Decimal('0'), desconto_retorno=Decimal('0')):
    """Teto contratual limitado ao valor que efetivamente pode receber Resgate."""
    with localcontext(Context(prec=60)):
        capacidade = valor
        if politica.ordem_aplicacao_resgate == 'DEPOIS_DOS_DESCONTOS_PERCENTUAIS':
            if politica.modo_combinacao_descontos_percentuais == 'ADITIVO':
                capacidade *= 1 - min(Decimal('100'), desconto_nivel + desconto_retorno) / 100
            else:
                capacidade *= (1 - desconto_nivel / 100) * (1 - desconto_retorno / 100)
        return min(teto_resgate(valor, politica.limite_resgate_percentual), capacidade)


def maximo_resgate(saldo, politica, *, valor_compra=None, desconto_nivel=Decimal('0'), desconto_retorno=Decimal('0')):
    """Maior mínimo + N × incremento financiável, sem consumo ou reserva."""
    with localcontext(Context(prec=max(60, len(saldo.as_tuple().digits) + 40))):
        limite = min(saldo, Decimal(MAX_PONTOS_RESGATE))
        if politica.limite_resgate_percentual == 0:
            limite = Decimal(0)
        if valor_compra is not None:
            teto = maximo_desconto_compra(valor_compra, politica, desconto_nivel, desconto_retorno)
            limite = min(limite, teto / politica.valor_monetario_por_ponto)
        minimo = politica.resgate_minimo_pontos
        incremento = politica.incremento_resgate_pontos
        pontos = 0 if limite < minimo else minimo + int(
            ((limite - minimo) / incremento).to_integral_value(rounding=ROUND_FLOOR)
        ) * incremento
        desconto = calcular_desconto(Decimal(pontos), politica.valor_monetario_por_ponto) if pontos else Decimal('0.00')
        return pontos, desconto


def disponibilidade_resgate(saldo, politica, *, valor_compra=None, desconto_nivel=Decimal('0'), desconto_retorno=Decimal('0')):
    pontos, desconto = maximo_resgate(saldo, politica, valor_compra=valor_compra,
                                     desconto_nivel=desconto_nivel, desconto_retorno=desconto_retorno)
    return {
        'possivel': pontos > 0 and politica.limite_resgate_percentual > 0,
        'maximo_pontos': pontos,
        'maximo_desconto': format(desconto, '.2f'),
        'limite_resgate_percentual': format(politica.limite_resgate_percentual, '.4f'),
    }
