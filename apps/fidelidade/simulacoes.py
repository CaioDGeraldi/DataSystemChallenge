"""Simulação de Compra sem persistência ou reserva de estado."""
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext

from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.empresas.models import Loja
from apps.empresas.services import exigir_loja_autorizada, resolver_configuracao
from apps.usuarios.validators import normalizar_cpf, validar_cpf

from .consultas import _saldo_atual
from .calculos_resgate import disponibilidade_resgate
from .beneficios import NivelBeneficios, avaliar_fidelidade_compra
from .eventos import consultar_efeito_evento
from .exceptions import ClienteNaoEncontrado, LojaForaDoEscopo
from .models import Compra, LotePontos, NivelFidelidade


ZERO = Decimal("0.0000")


def _quatro_casas(valor):
    with localcontext(Context(prec=60, rounding=ROUND_HALF_UP)):
        return format(
            valor.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            ".4f",
        )


def _duas_casas(valor):
    with localcontext(Context(prec=60, rounding=ROUND_HALF_UP)):
        return format(
            valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            ".2f",
        )


def _nivel_publico(nivel):
    if nivel is None:
        return None
    return {
        "nome": nivel.nome,
        "pontos_minimos": _quatro_casas(nivel.pontos_minimos),
    }


def simular_compra(*, credencial, loja_id, cliente_cpf, valor):
    instante = timezone.now()

    loja = Loja.objects.select_related("empresa").filter(pk=loja_id).first()
    if loja is None:
        raise LojaForaDoEscopo

    try:
        loja = exigir_loja_autorizada(credencial, loja)
    except PermissionDenied:
        raise LojaForaDoEscopo from None

    cpf = normalizar_cpf(cliente_cpf)
    validar_cpf(cpf)

    cliente = (
        Cliente.objects.select_related("usuario")
        .filter(
            empresa_id=loja.empresa_id,
            usuario__cpf=cpf,
        )
        .first()
    )
    if cliente is None:
        raise ClienteNaoEncontrado

    politica = resolver_configuracao(loja.empresa, loja)

    ultima_compra = (
        Compra.objects.filter(
            cliente_id=cliente.pk,
            ocorrida_em__lte=instante,
        )
        .order_by("-ocorrida_em", "-pk")
        .values_list("ocorrida_em", flat=True)
        .first()
    )

    progresso = (
        LotePontos.objects.filter(cliente_id=cliente.pk).aggregate(
            total=Sum("pontos_concedidos"),
        )["total"]
        or ZERO
    )

    niveis = [
        NivelBeneficios(
            id=nivel.pk,
            nome=nivel.nome,
            pontos_minimos=nivel.pontos_minimos,
            bonus_pontos_percentual=nivel.bonus_pontos_percentual,
            desconto_percentual=nivel.desconto_percentual,
        )
        for nivel in NivelFidelidade.objects.filter(
            empresa_id=loja.empresa_id,
        )
    ]

    efeito = consultar_efeito_evento(loja, instante)
    multiplicador = efeito.valor if efeito is not None else Decimal("1.0000")

    avaliacao = avaliar_fidelidade_compra(
        valor=valor,
        politica=politica,
        instante=instante,
        ultima_compra=ultima_compra,
        progresso=progresso,
        niveis=niveis,
        multiplicador=multiplicador,
    )

    nivel_atual = avaliacao.nivel_anterior
    nivel_bonus = avaliacao.nivel_bonus

    bonus_nivel_configurado = (
        nivel_bonus.bonus_pontos_percentual
        if nivel_bonus is not None
        else ZERO
    )
    desconto_nivel_configurado = (
        nivel_atual.desconto_percentual
        if nivel_atual is not None
        else ZERO
    )

    promocao_retorno_aplicavel = (
        avaliacao.retorno and politica.promocao_retorno_ativa
    )

    with localcontext(Context(prec=60, rounding=ROUND_HALF_UP)):
        desconto_total = (
            valor - avaliacao.valor_final
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    saldo = _saldo_atual(cliente.pk, instante)
    return {
        "cliente": {
            "cpf": cliente.usuario.cpf,
            "nome": cliente.usuario.get_full_name().strip(),
        },
        "simulada_em": instante,
        "saldo": {"pontos": _quatro_casas(saldo)},
        "resgate": disponibilidade_resgate(
            saldo, politica, valor_compra=valor,
            desconto_nivel=avaliacao.desconto_nivel, desconto_retorno=avaliacao.desconto_retorno,
        ),
        "atividade": {
            "ativo": avaliacao.ativo_antes,
            "retorno": avaliacao.retorno,
            "ultima_compra_em": ultima_compra,
        },
        "nivel": {
            "atual": _nivel_publico(nivel_atual),
            "bonus_pontos": _nivel_publico(nivel_bonus),
            "beneficios_aplicaveis": avaliacao.beneficios_nivel_aplicaveis,
            "bonus_pontos_percentual": _quatro_casas(
                bonus_nivel_configurado,
            ),
            "desconto_percentual": _quatro_casas(
                desconto_nivel_configurado,
            ),
        },
        "campanha": {
            "aplicavel": efeito is not None,
            "nome": efeito.evento.nome if efeito is not None else None,
            "multiplicador_pontos": _quatro_casas(multiplicador),
        },
        "promocao_retorno": {
            "aplicavel": promocao_retorno_aplicavel,
            "bonus_pontos_percentual": _quatro_casas(
                politica.bonus_pontos_retorno_percentual
                if promocao_retorno_aplicavel
                else ZERO
            ),
            "desconto_percentual": _quatro_casas(
                politica.desconto_retorno_percentual
                if promocao_retorno_aplicavel
                else ZERO
            ),
        },
        "valores": {
            "bruto": _duas_casas(valor),
            "desconto_total": _duas_casas(desconto_total),
            "final": _duas_casas(avaliacao.valor_final),
            "elegivel_pontos": _duas_casas(
                avaliacao.valor_elegivel_pontos,
            ),
        },
        "pontos": {
            "base": _quatro_casas(avaliacao.pontos_base),
            "apos_campanha": _quatro_casas(
                avaliacao.pontos_campanha,
            ),
            "bonus_nivel": _quatro_casas(
                avaliacao.pontos_bonus_nivel,
            ),
            "bonus_retorno": _quatro_casas(
                avaliacao.pontos_bonus_retorno,
            ),
            "total_estimado": _quatro_casas(
                avaliacao.pontos_concedidos,
            ),
        },
    }
