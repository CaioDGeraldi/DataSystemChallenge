from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from apps.empresas.apresentacao import contexto_gestao
from .services import (
    HORIZONTES, ler_dashboard, ler_series_fidelidade, ler_series_vendas,
    normalizar_horizonte, resolver_escopo_dashboard,
)


SECOES = (
    ('inicio', 'Visão geral'),
    ('vendas', 'Vendas'),
    ('fidelidade', 'Fidelidade'),
    ('clientes', 'Clientes'),
)

SERIES = {
    'vendas': (
        ('compras', 'Compras por mês', '', '0'),
        ('volume', 'Volume bruto por mês', 'R$', '2'),
        ('ticket', 'Ticket médio por mês', 'R$', '2'),
    ),
    'fidelidade': (
        ('pontos_concedidos', 'Pontos concedidos por mês', '', '-4'),
        ('pontos_resgatados', 'Pontos resgatados por mês', '', '-4'),
        ('custo_resgates', 'Custo efetivo de Resgates', 'R$', '2'),
    ),
}
LEITORES_SERIES = {'vendas': ler_series_vendas, 'fidelidade': ler_series_fidelidade}


def _contexto_series(request, secao, escopo, referencia):
    definicoes = SERIES.get(secao, ())
    periodos = {f'{chave}_meses': normalizar_horizonte(request.GET.get(f'{chave}_meses'))
                for chave, *_ in definicoes}
    series = LEITORES_SERIES[secao](escopo, periodos, referencia=referencia) if definicoes else {}
    filtro = {'loja': escopo.loja_selecionada.pk} if escopo.loja_selecionada else {}
    blocos = []
    for chave, titulo, unidade, casas in definicoes:
        parametro = f'{chave}_meses'
        opcoes = [dict(meses=meses, selecionado=meses == periodos[parametro],
                       url=request.path + '?' + urlencode({**filtro, **periodos, parametro: meses})
                       + f'#dashboard-{chave}') for meses in HORIZONTES]
        blocos.append(dict(chave=chave, titulo=titulo, unidade=unidade, casas=casas,
                           meses=periodos[parametro], linhas=series[chave], opcoes=opcoes,
                           ancora=chave.replace('_', '-')))
    return {'dashboard_periodos': periodos, 'dashboard_series': series, 'series_temporais': blocos}


def _renderizar_dashboard(request, secao, template):
    escopo = resolver_escopo_dashboard(request)
    filtro = f'?loja={escopo.loja_selecionada.pk}' if escopo.loja_selecionada else ''
    secoes = [dict(nome=nome, url=reverse(f'dashboard:{chave}') + filtro,
                   ativa=chave == secao) for chave, nome in SECOES]
    dados = ler_dashboard(escopo, secao=secao)
    contexto_series = _contexto_series(request, secao, escopo, dados['referencia'])
    graficos = {}
    if secao == 'clientes':
        if dados['niveis'] is not None:
            graficos['niveis_com_dados'] = any(n['quantidade'] for n in dados['niveis'])
        if dados['clientes_no_escopo']:
            graficos['atividade_clientes_grafico'] = [
                dict(nome='Ativos', valor=dados['clientes_ativos']),
                dict(nome='Inativos', valor=dados['clientes_inativos']),
            ]
        graficos['ranking_grafico'] = [
            dict(nome=f"{cliente['cliente__usuario__first_name']} {cliente['cliente__usuario__last_name']}",
                 pontos=cliente['pontos'])
            for cliente in dados['ranking']
        ]
    if secao == 'fidelidade':
        recompra = dados['recompra']
        if recompra['elegiveis']:
            graficos['recompra_grafico'] = [
                dict(nome='Voltaram', valor=recompra['recompraram']),
                dict(nome='Não voltaram', valor=recompra['nao_recompraram']),
            ]
        for serie in contexto_series['series_temporais']:
            serie['total'] = dados[serie['chave']]
    return render(request, template, {
        **contexto_gestao(escopo.membro, 'dashboard'),
        'escopo': escopo, 'dashboard': dados,
        **contexto_series, **graficos,
        'dashboard_vendas_url': reverse('dashboard:vendas') + filtro,
        'dashboard_clientes_url': reverse('dashboard:clientes') + filtro,
        'dashboard_fidelidade_url': reverse('dashboard:fidelidade') + filtro,
        'dashboard_secoes': secoes,
        'dashboard_secao': next(item['nome'] for item in secoes if item['ativa']),
    })


@login_required
@require_GET
def dashboard(request):
    return _renderizar_dashboard(request, 'inicio', 'datasystem/gestor/dashboard.html')


@login_required
@require_GET
def vendas(request):
    return _renderizar_dashboard(request, 'vendas', 'datasystem/gestor/dashboard/vendas.html')


@login_required
@require_GET
def fidelidade(request):
    return _renderizar_dashboard(request, 'fidelidade', 'datasystem/gestor/dashboard/fidelidade.html')


@login_required
@require_GET
def clientes(request):
    return _renderizar_dashboard(request, 'clientes', 'datasystem/gestor/dashboard/clientes.html')
