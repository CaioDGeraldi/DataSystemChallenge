from datetime import date, timedelta, timezone as utc_timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse

from apps.clientes.models import Cliente
from apps.empresas.models import AcessoLoja, MembroEmpresa
from apps.fidelidade.niveis import classificar_cliente, criar_nivel
from apps.fidelidade.test_estornos import DadosEstornos
from apps.usuarios.services import CONTEXTO_SESSAO
from .services import ler_dashboard, resolver_escopo_dashboard


class DashboardTests(DadosEstornos, TestCase):
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

    def ler(self, membro=None, loja=None):
        return ler_dashboard(self.escopo(membro, loja), referencia=self.instante)

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
        self.assertEqual(dados, dict(elegiveis=2, recompraram=1,
                                     percentual=Decimal('50'), periodo_recompra_dias=30))

    def test_ranking_limite_desempate_e_pontos_fora_do_escopo(self):
        # CPFs válidos gerados deterministicamente para ampliar o universo.
        for n in range(12):
            cpf = str(100000000 + n)
            for tamanho in (9, 10):
                soma = sum(int(d) * (tamanho + 1 - i) for i, d in enumerate(cpf))
                digito = 11 - soma % 11
                cpf += str(0 if digito >= 10 else digito)
            usuario = get_user_model().objects.create_user(cpf)
            cliente = Cliente.objects.create(usuario=usuario, empresa=self.empresa)
            self.compra(cliente=cliente)
        self.compra(loja=self.segunda, valor='99999')
        ranking = self.ler(self.gestor)['ranking']
        ids = list(Cliente.objects.filter(empresa=self.empresa).exclude(
            pk__in=[self.cliente.pk, self.outro_cliente.pk],
        ).order_by('pk').values_list('pk', flat=True))
        self.assertEqual([r['cliente_id'] for r in ranking], ids[:10])
        self.assertEqual(len(ranking), 10)
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
            for loja in invalidos:
                with self.subTest(membro=membro.pk, loja=loja), patch('apps.dashboard.views.ler_dashboard') as ler:
                    resposta = self.client.get(reverse('dashboard:inicio'), {'loja': loja})
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
                      'Nenhum cliente no ranking', 'Nenhuma compra',
                      'retorna-mobile-presentation', 'retorna-desktop-presentation',
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
                      'Pontos concedidos', 'Top 10 clientes por pontos concedidos',
                      'Pontos usados em resgates, inclusive os que foram estornados.'):
            self.assertContains(resposta, texto)
        for texto in ('histórico', 'Histórico', 'Lojas permitidas', 'lojas autorizadas'):
            self.assertNotContains(resposta, texto)
        resposta = self.client.get(reverse('dashboard:inicio'), {'loja': self.loja.pk})
        self.assertEqual(resposta.context['escopo'].loja_selecionada, self.loja)
        self.assertContains(resposta, f'value="{self.loja.pk}" selected')
        self.entrar()
        resposta = self.client.get(reverse('dashboard:inicio'))
        self.assertContains(resposta, 'Nenhum nível configurado')
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
        resposta = self.client.get(reverse('dashboard:inicio'))
        self.assertContains(resposta, '<td>Ana Silva</td>', html=True)
        self.assertContains(resposta, '<h3>Ana Silva</h3>', html=True)
        self.assertContains(resposta, '<td class="numeric">123</td>', html=True)
        self.assertContains(resposta, '<dd>123</dd>', html=True)
        self.assertNotContains(resposta, f'#{self.cliente.pk}')
        self.assertEqual(resposta.context['dashboard']['ranking'][0]['cliente_id'], self.cliente.pk)

    def test_cliente_nao_acessa_e_gestor_sem_acesso_tem_vazio(self):
        self.entrar(cliente=True)
        with patch('apps.dashboard.views.ler_dashboard') as ler:
            self.assertEqual(self.client.get(reverse('dashboard:inicio')).status_code, 403)
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
