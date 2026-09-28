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


def ler_dashboard(escopo, *, referencia=None):
    referencia = referencia if referencia is not None else timezone.now()
    fuso = timezone.get_current_timezone()
    data_local = timezone.localdate(referencia, fuso)
    empresa = escopo.membro.empresa
    politica = resolver_configuracao(empresa)
    compras = Compra.objects.filter(
        loja__empresa_id=empresa.pk, loja_id__in=escopo.loja_ids,
        ocorrida_em__lte=referencia,
    )
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
    resgates = Resgate.objects.filter(loja__empresa_id=empresa.pk, loja_id__in=escopo.loja_ids)
    totais_resgates = resgates.aggregate(
        pontos_resgatados=Sum('pontos_resgatados', default=ZERO),
        custo_resgates=Sum('valor_desconto', filter=Q(estorno__isnull=True), default=ZERO),
    )
    ranking = list(lotes.values(
        'cliente_id', 'cliente__usuario__first_name', 'cliente__usuario__last_name',
    ).annotate(pontos=Sum('pontos_concedidos')).order_by('-pontos', 'cliente_id')[:10])
    niveis = None
    if escopo.membro.papel == MembroEmpresa.Papel.ADMINISTRADOR:
        distribuicao = dict(clientes_com_nivel(clientes).order_by().values('nivel_id').annotate(
            quantidade=Count('pk'),
        ).values_list('nivel_id', 'quantidade'))
        niveis = [dict(nome=nivel.nome, quantidade=distribuicao.get(nivel.pk, 0))
                  for nivel in NivelFidelidade.objects.filter(empresa=empresa).order_by('pontos_minimos')]
    mes_atual = data_local.replace(day=1)
    meses = [_mes_deslocado(mes_atual, n) for n in range(-11, 1)]
    inicio = timezone.make_aware(datetime.combine(meses[0], time.min), fuso)
    fim = timezone.make_aware(datetime.combine(_mes_deslocado(mes_atual, 1), time.min), fuso)
    agrupados = compras.filter(ocorrida_em__gte=inicio, ocorrida_em__lt=fim).annotate(
        mes=TruncMonth('ocorrida_em', tzinfo=fuso),
    ).values('mes').annotate(compras=Count('pk'), volume=Sum('valor')).order_by('mes')
    por_mes = {linha['mes'].date(): linha for linha in agrupados}
    serie = [dict(mes=mes, compras=por_mes.get(mes, {}).get('compras', 0),
                  volume=por_mes.get(mes, {}).get('volume', ZERO)) for mes in meses]
    return {
        **totais, **totais_resgates, 'referencia': referencia, 'ticket_medio': ticket,
        'periodo_cliente_ativo_dias': politica.periodo_cliente_ativo_dias,
        'recompra': _recompra(compras, clientes, data_local, politica.periodo_recompra_dias, fuso),
        'pontos_concedidos': lotes.aggregate(total=Sum('pontos_concedidos', default=ZERO))['total'],
        'ranking': ranking, 'niveis': niveis, 'serie': serie,
    }
