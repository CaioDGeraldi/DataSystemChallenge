"""Contratos físicos e cálculo financeiro do Resgate, sem consulta à configuração."""
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext

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
