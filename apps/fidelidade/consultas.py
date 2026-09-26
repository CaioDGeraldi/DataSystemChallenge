"""Consultas de fidelidade atuais, sem persistência nem snapshots."""
from decimal import Context, Decimal, localcontext

from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.empresas.models import Loja
from apps.empresas.services import exigir_loja_autorizada, resolver_configuracao
from apps.usuarios.validators import normalizar_cpf, validar_cpf

from .beneficios import NivelBeneficios, avaliar_fidelidade_compra
from .exceptions import ClienteNaoEncontrado, LojaForaDoEscopo
from .models import AlocacaoResgate, Compra, LotePontos, NivelFidelidade


ZERO = Decimal("0.0000")


def _quatro_casas(valor):
    return format(valor, ".4f")


def _duas_casas(valor):
    return format(valor, ".2f")


def _saldo_atual(cliente_id, instante):
    concedidos = (
        LotePontos.objects.filter(
            cliente_id=cliente_id,
            expira_em__gt=instante,
        ).aggregate(total=Sum("pontos_concedidos"))["total"]
        or ZERO
    )
    consumidos = (
        AlocacaoResgate.objects.filter(
            lote__cliente_id=cliente_id,
            lote__expira_em__gt=instante,
        ).aggregate(total=Sum("pontos_consumidos"))["total"]
        or ZERO
    )

    precisao = max(
        60,
        len(concedidos.as_tuple().digits)
        + len(consumidos.as_tuple().digits)
        + 8,
    )
    with localcontext(Context(prec=precisao)):
        saldo = concedidos - consumidos

    if saldo < 0:
        raise RuntimeError("Saldo derivado negativo.")

    return saldo


def consultar_fidelidade_cliente(*, credencial, loja_id, cliente_cpf):
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

    pontos_historicos = (
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

    avaliacao = avaliar_fidelidade_compra(
        valor=Decimal("0.00"),
        politica=politica,
        instante=instante,
        ultima_compra=ultima_compra,
        progresso=pontos_historicos,
        niveis=niveis,
    )

    nivel = avaliacao.nivel_anterior
    nivel_atual = None
    if nivel is not None:
        nivel_atual = {
            "nome": nivel.nome,
            "pontos_minimos": _quatro_casas(nivel.pontos_minimos),
            "beneficios": {
                "bonus_pontos_percentual": _quatro_casas(
                    nivel.bonus_pontos_percentual,
                ),
                "desconto_percentual": _quatro_casas(
                    nivel.desconto_percentual,
                ),
                "aplicaveis": avaliacao.beneficios_nivel_aplicaveis,
            },
        }

    promocao_aplicavel = (
        avaliacao.retorno and politica.promocao_retorno_ativa
    )

    return {
        "cliente": {
            "cpf": cliente.usuario.cpf,
            "nome": cliente.usuario.get_full_name().strip(),
        },
        "atividade": {
            "ativo": avaliacao.ativo_antes,
            "ultima_compra_em": ultima_compra,
            "periodo_cliente_ativo_dias": politica.periodo_cliente_ativo_dias,
        },
        "nivel": {
            "pontos_historicos": _quatro_casas(pontos_historicos),
            "atual": nivel_atual,
        },
        "saldo": {
            "pontos": _quatro_casas(
                _saldo_atual(cliente.pk, instante),
            ),
        },
        "promocao_retorno": {
            "aplicavel": promocao_aplicavel,
            "bonus_pontos_percentual": _quatro_casas(
                politica.bonus_pontos_retorno_percentual
                if promocao_aplicavel
                else ZERO
            ),
            "desconto_percentual": _quatro_casas(
                politica.desconto_retorno_percentual
                if promocao_aplicavel
                else ZERO
            ),
        },
        "resgate": {
            "minimo_pontos": politica.resgate_minimo_pontos,
            "incremento_pontos": politica.incremento_resgate_pontos,
            "valor_monetario_por_ponto": _duas_casas(
                politica.valor_monetario_por_ponto,
            ),
        },
    }
