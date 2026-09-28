"""Leitura agregada do Dashboard; escopo autorizado antes de qualquer métrica."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Context, Decimal, localcontext

from django.core.exceptions import PermissionDenied
from django.db.models import Count, DateField, Exists, ExpressionWrapper, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.empresas.models import Loja, MembroEmpresa
from apps.empresas.services import resolver_configuracao, resolver_lojas_visiveis
from apps.fidelidade.models import Compra, LotePontos, NivelFidelidade, Resgate
from apps.fidelidade.niveis import clientes_com_nivel
from apps.usuarios.services import validar_contexto_ativo

ZERO = Decimal('0')
HORIZONTES = (3, 6, 12)


def normalizar_horizonte(valor):
    """Query string inválida não impede a leitura: volta ao padrão de 12 meses."""
    return int(valor) if str(valor) in ('3', '6', '12') else 12


@dataclass(frozen=True)
class EscopoDashboard:
    membro: MembroEmpresa
    lojas: tuple[Loja, ...]
    loja_selecionada: Loja | None

    @property
    def loja_ids(self):
        if self.loja_selecionada is not None:
            return (self.loja_selecionada.pk,)
        return tuple(loja.pk for loja in self.lojas)


def resolver_escopo_dashboard(request):
    membro = validar_contexto_ativo(request, 'gestao')
    lojas = tuple(resolver_lojas_visiveis(request))
    selecionada = None
    filtro = request.GET.get('loja', '')
    if filtro:
        # Não converter entrada arbitrária em filtro de métricas ou aceitar IDs
        # ausentes da lista autorizada (inclui inexistentes e outras Empresas).
        selecionada = next((loja for loja in lojas if str(loja.pk) == filtro), None)
        if selecionada is None:
            raise PermissionDenied('Loja não autorizada neste contexto.')
    return EscopoDashboard(membro, lojas, selecionada)


def _mes_deslocado(mes, deslocamento):
    ano, indice = divmod(mes.year * 12 + mes.month - 1 + deslocamento, 12)
    return date(ano, indice + 1, 1)


def _meses_calendario(referencia, horizonte):
    mes_atual = timezone.localdate(referencia).replace(day=1)
    return [_mes_deslocado(mes_atual, n) for n in range(1 - horizonte, 1)]


def _agregar_mensal(registros, campo_data, meses, referencia, **agregacoes):
    fuso = timezone.get_current_timezone()
    inicio = timezone.make_aware(datetime.combine(meses[0], time.min), fuso)
    return registros.filter(**{
        f'{campo_data}__gte': inicio, f'{campo_data}__lte': referencia,
    }).annotate(mes=TruncMonth(campo_data, tzinfo=fuso)).values('mes').annotate(
        **agregacoes,
    ).order_by('mes')


def _preencher_meses(meses, agrupados, **padroes):
    por_mes = {linha['mes'].date(): linha for linha in agrupados}
    return [dict(mes=mes, **{
        campo: por_mes.get(mes, {}).get(campo, padrao) for campo, padrao in padroes.items()
    }) for mes in meses]


def _compras_no_escopo(escopo, referencia):
    return Compra.objects.filter(
        loja__empresa_id=escopo.membro.empresa_id, loja_id__in=escopo.loja_ids,
        ocorrida_em__lte=referencia,
    )


def _resgates_no_escopo(escopo, referencia):
    return Resgate.objects.filter(
        loja__empresa_id=escopo.membro.empresa_id, loja_id__in=escopo.loja_ids,
        resgatado_em__lte=referencia,
    )


def _custo_resgates(referencia):
    # Um estorno posterior não apaga o custo que ainda existia na referência.
    return Sum('valor_desconto', filter=(
        Q(estorno__isnull=True) | Q(estorno__estornado_em__gt=referencia)
    ), default=ZERO)


def _serie_compras(compras, referencia):
    meses = _meses_calendario(referencia, 12)
    agrupados = _agregar_mensal(compras, 'ocorrida_em', meses, referencia,
                               compras=Count('pk'), volume=Sum('valor'))
    return _preencher_meses(meses, agrupados, compras=0, volume=ZERO)


def _recortar_series(linhas, metricas, periodos):
    # Cada série sai pronta do backend, com seu próprio horizonte normalizado.
    return {metrica: [dict(mes=linha['mes'], valor=linha[metrica])
                      for linha in linhas[-normalizar_horizonte(periodos.get(f'{metrica}_meses')):]]
            for metrica in metricas}


def ler_series_vendas(escopo, periodos, *, referencia):
    """Uma agregação de 12 meses abastece os três recortes independentes."""
    linhas = _serie_compras(_compras_no_escopo(escopo, referencia), referencia)
    with localcontext(Context(prec=60)):
        for linha in linhas:
            # Ausência de compras não é ticket zero; o frontend exibirá "Sem dados".
            linha['ticket'] = linha['volume'] / linha['compras'] if linha['compras'] else None
    return _recortar_series(linhas, ('compras', 'volume', 'ticket'), periodos)


def ler_series_fidelidade(escopo, periodos, *, referencia):
    meses = _meses_calendario(referencia, 12)
    lotes = LotePontos.objects.filter(compra_id__in=_compras_no_escopo(
        escopo, referencia,
    ).values('pk'))
    concessoes = _agregar_mensal(lotes, 'compra__ocorrida_em', meses, referencia,
                               pontos_concedidos=Sum('pontos_concedidos'))
    # Pontos mantêm o fato histórico; custo considera apenas estornos até a referência.
    resgates = _agregar_mensal(_resgates_no_escopo(escopo, referencia), 'resgatado_em', meses, referencia,
                              pontos_resgatados=Sum('pontos_resgatados'),
                              custo_resgates=_custo_resgates(referencia))
    return {
        **_recortar_series(_preencher_meses(meses, concessoes, pontos_concedidos=ZERO),
                           ('pontos_concedidos',), periodos),
        **_recortar_series(_preencher_meses(meses, resgates, pontos_resgatados=ZERO,
                                          custo_resgates=ZERO),
                           ('pontos_resgatados', 'custo_resgates'), periodos),
    }


def _recompra(compras, clientes, referencia_data, dias, fuso):
    if dias >= referencia_data.toordinal():
        return dict(elegiveis=0, recompraram=0, percentual=None, periodo_recompra_dias=dias)
    primeira = compras.filter(cliente_id=OuterRef('pk')).order_by(
        'ocorrida_em', 'pk',
    ).annotate(data_local=TruncDate('ocorrida_em', tzinfo=fuso)).values('data_local')[:1]
    # date + integer no PostgreSQL preserva dias de calendário, inclusive em DST.
    elegiveis = clientes.annotate(primeira_data=Subquery(primeira)).filter(
        primeira_data__lte=referencia_data - timedelta(days=dias),
    )
    segunda = compras.filter(cliente_id=OuterRef('pk')).annotate(
        data_local=TruncDate('ocorrida_em', tzinfo=fuso),
    ).filter(
        data_local__gt=OuterRef('primeira_data'),
        data_local__lte=ExpressionWrapper(
            OuterRef('primeira_data') + Value(dias), output_field=DateField(),
        ),
    )
    totais = elegiveis.annotate(recomprou=Exists(segunda)).aggregate(
        elegiveis=Count('pk'), recompraram=Count('pk', filter=Q(recomprou=True)),
    )
    with localcontext(Context(prec=60)):
        percentual = (Decimal(totais['recompraram']) * 100 / totais['elegiveis']
                      if totais['elegiveis'] else None)
    return {**totais, 'percentual': percentual, 'periodo_recompra_dias': dias}


def ler_dashboard(escopo, *, referencia=None, secao=None):
    """KPIs sem horizonte; secao limita apenas as análises acessórias.

    Sem secao, mantém a leitura completa usada pelos consumidores da F4.02B.
    """
    referencia = referencia if referencia is not None else timezone.now()
    fuso = timezone.get_current_timezone()
    data_local = timezone.localdate(referencia, fuso)
    empresa = escopo.membro.empresa
    politica = resolver_configuracao(empresa)
    compras = _compras_no_escopo(escopo, referencia)
    clientes = Cliente.objects.filter(empresa_id=empresa.pk, pk__in=compras.values('cliente_id'))
    # Evita overflow para políticas positivas maiores que a idade do calendário.
    try:
        inicio_atividade = referencia - timedelta(days=politica.periodo_cliente_ativo_dias)
    except OverflowError:
        inicio_atividade = datetime.min.replace(tzinfo=referencia.tzinfo)
    totais = compras.aggregate(
        compras=Count('pk'), volume=Sum('valor', default=ZERO),
        clientes_no_escopo=Count('cliente_id', distinct=True),
        clientes_ativos=Count('cliente_id', distinct=True,
                              filter=Q(ocorrida_em__gte=inicio_atividade)),
    )
    with localcontext(Context(prec=60)):
        ticket = totais['volume'] / totais['compras'] if totais['compras'] else ZERO
    lotes = LotePontos.objects.filter(compra_id__in=compras.values('pk'))
    resgates = _resgates_no_escopo(escopo, referencia)
    totais_resgates = resgates.aggregate(
        pontos_resgatados=Sum('pontos_resgatados', default=ZERO),
        custo_resgates=_custo_resgates(referencia),
    )
    ranking = []
    if secao in (None, 'clientes'):
        ranking = list(lotes.values(
            'cliente_id', 'cliente__usuario__first_name', 'cliente__usuario__last_name',
        ).annotate(pontos=Sum('pontos_concedidos')).order_by('-pontos', 'cliente_id')[:10])
    niveis = None
    if secao in (None, 'clientes') and escopo.membro.papel == MembroEmpresa.Papel.ADMINISTRADOR:
        distribuicao = dict(clientes_com_nivel(clientes).order_by().values('nivel_id').annotate(
            quantidade=Count('pk'),
        ).values_list('nivel_id', 'quantidade'))
        niveis = [dict(nome=nivel.nome, quantidade=distribuicao.get(nivel.pk, 0))
                  for nivel in NivelFidelidade.objects.filter(empresa=empresa).order_by('pontos_minimos')]
    serie = _serie_compras(compras, referencia) if secao is None else []
    recompra = _recompra(compras, clientes, data_local, politica.periodo_recompra_dias, fuso)
    recompra['nao_recompraram'] = recompra['elegiveis'] - recompra['recompraram']
    return {
        **totais, **totais_resgates, 'referencia': referencia, 'ticket_medio': ticket,
        'periodo_cliente_ativo_dias': politica.periodo_cliente_ativo_dias,
        'recompra': recompra,
        'clientes_inativos': totais['clientes_no_escopo'] - totais['clientes_ativos'],
        'pontos_concedidos': lotes.aggregate(total=Sum('pontos_concedidos', default=ZERO))['total'],
        'ranking': ranking, 'niveis': niveis, 'serie': serie,
    }
