"""Cálculos determinísticos; não consultam configuração nem persistem histórico."""
from calendar import monthrange
from datetime import datetime, timezone as datetime_timezone
from decimal import Context, Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, localcontext

from django.core.exceptions import ValidationError
from django.core.validators import DecimalValidator
from django.utils import timezone

from apps.empresas.parametros import PRECISOES_PONTOS


ARREDONDAMENTOS = {"HALF_UP": ROUND_HALF_UP, "DOWN": ROUND_DOWN, "UP": ROUND_UP}


def calcular_pontos(valor, pontos_por_real, precisao, modo, multiplicador=Decimal("1.0000")):
    for numero in (valor, pontos_por_real):
        if not isinstance(numero, Decimal) or not numero.is_finite() or numero < 0:
            raise ValidationError("Informe valores Decimal não negativos e finitos.")
        DecimalValidator(max_digits=12, decimal_places=2)(numero)
    if (type(precisao) is not int or precisao not in PRECISOES_PONTOS
            or not isinstance(modo, str) or modo not in ARREDONDAMENTOS):
        raise ValidationError("Política de pontos inválida.")
    if not isinstance(multiplicador, Decimal) or not multiplicador.is_finite() or multiplicador <= 0:
        raise ValidationError("Informe um multiplicador Decimal estritamente positivo.")
    DecimalValidator(max_digits=12, decimal_places=4)(multiplicador)
    # Três operandos de até 12 dígitos: até 36 dígitos no produto exato.
    # Margem para carry na quantização; contexto independente do chamador.
    with localcontext(Context(prec=40, rounding=ROUND_HALF_UP)):
        base = valor * pontos_por_real
        concedidos = (base * multiplicador).quantize(Decimal(1).scaleb(-precisao), rounding=ARREDONDAMENTOS[modo])
        base = base.quantize(Decimal("0.0001"))
        concedidos = concedidos.quantize(Decimal("0.0001"))
        DecimalValidator(max_digits=24, decimal_places=4)(concedidos)
        return base, concedidos


def calcular_expiracao(adquiridos_em, validade_meses):
    if not isinstance(adquiridos_em, datetime) or timezone.is_naive(adquiridos_em):
        raise ValidationError({"adquiridos_em": "Informe uma data/hora com timezone."})
    if type(validade_meses) is not int or validade_meses < 1:
        raise ValidationError({"validade_pontos_meses_aplicada": "Informe um inteiro positivo."})
    erro = {"expira_em": "A data da Compra e a validade não permitem representar a expiração."}
    try:
        local = timezone.localtime(adquiridos_em, timezone.get_default_timezone())
        ano, mes_zero = divmod(local.year * 12 + local.month - 1 + validade_meses, 12)
        if not 1 <= ano <= 9999:
            raise ValidationError(erro)
        mes = mes_zero + 1
        dia = min(local.day, monthrange(ano, mes)[1])
        expira = local.replace(year=ano, month=mes, day=dia)
        # Também precisa ser representável em UTC para persistência/serialização.
        expira.astimezone(datetime_timezone.utc)
    except (OverflowError, ValueError):
        raise ValidationError(erro) from None
    return expira
