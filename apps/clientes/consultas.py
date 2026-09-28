"""Leituras da Área do Cliente; recebem vínculo já autorizado pela camada web."""
from decimal import Context, Decimal, localcontext
from math import ceil

from django.db.models import DecimalField, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.empresas.services import resolver_configuracao
from apps.fidelidade.apresentacao_compras import explicar_compra
from apps.fidelidade.beneficios import avaliar_fidelidade_compra
from apps.fidelidade.consultas import _saldo_atual
from apps.fidelidade.consumo import alocacoes_com_consumo_efetivo
from apps.fidelidade.models import AlocacaoResgate, Compra, LotePontos, NivelFidelidade, Resgate
from apps.fidelidade.niveis import classificar_cliente, clientes_com_nivel

from .models import Cliente


def _total(queryset, grupo, campo):
    return Coalesce(
        Subquery(queryset.order_by().values(grupo).annotate(total=Sum(campo)).values('total')),
        Value(Decimal('0')), output_field=DecimalField(),
    )


def proxima_expiracao(cliente, instante):
    consumos = alocacoes_com_consumo_efetivo(AlocacaoResgate.objects.all())
    lotes = LotePontos.objects.filter(cliente=cliente, expira_em__gt=instante).annotate(
        restante=F('pontos_concedidos') - _total(
            consumos.filter(lote_id=OuterRef('pk')), 'lote_id', 'pontos_consumidos',
        ),
    ).filter(restante__gt=0)
    # Agrupa os lotes que expiram no mesmo instante, já descontado o consumo efetivo.
    proxima = lotes.order_by('expira_em').values('expira_em').annotate(
        pontos=Sum('restante'),
    ).first()
    if proxima:
        proxima['dias'] = ceil((proxima['expira_em'] - instante).total_seconds() / 86400)
    return proxima


def ranking_pessoal(cliente, instante, progresso, saldo):
    universo = Cliente.objects.filter(empresa_id=cliente.empresa_id)
    acumulado = None
    disponivel = None
    # 1 + quantidade estritamente maior equivale a RANK(), inclusive os saltos
    # após empates. COUNT no banco: não materializa a população nem suas identidades.
    if progresso > 0:
        acumulado = 1 + clientes_com_nivel(universo).filter(pontos_para_nivel__gt=progresso).count()
    if saldo > 0:
        concessoes = LotePontos.objects.filter(cliente_id=OuterRef('pk'), expira_em__gt=instante)
        consumos = alocacoes_com_consumo_efetivo(AlocacaoResgate.objects.all()).filter(
            lote__cliente_id=OuterRef('pk'), lote__expira_em__gt=instante,
        )
        universo = universo.annotate(disponivel=
            _total(concessoes, 'cliente_id', 'pontos_concedidos')
            - _total(consumos, 'lote__cliente_id', 'pontos_consumidos'),
        )
        disponivel = 1 + universo.filter(disponivel__gt=saldo).count()
    return {'acumulado': acumulado, 'disponivel': disponivel}


def compras_cliente(cliente):
    return Compra.objects.filter(cliente=cliente).select_related('loja', 'lote_pontos').order_by('-ocorrida_em', '-pk')


def resgates_cliente(cliente):
    return Resgate.objects.filter(cliente=cliente).select_related('loja', 'estorno').order_by('-resgatado_em', '-pk')


def apresentar_compra(compra):
    explicacao = explicar_compra(compra)
    if explicacao:
        compra.detalhes_pontos = {k: Decimal(v) for k, v in explicacao['pontos'].items()}
    return compra


def resumo_cliente(cliente):
    instante = timezone.now()
    classificacao = classificar_cliente(cliente)
    progresso = classificacao.pontos_para_nivel
    niveis = list(NivelFidelidade.objects.filter(empresa_id=cliente.empresa_id))
    seguinte = next((n for n in niveis if n.pontos_minimos > progresso), None)
    ultima = compras_cliente(cliente).filter(ocorrida_em__lte=instante).first()
    politica = resolver_configuracao(cliente.empresa)
    beneficios = avaliar_fidelidade_compra(
        valor=Decimal('0.00'), politica=politica, instante=instante,
        ultima_compra=ultima.ocorrida_em if ultima else None,
        progresso=progresso, niveis=niveis,
    )
    saldo = _saldo_atual(cliente.pk, instante)
    with localcontext(Context(prec=max(60, len(progresso.as_tuple().digits) + 8))):
        faltam = seguinte.pontos_minimos - progresso if seguinte else None
    return {
        'saldo': saldo, 'pontos_nivel': progresso, 'nivel': classificacao.nivel,
        'proximo_nivel': seguinte, 'faltam': faltam, 'beneficios': beneficios,
        'retorno': beneficios.retorno and politica.promocao_retorno_ativa,
        'ultima_compra': ultima, 'expiracao': proxima_expiracao(cliente, instante),
        'ranking': ranking_pessoal(cliente, instante, progresso, saldo),
    }
