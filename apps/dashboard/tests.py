from datetime import date, timedelta, timezone as utc_timezone
from decimal import Decimal
from html.parser import HTMLParser
import json
import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.empresas.models import AcessoLoja, MembroEmpresa
from apps.fidelidade.niveis import classificar_cliente, criar_nivel
from apps.fidelidade.test_estornos import DadosEstornos
from apps.usuarios.services import CONTEXTO_SESSAO
from .services import (
    ler_dashboard, ler_series_fidelidade, ler_series_vendas, normalizar_horizonte,
    resolver_escopo_dashboard,
)


class DadosDashboard(DadosEstornos):
    secoes = ('inicio', 'vendas', 'fidelidade', 'clientes')

    def setUp(self):
        super().setUp()
        self.gestor = MembroEmpresa.objects.create(
            usuario=self.outro_usuario, empresa=self.empresa, papel='GESTOR',
        )
        AcessoLoja.objects.create(membro=self.gestor, loja=self.loja)

    def escopo(self, membro=None, loja=None):
        membro = membro or self.membro
        request = self.request(membro)
        request.user = membro.usuario
        if loja is not None:
            request.GET = {'loja': str(getattr(loja, 'pk', loja))}
        return resolver_escopo_dashboard(request)

    def ler(self, membro=None, loja=None, secao=None):
        return ler_dashboard(self.escopo(membro, loja), referencia=self.instante, secao=secao)

    def entrar(self, membro=None, cliente=False):
        membro = membro or self.membro
        self.client.force_login(membro.usuario)
        session = self.client.session
        session[CONTEXTO_SESSAO] = {
            'tipo_contexto': 'cliente' if cliente else 'gestao',
            'empresa_id': membro.empresa_id,
            'vinculo_id': self.cliente.pk if cliente else membro.pk,
        }
        session.save()

    def compra(self, dias=0, loja=None, cliente=None, valor='100.00', instante=None):
        return self.lote(valor, loja_id=(loja or self.loja).pk,
                         cliente_cpf=(cliente or self.cliente).usuario.cpf,
                         ocorrida_em=instante or self.instante - timedelta(days=dias))


class DashboardTests(DadosDashboard, TestCase):
    def pagina_clientes(self, parametros=None):
        with patch('apps.dashboard.services.timezone.now', return_value=self.instante):
            return self.client.get(reverse('dashboard:clientes'), parametros or {})

    def json_clientes(self, resposta, chave):
        payload = re.search(
            rf'<script id="dashboard-json-{chave}" type="application/json">(.*?)</script>',
            resposta.content.decode(),
        ).group(1)
        self.assertNotIn('<', payload)
        self.assertNotIn('&', payload)
        return json.loads(payload)

    def test_graficos_clientes_atividade_json_fallback_e_janela(self):
        self.entrar()
        self.configurar(periodo_cliente_ativo_dias=30)
        self.compra(31)
        self.compra(cliente=self.outro_cliente)
        resposta = self.pagina_clientes({'compras_meses': 3, 'pontos_concedidos_meses': 6})
        self.assertEqual(self.json_clientes(resposta, 'atividade-clientes'), [
            {'nome': 'Ativos', 'valor': 1}, {'nome': 'Inativos', 'valor': 1},
        ])
        dados = resposta.context['dashboard']
        self.assertEqual(dados['clientes_ativos'] + dados['clientes_inativos'], dados['clientes_no_escopo'])
        self.assertContains(resposta, '<canvas', count=2)
        self.assertContains(resposta, 'data-chart-axis="y"', count=2)
        self.assertContains(resposta, '<summary>Ver dados</summary>', count=2)
        for texto in ('Janela de atividade: 30 dias', 'Compra nos últimos 30 dias',
                      'Sem Compra nos últimos 30 dias', 'Clientes nas lojas selecionadas',
                      'Clientes ativos', 'Clientes inativos', '<td>Ana Silva</td>',
                      '<h3>Ana Silva</h3>', 'Progresso histórico', 'name="loja"'):
            self.assertContains(resposta, texto)
        self.assertEqual(resposta.context['dashboard_periodos'], {})
        self.assertNotContains(resposta, '_meses')

    def test_graficos_clientes_vazios_sem_canvas_e_ranking_independente(self):
        self.entrar()
        resposta = self.pagina_clientes()
        self.assertContains(resposta, 'Nenhum cliente com Compra nas lojas selecionadas.')
        self.assertContains(resposta, 'Nenhum cliente no ranking.')
        self.assertNotContains(resposta, '<canvas')
        self.assertNotContains(resposta, 'type="application/json"')
        self.compra()
        dados = self.ler(secao='clientes')
        dados['ranking'] = []
        with patch('apps.dashboard.views.ler_dashboard', return_value=dados):
            resposta = self.pagina_clientes()
        self.assertContains(resposta, '<canvas', count=1)
        self.assertNotContains(resposta, 'dashboard-json-ranking')
        self.assertContains(resposta, 'Nenhum cliente no ranking.')

    def test_graficos_clientes_ranking_seguro_historico_sem_dados_extras(self):
        self.cliente.usuario.first_name = 'Ana </script> &'
        self.cliente.usuario.save(update_fields=['first_name'])
        self.compra(500, valor='1234.56')
        self.compra(valor='1000')
        self.resgatar()
        self.estornar()
        self.compra(cliente=self.outro_cliente, valor='3000')
        self.entrar()
        resposta = self.pagina_clientes()
        linhas = self.json_clientes(resposta, 'ranking')
        ranking = resposta.context['dashboard']['ranking']
        self.assertEqual(linhas, [
            {'nome': f"{r['cliente__usuario__first_name']} {r['cliente__usuario__last_name']}",
             'pontos': str(r['pontos'])} for r in ranking
        ])
        self.assertEqual(Decimal(linhas[1]['pontos']), Decimal('2234.56'))
        self.assertEqual(linhas[1]['nome'], 'Ana </script> & Silva')
        for linha in linhas:
            self.assertEqual(set(linha), {'nome', 'pontos'})
        self.assertNotIn(self.cliente.usuario.cpf, json.dumps(linhas))
        self.assertContains(resposta, 'Ana &lt;/script&gt; &amp; Silva')

    def test_graficos_clientes_admin_gestor_escopo_e_atividade_zero(self):
        self.configurar(periodo_cliente_ativo_dias=30)
        self.compra(40, valor='100')
        self.compra(loja=self.segunda, cliente=self.outro_cliente, valor='900')
        credencial, _ = self.emitir(membro=self.outro_membro)
        self.lote('9999', credencial=credencial, loja_id=self.externa.pk,
                  cliente_cpf=self.cliente_externo.usuario.cpf)
        for membro, loja, pontos, atividade in (
            (self.membro, None, [900, 100], [1, 1]),
            (self.membro, self.loja, [100], [0, 1]),
            (self.membro, self.segunda, [900], [1, 0]),
            (self.gestor, None, [100], [0, 1]),
            (self.gestor, self.loja, [100], [0, 1]),
        ):
            with self.subTest(membro=membro.pk, loja=loja):
                self.entrar(membro)
                resposta = self.pagina_clientes({'loja': loja.pk} if loja else {})
                self.assertEqual([Decimal(r['pontos']) for r in self.json_clientes(resposta, 'ranking')], pontos)
                self.assertEqual([r['valor'] for r in self.json_clientes(resposta, 'atividade-clientes')], atividade)
                self.assertContains(resposta, '<canvas', count=2)

    def test_link_ticket_visao_geral_preserva_somente_loja(self):
        self.entrar()
        for loja in (None, self.loja):
            with self.subTest(loja=loja):
                params = {
                    'compras_meses': 3, 'volume_meses': 6, 'ticket_meses': 12,
                    'pontos_concedidos_meses': 3, 'pontos_resgatados_meses': 6,
                    'custo_resgates_meses': 12, 'estranho': 'ignorar',
                }
                if loja:
                    params['loja'] = loja.pk
                resposta = self.client.get(reverse('dashboard:inicio'), params)
                self.assertEqual(resposta.status_code, 200)
                card = re.search(r'<section[^>]*><h2>Ticket médio</h2>.*?</section>',
                                 resposta.content.decode(), re.S)
                self.assertIsNotNone(card)
                self.assertEqual(card.group().count('Ver gráfico'), 1)
                links = ControlesDashboardParser(card.group()).links
                self.assertEqual(len(links), 1)
                destino = urlsplit(links[0]['href'])
                self.assertEqual(destino.path, reverse('dashboard:vendas'))
                self.assertEqual(destino.fragment, 'ticket')
                self.assertEqual(parse_qs(destino.query),
                                 {'loja': [str(loja.pk)]} if loja else {})
                self.assertIn('<span class="sr-only"> — Ticket médio</span>', card.group())

    def test_links_clientes_visao_geral_preservam_somente_loja(self):
        self.entrar()
        for loja in (None, self.loja):
            params = {'compras_meses': 3, 'pontos_concedidos_meses': 6}
            if loja:
                params['loja'] = loja.pk
            resposta = self.client.get(reverse('dashboard:inicio'), params)
            links = [a['href'] for a in ControlesDashboardParser(resposta.content.decode()).links
                     if urlsplit(a.get('href', '')).fragment == 'atividade-clientes']
            self.assertEqual(len(links), 2)
            for link in links:
                destino = urlsplit(link)
                self.assertEqual(destino.path, reverse('dashboard:clientes'))
                self.assertEqual(parse_qs(destino.query), {'loja': [str(loja.pk)]} if loja else {})
            self.assertEqual(resposta.context['dashboard']['ranking'], [])
            self.assertNotContains(resposta, 'dashboard-json-ranking')

    def test_vazio_referencia_unica_e_serie_calendario(self):
        escopo = self.escopo()
        with patch('apps.dashboard.services.timezone.now', return_value=self.instante) as agora:
            dados = ler_dashboard(escopo)
        agora.assert_called_once_with()
        for campo in ('clientes_no_escopo', 'clientes_ativos', 'ticket_medio',
                      'custo_resgates', 'pontos_concedidos', 'pontos_resgatados'):
            self.assertEqual(dados[campo], 0)
        self.assertEqual(dados['ranking'], [])
        self.assertEqual(dados['niveis'], [])
        self.assertIsNone(dados['recompra']['percentual'])
        self.assertEqual(len(dados['serie']), 12)
        self.assertEqual(dados['serie'][0]['mes'], date(2025, 10, 1))
        self.assertEqual(dados['serie'][-1]['mes'], date(2026, 9, 1))
        self.assertTrue(all(m['compras'] == m['volume'] == 0 for m in dados['serie']))

    def test_admin_empresa_ativa_gestor_e_filtro_mesmo_escopo_em_todas_metricas(self):
        self.compra(200, valor='100')
        self.compra(170, valor='300')
        self.compra(0, self.segunda, valor='900')
        self.compra(200, self.segunda, self.outro_cliente, '700')
        credencial, _ = self.emitir(membro=self.outro_membro)
        self.lote('9999', credencial=credencial, loja_id=self.externa.pk,
                  cliente_cpf=self.cliente_externo.usuario.cpf)
        admin = self.ler()
        gestor = self.ler(self.gestor)
        filtrado = self.ler(loja=self.loja)
        self.assertEqual((admin['clientes_no_escopo'], admin['compras'], admin['volume']), (2, 4, 2000))
        self.assertEqual((gestor['clientes_no_escopo'], gestor['compras'], gestor['volume']), (1, 2, 400))
        self.assertEqual(gestor['pontos_concedidos'], 400)
        self.assertEqual(gestor['ranking'][0]['pontos'], 400)
        self.assertEqual(gestor['recompra']['recompraram'], 1)
        self.assertEqual(admin['recompra']['elegiveis'], 2)
        self.assertEqual(self.ler(loja=self.segunda)['recompra']['recompraram'], 0)
        self.assertEqual(self.ler(self.outro_membro)['volume'], 9999)
        for campo in ('clientes_no_escopo', 'clientes_ativos', 'ticket_medio', 'custo_resgates',
                      'pontos_concedidos', 'pontos_resgatados', 'recompra', 'ranking', 'serie'):
            self.assertEqual(gestor[campo], filtrado[campo], campo)
        self.assertIsNone(gestor['niveis'])
        self.assertEqual(sum(m['volume'] for m in gestor['serie']), 400)

    def test_clientes_distintos_sem_compra_excluidos_e_atividade_corporativa(self):
        self.configurar(periodo_cliente_ativo_dias=30)
        self.compra(31)
        self.compra(32)
        self.compra(0, self.segunda)
        self.assertEqual(self.ler(self.gestor)['clientes_no_escopo'], 1)
        self.assertEqual(self.ler(self.gestor)['clientes_ativos'], 0)
        self.assertEqual(self.ler()['clientes_ativos'], 1)
        self.compra(30)
        self.assertEqual(self.ler(self.gestor)['clientes_ativos'], 1)

    def test_ticket_e_serie_usam_bruto_com_beneficio_real(self):
        criar_nivel(self.request(), nome='Inicial', pontos_minimos=Decimal('0'),
                    desconto_percentual=Decimal('20'))
        lote = self.compra(valor='100')
        self.assertEqual(lote.beneficios_aplicados['resultado']['valor_final'], '80.00')
        self.compra(valor='300')
        dados = self.ler()
        self.assertEqual(dados['ticket_medio'], 200)
        self.assertEqual(dados['serie'][-1]['volume'], 400)
        self.assertEqual(dados['serie'][-1]['compras'], 2)

    def test_custo_efetivo_historico_resgates_e_escopo(self):
        self.compra(valor='1000')
        self.resgatar()
        self.estornar()
        self.resgatar(identificador_externo='R2', pontos=200)
        self.resgatar(identificador_externo='R3', loja_id=self.segunda.pk, pontos=100)
        self.configurar(valor_monetario_por_ponto=Decimal('0.90'))
        dados = self.ler(self.gestor)
        self.assertEqual(dados['custo_resgates'], 10)
        self.assertEqual(dados['pontos_resgatados'], 300)
        self.assertEqual(dados['pontos_concedidos'], 1000)
        self.assertEqual(dados['ranking'][0]['pontos'], 1000)
        self.assertEqual(self.ler()['custo_resgates'], 15)
        self.assertEqual(self.ler()['pontos_resgatados'], 400)
        self.assertEqual(self.ler(loja=self.segunda)['pontos_resgatados'], 100)

    def test_recompra_matriz_limites_e_datas_locais(self):
        primeira = self.instante - timedelta(days=200)
        casos = [
            ('dentro', primeira, primeira + timedelta(days=40), 1, 1),
            ('limite', primeira, primeira + timedelta(days=180), 1, 1),
            ('apos', primeira, primeira + timedelta(days=181), 1, 0),
            ('mesmo_dia', primeira, primeira + timedelta(hours=8), 1, 0),
            ('sem_maturidade', self.instante - timedelta(days=179), self.instante, 0, 0),
            ('maturidade_exata', self.instante - timedelta(days=180), self.instante, 1, 1),
            # Cruza UTC, mas não a data local (21:30 e 23:30).
            ('mesmo_dia_local', primeira.replace(hour=21), primeira.replace(hour=23).astimezone(utc_timezone.utc), 1, 0),
            # Mesmo dia UTC, datas locais distintas (23:30 e 00:30).
            ('dias_locais_distintos', primeira.replace(hour=23), (primeira + timedelta(days=1)).replace(hour=0), 1, 1),
        ]
        for nome, inicio, volta, elegiveis, recompraram in casos:
            with self.subTest(nome=nome):
                # Cada cenário tem uma Loja própria para isolar a primeira compra.
                from apps.empresas.models import Loja
                loja = Loja.objects.create(empresa=self.empresa, nome=nome, cidade='Araras')
                self.compra(loja=loja, instante=inicio)
                self.compra(loja=loja, instante=volta)
                dados = self.ler(loja=loja)['recompra']
                self.assertEqual((dados['elegiveis'], dados['recompraram']), (elegiveis, recompraram))
                self.assertEqual(dados['percentual'], Decimal(recompraram * 100) if elegiveis else None)

    def test_recompra_primeira_e_segunda_precisam_estar_no_escopo(self):
        self.compra(250, self.segunda)
        self.compra(100)
        self.assertEqual(self.ler()['recompra']['recompraram'], 1)
        self.assertEqual(self.ler(self.gestor)['recompra']['elegiveis'], 0)
        self.assertEqual(self.ler(loja=self.loja)['recompra']['elegiveis'], 0)
        self.assertEqual(self.ler(loja=self.segunda)['recompra']['recompraram'], 0)

    def test_recompra_janela_configurada_percentual_decimal(self):
        self.configurar(periodo_recompra_dias=30)
        self.compra(40)
        self.compra(20)
        self.compra(40, cliente=self.outro_cliente)
        dados = self.ler()['recompra']
        self.assertEqual(dados, dict(elegiveis=2, recompraram=1, nao_recompraram=1,
                                     percentual=Decimal('50'), periodo_recompra_dias=30))

    def test_ranking_limite_desempate_e_pontos_fora_do_escopo(self):
        # CPFs válidos gerados deterministicamente para ampliar o universo.
        for n in range(12):
            cpf = str(100000000 + n)
            for tamanho in (9, 10):
                soma = sum(int(d) * (tamanho + 1 - i) for i, d in enumerate(cpf))
                digito = 11 - soma % 11
                cpf += str(0 if digito >= 10 else digito)
            usuario = get_user_model().objects.create_user(cpf, first_name=f'Cliente {n}')
            cliente = Cliente.objects.create(usuario=usuario, empresa=self.empresa)
            self.compra(cliente=cliente)
        self.compra(loja=self.segunda, valor='99999')
        ranking = self.ler(self.gestor)['ranking']
        ids = list(Cliente.objects.filter(empresa=self.empresa).exclude(
            pk__in=[self.cliente.pk, self.outro_cliente.pk],
        ).order_by('pk').values_list('pk', flat=True))
        self.assertEqual([r['cliente_id'] for r in ranking], ids[:10])
        self.assertEqual(len(ranking), 10)
        self.entrar(self.gestor)
        resposta = self.pagina_clientes()
        linhas = self.json_clientes(resposta, 'ranking')
        self.assertEqual(len(linhas), 10)
        self.assertEqual(linhas, [
            {'nome': f"{r['cliente__usuario__first_name']} {r['cliente__usuario__last_name']}",
             'pontos': str(r['pontos'])} for r in ranking
        ])
        self.assertEqual(self.ler()['ranking'][0]['cliente_id'], self.cliente.pk)

    def test_nivel_admin_canonico_corporativo_com_filtro_e_gestor_indisponivel(self):
        criar_nivel(self.request(), nome='Bronze', pontos_minimos=Decimal('0'))
        criar_nivel(self.request(), nome='Ouro', pontos_minimos=Decimal('1000'))
        self.compra(500, valor='100')  # Expirado e inativo.
        self.compra(500, self.segunda, valor='1000')
        self.assertEqual(classificar_cliente(self.cliente).nivel.nome, 'Ouro')
        self.assertEqual(self.ler(loja=self.loja)['niveis'], [
            dict(nome='Bronze', quantidade=0), dict(nome='Ouro', quantidade=1),
        ])
        with patch('apps.dashboard.services.clientes_com_nivel') as classificar:
            self.assertIsNone(self.ler(self.gestor)['niveis'])
        classificar.assert_not_called()

    def test_serie_limites_calendario_local_e_zeros(self):
        inicio = self.instante.replace(year=2025, month=10, day=1, hour=0, minute=0)
        self.compra(instante=inicio - timedelta(seconds=1))
        self.compra(instante=inicio, valor='250')
        self.compra(instante=self.instante.replace(day=1, hour=0, minute=0), valor='150')
        serie = self.ler()['serie']
        self.assertEqual(serie[0]['volume'], 250)
        self.assertEqual(serie[-1]['volume'], 150)
        self.assertEqual([m['compras'] for m in serie], [1] + [0] * 10 + [1])
        self.assertEqual([m['mes'] for m in serie], sorted(m['mes'] for m in serie))

    def test_http_filtros_recusados_antes_de_ler_metricas(self):
        for membro, invalidos in ((self.gestor, [self.segunda.pk, self.externa.pk, 999999, 'abc']),
                                  (self.membro, [self.externa.pk, 999999, '-1'])):
            self.entrar(membro)
            for secao in self.secoes:
                for loja in invalidos:
                    with self.subTest(secao=secao, membro=membro.pk, loja=loja), patch('apps.dashboard.views.ler_dashboard') as ler:
                        resposta = self.client.get(reverse(f'dashboard:{secao}'), {'loja': loja})
                        self.assertEqual(resposta.status_code, 403)
                        ler.assert_not_called()

    def test_http_template_navegacao_mobile_vazio_e_filtro_valido(self):
        self.entrar(self.gestor)
        with patch('apps.dashboard.services.clientes_com_nivel') as classificar:
            resposta = self.client.get(reverse('dashboard:inicio'))
        classificar.assert_not_called()
        self.assertIsNone(resposta.context['dashboard']['niveis'])
        self.assertNotContains(resposta, 'dashboard-niveis')
        self.assertNotContains(resposta, 'Distribuição por nível')
        self.assertNotContains(resposta, 'indisponível para o perfil Gestor')
        self.assertTemplateUsed(resposta, 'datasystem/gestor/dashboard.html')
        for texto in ('Dashboard', 'Todas as lojas', 'Sem base suficiente',
                      'Nenhuma compra',
                      'retorna-dashboard-cards', 'sidebar', 'aria-current="page"'):
            self.assertContains(resposta, texto)
        self.assertNotContains(resposta, '<p class="retorna-dashboard-value">0%</p>', html=True)
        self.assertNotContains(resposta, self.segunda.nome)
        self.assertNotContains(resposta, self.externa.nome)
        self.assertNotContains(resposta, 'Buscar loja')
        self.assertNotContains(resposta, 'role="combobox"')
        for texto in ('data-store-search',
                      '<label for="dashboard-loja">Loja</label>',
                      '<select id="dashboard-loja" name="loja">',
                      '<option value="">Todas as lojas</option>',
                      'Pontos concedidos',
                      'Pontos usados em resgates, inclusive os que foram estornados.'):
            self.assertContains(resposta, texto)
        for texto in ('histórico', 'Histórico', 'Lojas permitidas', 'lojas autorizadas'):
            self.assertNotContains(resposta, texto)
        resposta = self.client.get(reverse('dashboard:inicio'), {'loja': self.loja.pk})
        self.assertEqual(resposta.context['escopo'].loja_selecionada, self.loja)
        self.assertContains(resposta, f'value="{self.loja.pk}" selected')
        self.entrar()
        resposta = self.client.get(reverse('dashboard:inicio'))
        self.assertNotContains(resposta, 'Distribuição por nível')
        self.assertContains(self.client.get(reverse('dashboard:fidelidade')), 'Nenhum nível configurado')
        for loja in (self.loja, self.segunda):
            self.assertContains(resposta, f'<option value="{loja.pk}">{loja.nome} — {loja.cidade}</option>', html=True)
        self.assertNotContains(resposta, self.externa.nome)

    def test_cutoff_inclusivo_exclui_compras_futuras_de_todas_metricas_de_compra(self):
        self.compra(200, valor='100')
        self.compra(instante=self.instante, valor='300')
        antes = self.ler()
        self.assertEqual(antes['clientes_no_escopo'], 1)
        self.assertEqual(antes['clientes_ativos'], 1)
        self.assertEqual(antes['compras'], 2)
        self.assertEqual(antes['ticket_medio'], 200)
        self.assertEqual(antes['pontos_concedidos'], 400)
        self.assertEqual(antes['ranking'][0]['pontos'], 400)
        self.assertEqual(antes['serie'][-1]['compras'], 1)
        self.assertEqual(antes['serie'][-1]['volume'], 300)
        # Ambas estão no mês atual; a primeira está só um microssegundo à frente.
        self.compra(instante=self.instante + timedelta(microseconds=1), valor='900')
        self.compra(instante=self.instante + timedelta(hours=1),
                    cliente=self.outro_cliente, valor='9000')
        for membro in (self.membro, self.gestor):
            with self.subTest(papel=membro.papel):
                depois = self.ler(membro)
                for campo in ('clientes_no_escopo', 'clientes_ativos', 'compras', 'volume',
                              'ticket_medio', 'pontos_concedidos', 'ranking', 'serie', 'recompra'):
                    self.assertEqual(depois[campo], antes[campo], campo)

    def test_compra_futura_nao_reativa_cliente_com_historico_antigo(self):
        self.compra(200)
        self.compra(instante=self.instante + timedelta(hours=1))
        dados = self.ler()
        self.assertEqual(dados['clientes_no_escopo'], 1)
        self.assertEqual(dados['clientes_ativos'], 0)

    def test_recompra_futura_so_conta_quando_ocorre_no_limite_da_janela(self):
        self.compra(180)
        segunda = self.instante + timedelta(hours=1)
        self.compra(instante=segunda)
        escopo = self.escopo()
        antes = ler_dashboard(escopo, referencia=self.instante)['recompra']
        self.assertEqual(antes['elegiveis'], 1)
        self.assertEqual(antes['recompraram'], 0)
        self.assertEqual(antes['percentual'], Decimal('0'))
        # Mesma data local no limite de 180 dias, agora com o fato já ocorrido.
        depois = ler_dashboard(escopo, referencia=segunda)['recompra']
        self.assertEqual(depois['elegiveis'], 1)
        self.assertEqual(depois['recompraram'], 1)
        self.assertEqual(depois['percentual'], Decimal('100'))

    def test_ranking_desktop_mobile_exibe_nome_e_pontos_sem_pk(self):
        self.compra(valor='123')
        self.entrar()
        resposta = self.client.get(reverse('dashboard:clientes'))
        self.assertContains(resposta, '<td>Ana Silva</td>', html=True)
        self.assertContains(resposta, '<h3>Ana Silva</h3>', html=True)
        self.assertContains(resposta, '<td class="numeric">123</td>', html=True)
        self.assertContains(resposta, '<dd>123</dd>', html=True)
        self.assertNotContains(resposta, f'#{self.cliente.pk}')
        self.assertEqual(resposta.context['dashboard']['ranking'][0]['cliente_id'], self.cliente.pk)

    def test_cliente_nao_acessa_e_gestor_sem_acesso_tem_vazio(self):
        self.entrar(cliente=True)
        for secao in self.secoes:
            with self.subTest(secao=secao), patch('apps.dashboard.views.ler_dashboard') as ler:
                self.assertEqual(self.client.get(reverse(f'dashboard:{secao}')).status_code, 403)
                ler.assert_not_called()
        self.compra()
        AcessoLoja.objects.filter(membro=self.gestor).delete()
        self.assertEqual(self.ler(self.gestor)['clientes_no_escopo'], 0)
        with self.assertRaises(PermissionDenied):
            self.escopo(self.gestor, self.loja)

    def test_todas_autorizadas_combina_lojas_e_filtro_restringe_recompra(self):
        AcessoLoja.objects.create(membro=self.gestor, loja=self.segunda)
        self.compra(200)
        self.compra(100, self.segunda)
        self.assertEqual(self.ler(self.gestor)['recompra']['recompraram'], 1)
        self.assertEqual(self.ler(self.gestor)['pontos_concedidos'], 200)
        for loja in (self.loja, self.segunda):
            dados = self.ler(self.gestor, loja)
            self.assertEqual(dados['recompra']['recompraram'], 0)
            self.assertEqual(dados['pontos_concedidos'], 100)

    def test_distribuicao_agrupa_clientes_e_reclassifica_com_politica_vigente(self):
        from apps.fidelidade.niveis import editar_nivel
        criar_nivel(self.request(), nome='Inicial', pontos_minimos=Decimal('0'))
        alto = criar_nivel(self.request(), nome='Alto', pontos_minimos=Decimal('1000'))
        self.compra(valor='1500')
        self.compra(cliente=self.outro_cliente, valor='1500')
        self.assertEqual(self.ler()['niveis'], [
            dict(nome='Inicial', quantidade=0), dict(nome='Alto', quantidade=2),
        ])
        editar_nivel(self.request(), alto.pk, nome='Alto', pontos_minimos=Decimal('2000'))
        self.assertEqual(self.ler()['niveis'], [
            dict(nome='Inicial', quantidade=2), dict(nome='Alto', quantidade=0),
        ])

    def test_recompra_nao_altera_snapshot_historico_de_beneficios(self):
        from apps.fidelidade.beneficios import reavaliar_snapshot
        lote = self.compra()
        self.assertNotIn('periodo_recompra_dias', lote.beneficios_aplicados['politica'])
        self.configurar(periodo_recompra_dias=60)
        avaliacao = reavaliar_snapshot(lote.beneficios_aplicados, lote.compra.valor,
                                       lote.compra.ocorrida_em, lote.multiplicador_pontos_aplicado)
        self.assertEqual(avaliacao.pontos_concedidos, lote.pontos_concedidos)

    def test_secoes_get_filtro_topbar_e_reabertura_admin_e_gestor(self):
        self.compra(valor='123')
        self.compra(loja=self.segunda, valor='456')
        nomes = ('Visão geral', 'Vendas', 'Fidelidade', 'Clientes')
        for membro in (self.membro, self.gestor):
            self.entrar(membro)
            for loja in (None, self.loja):
                filtro = f'?loja={loja.pk}' if loja else ''
                for secao in self.secoes:
                    with self.subTest(papel=membro.papel, loja=loja, secao=secao):
                        caminho = '/gestao/dashboard/' + (f'{secao}/' if secao != 'inicio' else '')
                        self.assertEqual(reverse(f'dashboard:{secao}'), caminho)
                        url = caminho + filtro
                        with patch('apps.dashboard.services.timezone.now', return_value=self.instante):
                            resposta = self.client.get(url)
                            reaberta = self.client.get(url)
                        # ler() passa referencia=self.instante explicitamente, a mesma
                        # referência usada nas duas requisições acima.
                        esperados = self.ler(membro, loja, secao=secao)
                        template = ('datasystem/gestor/dashboard.html' if secao == 'inicio'
                                    else f'datasystem/gestor/dashboard/{secao}.html')
                        for abertura, atual in (('inicial', resposta), ('reaberta', reaberta)):
                            with self.subTest(abertura=abertura):
                                self.assertEqual(atual.status_code, 200)
                                escopo = atual.context['escopo']
                                self.assertEqual(escopo.membro, membro)
                                self.assertEqual(escopo.loja_selecionada, loja)
                                self.assertEqual(escopo.lojas, self.escopo(membro, loja).lojas)
                                self.assertEqual(atual.context['dashboard_secao'], nomes[self.secoes.index(secao)])
                                self.assertEqual(atual.context['dashboard'], esperados)
                                self.assertEqual(atual.context['dashboard']['referencia'], self.instante)
                                self.assertTemplateUsed(atual, 'datasystem/gestao_base.html')
                                self.assertTemplateUsed(atual, template)
                                self.assertContains(atual, 'method="get"')
                                self.assertContains(atual, '<option value="">Todas as lojas</option>', html=True)
                                if loja:
                                    self.assertContains(atual, f'value="{loja.pk}" selected')
                                nav = atual.content.decode().split('aria-label="Seções do Dashboard">', 1)[1].split('</nav>', 1)[0]
                                self.assertEqual(nav.count('aria-current="page"'), 1)
                                for destino, nome in zip(self.secoes, nomes):
                                    ativo = ' aria-current="page"' if destino == secao else ''
                                    link = f'<a href="{reverse(f"dashboard:{destino}")}{filtro}"{ativo}>{nome}</a>'
                                    self.assertIn(link, nav)
                                self.assertNotContains(atual, self.externa.nome)
                                if membro == self.gestor:
                                    self.assertNotContains(atual, self.segunda.nome)

    def test_conteudo_exclusivo_por_secao_e_indicadores_preservados(self):
        self.entrar()
        exclusivos = {
            'vendas': 'Compras por mês',
            'fidelidade': 'Distribuição por nível',
            'clientes': 'Top 10 clientes por pontos concedidos',
        }
        indicadores = {
            'clientes': ('Clientes nas lojas selecionadas', 'Clientes ativos'),
            'fidelidade': ('Taxa de recompra', 'Pontos concedidos',
                           'Pontos resgatados', 'Custo efetivo de resgates'),
            'inicio': ('Ticket médio',),
        }
        for secao in self.secoes:
            with self.subTest(secao=secao):
                resposta = self.client.get(reverse(f'dashboard:{secao}'))
                for destino, texto in exclusivos.items():
                    verificar = self.assertContains if secao == destino else self.assertNotContains
                    verificar(resposta, texto)
                for destino, textos in indicadores.items():
                    for texto in textos:
                        verificar = self.assertRegex if secao in ('inicio', destino) else self.assertNotRegex
                        # O KPI "Ticket médio" é distinto da série "Ticket médio por mês" de Vendas.
                        fim_titulo = r'\s*</h2>' if destino == 'inicio' else ''
                        verificar(resposta.content.decode(), re.compile(
                            r'<h2\b[^>]*>' + re.escape(texto) + fim_titulo, re.I,
                        ))
                if secao in ('vendas', 'clientes'):
                    self.assertContains(resposta, 'retorna-mobile-presentation')
                    self.assertContains(resposta, 'retorna-desktop-presentation')
                if secao == 'clientes':
                    self.assertContains(resposta, 'Nenhum cliente no ranking')
                if secao == 'vendas':
                    for serie in resposta.context['dashboard_series'].values():
                        self.assertEqual(len(serie), 12)
                    self.assertContains(resposta, 'Volume bruto por mês')
                    self.assertContains(resposta, 'Ticket médio por mês')
                if secao not in ('vendas', 'fidelidade'):
                    self.assertNotContains(resposta, '<canvas')

    def test_gestor_nao_consulta_niveis_em_nenhuma_secao(self):
        self.entrar(self.gestor)
        for secao in self.secoes:
            with self.subTest(secao=secao), patch('apps.dashboard.services.clientes_com_nivel') as classificar:
                resposta = self.client.get(reverse(f'dashboard:{secao}'))
                self.assertEqual(resposta.status_code, 200)
                self.assertIsNone(resposta.context['dashboard']['niveis'])
                self.assertNotContains(resposta, 'Distribuição por nível')
                self.assertNotContains(resposta, 'dashboard-niveis')
                classificar.assert_not_called()

    def test_secoes_exigem_login_e_aceitam_somente_get(self):
        for secao in self.secoes:
            self.assertEqual(self.client.get(reverse(f'dashboard:{secao}')).status_code, 302)
        self.entrar()
        for secao in self.secoes:
            with patch('apps.dashboard.views.ler_dashboard') as ler:
                self.assertEqual(self.client.post(reverse(f'dashboard:{secao}')).status_code, 405)
                ler.assert_not_called()


class ControlesDashboardParser(HTMLParser):
    """Lê links e campos reais do HTML para exercitar navegação GET sem JavaScript."""
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.formularios = []
        self.formulario = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a':
            self.links.append(attrs)
        elif tag == 'form':
            self.formulario = {**attrs, 'campos': {}}
            self.formularios.append(self.formulario)
        elif tag == 'input' and self.formulario is not None and attrs.get('name'):
            self.formulario['campos'][attrs['name']] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.formulario = None


class SeriesDashboardTests(DadosDashboard, TestCase):
    def pagina(self, secao, parametros=None):
        with patch('apps.dashboard.services.timezone.now', return_value=self.instante):
            return self.client.get(reverse(f'dashboard:{secao}'), parametros or {})

    def test_horizontes_defaults_normalizacao_e_preenchimento(self):
        escopo = self.escopo()
        for invalido in (None, '', 'abc', '0', '-3', '4', '13', '3.0', '03', ' 6', '9' * 5000):
            self.assertEqual(normalizar_horizonte(invalido), 12)
        for leitor, metricas in (
            (ler_series_vendas, ('compras', 'volume', 'ticket')),
            (ler_series_fidelidade, ('pontos_concedidos', 'pontos_resgatados', 'custo_resgates')),
        ):
            for horizonte in (None, '3', '6', '12', 'invalido'):
                parametros = {f'{m}_meses': horizonte for m in metricas} if horizonte else {}
                series = leitor(escopo, parametros, referencia=self.instante)
                tamanho = int(horizonte) if horizonte in ('3', '6', '12') else 12
                for metrica, linhas in series.items():
                    with self.subTest(metrica=metrica, horizonte=horizonte):
                        self.assertEqual(len(linhas), tamanho)
                        self.assertEqual(linhas[-1]['mes'], date(2026, 9, 1))
                        self.assertEqual([r['mes'] for r in linhas], sorted(r['mes'] for r in linhas))
                        self.assertTrue(all(r['valor'] == (None if metrica == 'ticket' else 0) for r in linhas))

    def test_vendas_independentes_ticket_mensal_e_cutoff_inclusivo(self):
        self.compra(instante=self.instante.replace(month=6), valor='900')
        self.compra(instante=self.instante.replace(month=8), valor='100')
        self.compra(instante=self.instante.replace(month=8), valor='300')
        self.compra(valor='90')
        self.compra(instante=self.instante + timedelta(microseconds=1), valor='9999')
        escopo = self.escopo()
        with self.assertNumQueries(1):
            series = ler_series_vendas(escopo, {
                'compras_meses': 12, 'volume_meses': 6, 'ticket_meses': 3,
            }, referencia=self.instante)
        self.assertEqual([len(series[m]) for m in ('compras', 'volume', 'ticket')], [12, 6, 3])
        self.assertEqual([r['valor'] for r in series['compras'][-3:]], [0, 2, 1])
        self.assertEqual([r['valor'] for r in series['volume'][-3:]], [0, 400, 90])
        # Sem compras é None; agosto é (100 + 300) / 2, sem média de médias.
        self.assertEqual([r['valor'] for r in series['ticket']], [None, Decimal('200'), Decimal('90')])
        outro = ler_series_vendas(escopo, {
            'compras_meses': 3, 'volume_meses': 6, 'ticket_meses': 3,
        }, referencia=self.instante)
        self.assertEqual(outro['compras'], series['compras'][-3:])
        self.assertEqual(outro['volume'], series['volume'])
        self.assertEqual(outro['ticket'], series['ticket'])

    def test_calendario_virada_de_ano_inicio_e_timezone_atual(self):
        inicio = self.instante.replace(year=2025, month=10, day=1, hour=0, minute=0)
        self.compra(instante=inicio - timedelta(microseconds=1), valor='99')
        self.compra(instante=inicio, valor='10')
        dezembro = self.instante.replace(year=2025, month=12, day=31, hour=23)
        # Já é janeiro em UTC; continua dezembro em São Paulo.
        self.compra(instante=dezembro.astimezone(utc_timezone.utc), valor='20')
        self.compra(instante=dezembro + timedelta(hours=1), valor='30')
        escopo = self.escopo()
        with timezone.override('America/Sao_Paulo'):
            vendas = ler_series_vendas(escopo, {}, referencia=self.instante)
            fidelidade = ler_series_fidelidade(escopo, {}, referencia=self.instante)
        volumes = {r['mes']: r['valor'] for r in vendas['volume']}
        self.assertEqual(volumes[date(2025, 10, 1)], 10)
        self.assertEqual(volumes[date(2025, 12, 1)], 20)
        self.assertEqual(volumes[date(2026, 1, 1)], 30)
        self.assertEqual(fidelidade['pontos_concedidos'], vendas['volume'])
        with timezone.override('UTC'):
            utc = ler_series_vendas(escopo, {}, referencia=self.instante)
        volumes_utc = {r['mes']: r['valor'] for r in utc['volume']}
        self.assertEqual(volumes_utc[date(2025, 10, 1)], 109)
        self.assertEqual(volumes_utc[date(2025, 12, 1)], 0)
        self.assertEqual(volumes_utc[date(2026, 1, 1)], 50)

    def test_concessoes_por_ocorrencia_resgates_por_data_e_custo_historico(self):
        self.configurar(validade_pontos_meses=24)
        self.compra(instante=self.instante.replace(month=6), valor='2000')
        self.compra(valor='40')
        self.compra(instante=self.instante + timedelta(microseconds=1), valor='9000')
        with patch.object(self, 'instante', self.instante.replace(month=7)):
            self.resgatar(pontos=200)
        self.estornar()
        with patch.object(self, 'instante', self.instante.replace(month=8)):
            self.resgatar(identificador_externo='R2', pontos=300)
        self.resgatar(identificador_externo='R3', pontos=100)
        with patch.object(self, 'instante', self.instante + timedelta(microseconds=1)):
            self.resgatar(identificador_externo='FUTURO', pontos=100)
        self.configurar(valor_monetario_por_ponto=Decimal('0.90'))
        escopo = self.escopo()
        with self.assertNumQueries(2):
            series = ler_series_fidelidade(escopo, {
                'pontos_concedidos_meses': 6, 'pontos_resgatados_meses': 12,
                'custo_resgates_meses': 3,
            }, referencia=self.instante)
        self.assertEqual([len(s) for s in series.values()], [6, 12, 3])
        self.assertEqual([r['valor'] for r in series['pontos_concedidos']], [0, 0, 2000, 0, 0, 40])
        self.assertEqual([r['valor'] for r in series['pontos_resgatados'][-3:]], [200, 300, 100])
        self.assertEqual([r['valor'] for r in series['custo_resgates']], [0, 15, 5])

    def test_resgate_mes_local_e_referencia_as_of(self):
        self.configurar(validade_pontos_meses=24)
        self.compra(instante=self.instante.replace(year=2025, month=12, day=1), valor='1000')
        dezembro = self.instante.replace(year=2025, month=12, day=31, hour=23)
        with patch.object(self, 'instante', dezembro.astimezone(utc_timezone.utc)):
            self.resgatar()
        self.resgatar(identificador_externo='ATUAL', pontos=200)
        # O estorno posterior não exclui o custo nesta referência histórica.
        with patch.object(self, 'instante', self.instante + timedelta(days=1)):
            self.estornar()
            self.resgatar(identificador_externo='FUTURO', pontos=100)
        series = ler_series_fidelidade(self.escopo(), {}, referencia=self.instante)
        pontos = {r['mes']: r['valor'] for r in series['pontos_resgatados']}
        custos = {r['mes']: r['valor'] for r in series['custo_resgates']}
        self.assertEqual(pontos[date(2025, 12, 1)], 100)
        self.assertEqual(pontos[date(2026, 1, 1)], 0)
        self.assertEqual(custos[date(2025, 12, 1)], 5)
        self.assertEqual(sum(pontos.values()), 300)
        self.assertEqual(sum(custos.values()), 15)
        totais = self.ler()
        self.assertEqual(totais['pontos_resgatados'], sum(pontos.values()))
        self.assertEqual(totais['custo_resgates'], 15)

    def test_series_respeitam_empresa_lojas_e_gestor(self):
        self.compra(valor='1000')
        self.compra(loja=self.segunda, valor='2000')
        self.resgatar()
        self.resgatar(loja_id=self.segunda.pk, identificador_externo='SEGUNDA', pontos=200)
        credencial, _ = self.emitir(membro=self.outro_membro)
        self.lote('9000', credencial=credencial, loja_id=self.externa.pk,
                  cliente_cpf=self.cliente_externo.usuario.cpf)
        self.resgatar(credencial=credencial, loja_id=self.externa.pk,
                      cliente_cpf=self.cliente_externo.usuario.cpf, pontos=900)
        for leitor, campo, valor_gestor, valor_admin in (
            (ler_series_vendas, 'volume', 1000, 3000),
            (ler_series_fidelidade, 'pontos_concedidos', 1000, 3000),
            (ler_series_fidelidade, 'pontos_resgatados', 100, 300),
            (ler_series_fidelidade, 'custo_resgates', 5, 15),
        ):
            gestor = leitor(self.escopo(self.gestor), {}, referencia=self.instante)
            filtrado = leitor(self.escopo(loja=self.loja), {}, referencia=self.instante)
            admin = leitor(self.escopo(), {}, referencia=self.instante)
            self.assertEqual(gestor, filtrado)
            self.assertEqual(gestor[campo][-1]['valor'], valor_gestor)
            self.assertEqual(admin[campo][-1]['valor'], valor_admin)
            if campo in ('pontos_resgatados', 'custo_resgates'):
                self.assertEqual(self.ler(self.gestor)[campo], valor_gestor)
                self.assertEqual(self.ler(loja=self.loja)[campo], valor_gestor)
                self.assertEqual(self.ler()[campo], valor_admin)

    def chart_json(self, resposta, nome):
        html = resposta.content.decode()
        payload = re.search(rf'<script id="dashboard-json-{nome}" type="application/json">(.*?)</script>', html).group(1)
        self.assertNotIn('<', payload)
        self.assertNotIn('&', payload)
        return json.loads(payload)

    def test_graficos_fidelidade_series_periodos_e_fallback(self):
        self.entrar()
        self.compra(valor='123.45')
        resposta = self.pagina('fidelidade', {
            'pontos_concedidos_meses': 3, 'pontos_resgatados_meses': 6,
            'custo_resgates_meses': 12,
        })
        self.assertContains(resposta, 'data-chart-type="line"', count=3)
        self.assertContains(resposta, '<summary>Ver dados</summary>', count=3)
        for nome, meses in (('pontos_concedidos', 3), ('pontos_resgatados', 6), ('custo_resgates', 12)):
            linhas = self.chart_json(resposta, nome)
            self.assertEqual(len(linhas), meses)
            self.assertTrue(all(set(linha) == {'mes', 'valor'} for linha in linhas))
            self.assertEqual([Decimal(str(linha['valor'])) for linha in linhas],
                             [linha['valor'] for linha in resposta.context['dashboard_series'][nome]])
            self.assertEqual(Decimal(str(linhas[0]['valor'])), 0)
            self.assertContains(resposta, f'name="{nome}_meses" value="{meses}"')
        self.assertContains(resposta, 'retorna-mobile-presentation')
        self.assertContains(resposta, 'retorna-desktop-presentation')

    def test_recompra_chart_base_janela_e_sem_base(self):
        self.entrar()
        self.configurar(periodo_recompra_dias=30)
        vazio = self.pagina('fidelidade')
        self.assertContains(vazio, 'Sem base suficiente')
        self.assertNotContains(vazio, 'dashboard-json-recompra')
        self.assertNotContains(vazio, 'data-chart-type="bar"')
        self.compra(40)
        self.compra(20)
        self.compra(40, cliente=self.outro_cliente)
        resposta = self.pagina('fidelidade')
        self.assertContains(resposta, 'Taxa de recompra em até 30 dias')
        self.assertContains(resposta, '50%')
        self.assertContains(resposta, '1 de 2 clientes elegíveis')
        self.assertContains(resposta, 'data-chart-type="bar"', count=1)
        self.assertEqual(self.chart_json(resposta, 'recompra'), [
            {'nome': 'Voltaram', 'valor': 1}, {'nome': 'Não voltaram', 'valor': 1},
        ])

    def test_niveis_chart_admin_nomes_configuraveis_zero_e_gestor(self):
        self.entrar()
        vazio = self.pagina('fidelidade')
        self.assertContains(vazio, 'Nenhum nível configurado.')
        self.assertNotContains(vazio, 'dashboard-json-niveis')
        nome = 'Horizonte </script> & livre'
        criar_nivel(self.request(), nome=nome, pontos_minimos=Decimal('0'))
        criar_nivel(self.request(), nome='Constelação', pontos_minimos=Decimal('1000'))
        zerado = self.pagina('fidelidade')
        self.assertContains(zerado, 'Nenhum cliente nos níveis configurados')
        self.assertNotContains(zerado, 'data-chart-type="doughnut"')
        self.assertNotContains(zerado, 'dashboard-json-niveis')
        self.compra()
        resposta = self.pagina('fidelidade')
        self.assertContains(resposta, 'data-chart-type="doughnut"', count=1)
        self.assertContains(resposta, 'id="legenda-niveis"')
        self.assertContains(resposta, 'Horizonte &lt;/script&gt; &amp; livre')
        self.assertEqual(self.chart_json(resposta, 'niveis'), [
            {'nome': nome, 'quantidade': 1}, {'nome': 'Constelação', 'quantidade': 0},
        ])
        self.entrar(self.gestor)
        with patch('apps.dashboard.services.clientes_com_nivel') as classificar:
            gestor = self.pagina('fidelidade')
        classificar.assert_not_called()
        for texto in ('dashboard-json-niveis', 'data-chart-type="doughnut"',
                      'distribuicao-niveis', 'Distribuição por nível', nome):
            self.assertNotContains(gestor, texto)

    def test_links_visao_geral_fidelidade_preservam_so_loja(self):
        self.entrar()
        resposta = self.pagina('inicio', {'loja': self.loja.pk, 'compras_meses': 3})
        links = [link['href'] for link in ControlesDashboardParser(resposta.content.decode()).links
                 if urlsplit(link.get('href', '')).fragment in
                 ('recompra', 'pontos-concedidos', 'pontos-resgatados', 'custo-resgates')]
        self.assertEqual(len(links), 4)
        for link in links:
            destino = urlsplit(link)
            self.assertEqual(destino.path, reverse('dashboard:fidelidade'))
            self.assertEqual(parse_qs(destino.query), {'loja': [str(self.loja.pk)]})
            destino_html = self.pagina('fidelidade').content.decode()
            self.assertIn(f'id="{destino.fragment}"', destino_html)

    def test_graficos_vendas_json_fallback_e_ausencia(self):
        self.entrar()
        resposta = self.pagina('vendas', {
            'compras_meses': 3, 'volume_meses': 6, 'ticket_meses': 12,
        })
        self.assertContains(resposta, '<canvas', count=3)
        self.assertContains(resposta, '<summary>Ver dados</summary>', count=3)
        self.assertContains(resposta, 'Sem dados')
        html = resposta.content.decode()
        for metrica, meses in (('compras', 3), ('volume', 6), ('ticket', 12)):
            fonte = f'dashboard-json-{metrica}'
            self.assertContains(resposta, f'data-chart-json="{fonte}"', count=1)
            self.assertContains(resposta, f'aria-labelledby="dashboard-{metrica}"', count=2)
            payload = re.search(rf'<script id="{fonte}" type="application/json">(.*?)</script>', html).group(1)
            linhas = json.loads(payload)
            self.assertEqual(len(linhas), meses)
            self.assertTrue(all(set(linha) == {'mes', 'valor'} for linha in linhas))
            self.assertEqual([linha['mes'] for linha in linhas], sorted(linha['mes'] for linha in linhas))
            self.assertTrue(all(linha['valor'] is None for linha in linhas) if metrica == 'ticket'
                            else all(Decimal(str(linha['valor'])) == 0 for linha in linhas))
        for secao in ('inicio', 'clientes'):
            outra = self.pagina(secao)
            self.assertNotContains(outra, 'data-chart-json')
            self.assertNotContains(outra, 'id="dashboard-json-')
        # Exercise the actual template's safe serialization against a script terminator.
        from django.template.loader import render_to_string
        perigoso = '</script><script>alert(1)</script>&'
        renderizado = render_to_string('datasystem/gestor/dashboard/series.html', {
            'graficos': True, 'series_temporais': [{
                'chave': 'compras', 'titulo': 'Compras', 'meses': 3,
                'unidade': '', 'casas': '0', 'opcoes': [],
                'linhas': [{'mes': self.instante.date(), 'valor': perigoso}],
            }],
        })
        payload = re.search(r'type="application/json">(.*?)</script>', renderizado).group(1)
        self.assertNotIn('<', payload)
        self.assertNotIn('&', payload)
        self.assertEqual(json.loads(payload)[0]['valor'], perigoso)

    def test_controles_get_preservam_loja_outros_periodos_e_isolam_topbar(self):
        self.entrar()
        self.compra(valor='200')
        self.compra(loja=self.segunda, valor='800')
        for secao, metricas in (
            ('vendas', ('compras', 'volume', 'ticket')),
            ('fidelidade', ('pontos_concedidos', 'pontos_resgatados', 'custo_resgates')),
        ):
            periodos = {f'{m}_meses': str(h) for m, h in zip(metricas, (12, 6, 3))}
            parametros = {'loja': str(self.loja.pk), **periodos}
            resposta = self.pagina(secao, parametros)
            self.assertEqual(resposta.status_code, 200)
            html = resposta.content.decode()
            self.assertLess(html.index('retorna-dashboard-filter'), html.index('Atualizado em'))
            self.assertLess(html.index('Atualizado em'), html.index('retorna-dashboard-nav'))
            parser = ControlesDashboardParser(html)
            links_periodos = [a for a in parser.links if urlsplit(a.get('href', '')).fragment.startswith('dashboard-')]
            self.assertEqual(len(links_periodos), 9)
            self.assertEqual(sum(a.get('aria-current') == 'true' for a in links_periodos), 3)
            for link in links_periodos:
                destino = urlsplit(link['href'])
                metrica = destino.fragment.removeprefix('dashboard-')
                query = parse_qs(destino.query)
                self.assertEqual(destino.path, reverse(f'dashboard:{secao}'))
                self.assertEqual(query['loja'], [str(self.loja.pk)])
                self.assertEqual(set(query), set(parametros))
                for parametro, valor in periodos.items():
                    if parametro != f'{metrica}_meses':
                        self.assertEqual(query[parametro], [valor])
            # Segue um link de verdade para alterar somente o primeiro horizonte.
            link = next(a['href'] for a in links_periodos
                        if urlsplit(a['href']).fragment == f'dashboard-{metricas[0]}'
                        and parse_qs(urlsplit(a['href']).query)[f'{metricas[0]}_meses'] == ['3'])
            with patch('apps.dashboard.services.timezone.now', return_value=self.instante):
                alterada = self.client.get(link)
            self.assertEqual(alterada.status_code, 200)
            self.assertEqual(alterada.context['escopo'].loja_selecionada, self.loja)
            self.assertEqual(alterada.context['dashboard'], resposta.context['dashboard'])
            for metrica in metricas[1:]:
                self.assertEqual(alterada.context['dashboard_series'][metrica], resposta.context['dashboard_series'][metrica])
            self.assertEqual(len(alterada.context['dashboard_series'][metricas[0]]), 3)
            formulario = next(f for f in parser.formularios if 'retorna-dashboard-filter' in f.get('class', ''))
            self.assertEqual(formulario['method'], 'get')
            self.assertEqual(formulario['campos'], periodos)
            for loja in (str(self.segunda.pk), ''):
                trocada = self.pagina(secao, {**formulario['campos'], 'loja': loja})
                self.assertEqual(trocada.status_code, 200)
                self.assertEqual(trocada.context['dashboard_periodos'], {k: int(v) for k, v in periodos.items()})
                self.assertEqual(trocada.context['escopo'].loja_selecionada, self.segunda if loja else None)
            nav = html.split('aria-label="Seções do Dashboard">', 1)[1].split('</nav>', 1)[0]
            for link in ControlesDashboardParser(nav).links:
                self.assertEqual(parse_qs(urlsplit(link['href']).query), {'loja': [str(self.loja.pk)]})
            for chave in self.secoes:
                self.assertIn(reverse(f'dashboard:{chave}'), nav)

    def test_http_defaults_query_invalida_sem_dados_e_sem_filtro_temporal_global(self):
        self.entrar()
        for secao, metricas in (
            ('vendas', ('compras', 'volume', 'ticket')),
            ('fidelidade', ('pontos_concedidos', 'pontos_resgatados', 'custo_resgates')),
        ):
            for valor in (None, 'abc'):
                params = {f'{m}_meses': valor for m in metricas} if valor else {}
                resposta = self.pagina(secao, params)
                self.assertEqual(resposta.status_code, 200)
                self.assertEqual(resposta.context['dashboard_periodos'], {f'{m}_meses': 12 for m in metricas})
                for serie in resposta.context['dashboard_series'].values():
                    self.assertEqual(len(serie), 12)
                if secao == 'vendas':
                    self.assertContains(resposta, 'Sem dados')
                else:
                    self.assertContains(resposta, 'Sem base suficiente')
                    self.assertContains(resposta, 'Elegíveis: 0 · Voltaram: 0 · Não voltaram: 0')
            if secao not in ('vendas', 'fidelidade'):
                self.assertNotContains(resposta, '<canvas')
        self.compra(200)
        self.compra(100)
        self.compra(200, cliente=self.outro_cliente)
        for secao in self.secoes:
            inicial = self.pagina(secao)
            alterada = self.pagina(secao, {
                'compras_meses': 3, 'volume_meses': 6, 'ticket_meses': 12,
                'pontos_concedidos_meses': 6, 'pontos_resgatados_meses': 3,
                'custo_resgates_meses': 12, 'recompra_meses': 3,
            })
            self.assertEqual(inicial.context['dashboard'], alterada.context['dashboard'])
            if secao in ('inicio', 'clientes'):
                self.assertEqual(alterada.context['dashboard_periodos'], {})
                self.assertEqual(alterada.context['dashboard_series'], {})
            if secao == 'fidelidade':
                recompra = alterada.context['dashboard']['recompra']
                self.assertEqual((recompra['elegiveis'], recompra['recompraram'], recompra['nao_recompraram']), (2, 1, 1))
                self.assertEqual(recompra['percentual'], Decimal('50'))
                self.assertContains(alterada, 'Elegíveis: 2 · Voltaram: 1 · Não voltaram: 1')

    def test_ativos_inativos_no_universo_e_analises_somente_na_secao(self):
        self.configurar(periodo_cliente_ativo_dias=30)
        self.compra(100)
        self.compra(cliente=self.outro_cliente)
        for membro in (self.membro, self.gestor):
            dados = self.ler(membro, secao='clientes')
            self.assertEqual(dados['clientes_ativos'], 1)
            self.assertEqual(dados['clientes_inativos'], 1)
            self.assertEqual(dados['clientes_ativos'] + dados['clientes_inativos'], dados['clientes_no_escopo'])
        with patch('apps.dashboard.services.clientes_com_nivel') as niveis, \
                patch('apps.dashboard.services._serie_compras') as serie:
            for secao in self.secoes:
                dados = self.ler(self.gestor, secao=secao)
                if secao != 'clientes':
                    self.assertEqual(dados['ranking'], [])
            for secao in ('inicio', 'vendas', 'clientes'):
                self.ler(secao=secao)
        niveis.assert_not_called()
        serie.assert_not_called()


    def test_resgates_e_estornos_as_of_limites_kpi_e_serie(self):
        referencia = self.instante
        self.compra(instante=referencia.replace(month=7), valor='3000')
        casos = (
            ('SEM-ESTORNO', referencia.replace(month=8), None, 100, 5),
            ('ESTORNO-ANTES', referencia.replace(month=8), referencia - timedelta(microseconds=1), 200, 0),
            ('ESTORNO-IGUAL', referencia.replace(month=8), referencia, 300, 0),
            ('ESTORNO-DEPOIS', referencia.replace(month=8), referencia + timedelta(microseconds=1), 400, 20),
            ('RESGATE-IGUAL', referencia, None, 500, 25),
            ('RESGATE-FUTURO', referencia + timedelta(microseconds=1), None, 600, 0),
        )
        pontos_esperados = custo_esperado = 0
        escopo = self.escopo()
        for chave, resgatado_em, estornado_em, pontos, custo in casos:
            with self.subTest(caso=chave):
                with patch.object(self, 'instante', resgatado_em):
                    self.resgatar(identificador_externo=chave, pontos=pontos)
                if estornado_em is not None:
                    with patch.object(self, 'instante', estornado_em):
                        self.estornar(resgate_identificador_externo=chave, identificador_externo=chave)
                if resgatado_em <= referencia:
                    pontos_esperados += pontos
                custo_esperado += custo
                # Helpers devem usar a referência recebida, nunca ler o relógio.
                with patch('apps.dashboard.services.timezone.now', side_effect=AssertionError('Nova referência')):
                    totais = ler_dashboard(escopo, referencia=referencia)
                    series = ler_series_fidelidade(escopo, {}, referencia=referencia)
                self.assertEqual(totais['pontos_resgatados'], pontos_esperados)
                self.assertEqual(totais['custo_resgates'], custo_esperado)
                for campo in ('pontos_resgatados', 'custo_resgates'):
                    self.assertEqual(sum(r['valor'] for r in series[campo]), totais[campo])
        custos = {r['mes']: r['valor'] for r in series['custo_resgates']}
        self.assertEqual(custos[date(2026, 8, 1)], 25)
        self.assertEqual(custos[date(2026, 9, 1)], 25)
        self.configurar(valor_monetario_por_ponto=Decimal('0.90'))
        # Avançar até os fatos futuros inclui o Resgate e efetiva o Estorno,
        # mantendo valor persistido e atribuição ao mês original do Resgate.
        depois = referencia + timedelta(microseconds=1)
        totais_depois = ler_dashboard(escopo, referencia=depois)
        series_depois = ler_series_fidelidade(escopo, {}, referencia=depois)
        self.assertEqual(totais_depois['pontos_resgatados'], 2100)
        self.assertEqual(totais_depois['custo_resgates'], 60)
        self.assertEqual(series_depois['custo_resgates'][-2]['valor'], 5)
        self.assertEqual(series_depois['custo_resgates'][-1]['valor'], 55)
        for campo in ('pontos_resgatados', 'custo_resgates'):
            self.assertEqual(sum(r['valor'] for r in series_depois[campo]), totais_depois[campo])

    def test_request_fidelidade_reutiliza_referencia_unica_em_kpi_e_series(self):
        self.compra(valor='1000')
        self.resgatar()
        with patch.object(self, 'instante', self.instante + timedelta(microseconds=1)):
            self.estornar()
            self.resgatar(identificador_externo='FUTURO', pontos=200)
        self.entrar()
        # Isola o relógio do service dos relógios de sessão/autenticação do Django.
        with patch('apps.dashboard.services.timezone', wraps=timezone) as relogio:
            relogio.now.side_effect = [self.instante]
            resposta = self.client.get(reverse('dashboard:fidelidade'))
        relogio.now.assert_called_once_with()
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.context['dashboard']
        self.assertEqual(dados['referencia'], self.instante)
        self.assertEqual(dados['pontos_resgatados'], 100)
        self.assertEqual(dados['custo_resgates'], 5)
        for campo in ('pontos_resgatados', 'custo_resgates'):
            self.assertEqual(sum(r['valor'] for r in resposta.context['dashboard_series'][campo]), dados[campo])
