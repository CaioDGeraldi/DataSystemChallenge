from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.fidelidade.consultas import _saldo_atual
from apps.fidelidade.niveis import criar_nivel
from apps.fidelidade.test_estornos import DadosEstornos
from apps.usuarios.services import CONTEXTO_SESSAO

from .consultas import proxima_expiracao, ranking_pessoal, resumo_cliente
from .models import Cliente


class AreaClienteTests(DadosEstornos, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)
        self.ativar(self.cliente)
        self.relogio = patch('apps.clientes.consultas.timezone.now', return_value=self.instante)
        self.relogio.start()
        self.addCleanup(self.relogio.stop)

    def ativar(self, vinculo, tipo='cliente'):
        sessao = self.client.session
        sessao[CONTEXTO_SESSAO] = {
            'tipo_contexto': tipo, 'empresa_id': vinculo.empresa_id, 'vinculo_id': vinculo.pk,
        }
        sessao.save()

    def home(self):
        return self.client.get(reverse('clientes:area'))

    def nivel(self, nome='Semente', minimo='0', bonus='20', desconto='10'):
        return criar_nivel(self.request(), nome=nome, pontos_minimos=Decimal(minimo),
                           bonus_pontos_percentual=Decimal(bonus), desconto_percentual=Decimal(desconto))

    def test_home_vazia_e_markup_das_tres_paginas(self):
        for rota, titulo in [('area', 'Olá, Ana!'), ('pontos', 'Meus pontos'), ('resgates', 'Meus resgates')]:
            resposta = self.client.get(reverse(f'clientes:{rota}'))
            self.assertContains(resposta, titulo)
            self.assertTemplateUsed(resposta, 'datasystem/cliente/base.html')
            self.assertTemplateNotUsed(resposta, 'datasystem/gestao_base.html')
            for link in ('area', 'pontos', 'resgates'):
                self.assertContains(resposta, reverse(f'clientes:{link}'))
            self.assertContains(resposta, 'class="cliente-nav"')
            self.assertContains(resposta, 'aria-current="page"', count=1)
            self.assertContains(resposta, 'aria-label="Seu programa de fidelidade"')
            self.assertContains(resposta, 'aria-hidden="true"', count=3)
            self.assertContains(resposta, 'for="cliente-programa"')
            self.assertContains(resposta, 'href="#conteudo"')
            self.assertContains(resposta, 'csrfmiddlewaretoken')
            for termo in ('FEFO', 'snapshot', 'tenant', 'LotePontos', 'pontos históricos', 'ATINGIDO_NA_COMPRA'):
                self.assertNotContains(resposta, termo)
        resposta = self.home()
        self.assertEqual(resposta.context['saldo'], 0)
        self.assertEqual(resposta.context['ranking'], {'acumulado': None, 'disponivel': None})
        self.assertContains(resposta, 'ainda não possui níveis')

    def test_saldo_consumo_parcial_e_proxima_expiracao_agrupada(self):
        lote = self.lote('300.00')
        self.lote('50.00')
        self.resgatar()
        resposta = self.home()
        self.assertEqual(resposta.context['saldo'], Decimal('250'))
        self.assertEqual(resposta.context['pontos_nivel'], Decimal('350'))
        self.assertEqual(resposta.context['expiracao']['pontos'], Decimal('250'))
        self.assertEqual(resposta.context['expiracao']['expira_em'], lote.expira_em)
        self.assertGreater(resposta.context['expiracao']['dias'], 60)

    def test_expiracao_ignora_lote_consumido_e_limite_expirado(self):
        primeiro = self.lote()
        self.resgatar()
        segundo = self.lote('200.00', ocorrida_em=self.instante + timedelta(days=1))
        self.assertEqual(proxima_expiracao(self.cliente, self.instante)['expira_em'], segundo.expira_em)
        self.assertIsNone(proxima_expiracao(self.cliente, segundo.expira_em))
        self.assertEqual(_saldo_atual(self.cliente.pk, primeiro.expira_em), Decimal('200'))

    def test_nivel_progresso_beneficios_e_nivel_maximo(self):
        self.lote('300.00')
        self.nivel()
        proximo = self.nivel('Floresta', '500')
        resposta = self.home()
        self.assertEqual(resposta.context['nivel'].nome, 'Semente')
        self.assertEqual(resposta.context['proximo_nivel'], proximo)
        self.assertEqual(resposta.context['faltam'], Decimal('200'))
        self.assertContains(resposta, '+20% em pontos')
        self.assertContains(resposta, '10% de desconto')
        self.assertContains(resposta, '<progress id="progresso-nivel" value="300.0000" max="500.0000">')
        self.lote('200.00')
        self.assertContains(self.home(), 'Seu nível atual é o mais alto disponível.')

    def test_retorno_e_beneficios_suspensos(self):
        self.lote(ocorrida_em=self.instante - timedelta(days=181))
        self.nivel()
        self.configurar(inatividade_suspende_beneficios_nivel=True,
                        beneficio_primeira_compra_apos_inatividade='SEM_BENEFICIOS_NIVEL',
                        promocao_retorno_ativa=True, bonus_pontos_retorno_percentual=Decimal('15'),
                        desconto_retorno_percentual=Decimal('10'))
        resposta = self.home()
        self.assertContains(resposta, 'Sentimos sua falta.')
        self.assertContains(resposta, '+15% em pontos')
        self.assertContains(resposta, 'benefícios do seu nível estão suspensos')
        self.assertNotContains(resposta, '+20% em pontos')

    def test_primeira_compra_nao_anuncia_retorno(self):
        self.configurar(promocao_retorno_ativa=True)
        self.assertNotContains(self.home(), 'Sentimos sua falta.')

    def test_compras_usa_snapshot_e_ultima_compra(self):
        self.nivel()
        self.lote('300.00')
        self.configurar(pontos_por_real=Decimal('99'))
        resposta = self.client.get(reverse('clientes:pontos'))
        self.assertContains(resposta, '360 pontos ganhos')
        self.assertContains(resposta, '+60 pelo seu nível')
        self.assertContains(resposta, 'R$ 300,00')
        self.assertContains(resposta, 'Centro')
        self.assertContains(self.home(), '+360 pontos')

    def test_resgate_sem_estorno(self):
        self.lote('300.00')
        self.resgatar(pontos=200)
        resposta = self.client.get(reverse('clientes:resgates'))
        self.assertContains(resposta, '200 pontos usados')
        self.assertContains(resposta, 'R$ 10,00 de desconto')
        self.assertContains(resposta, 'Resgate realizado.')

    def test_estorno_com_devolucao(self):
        self.lote('300.00')
        self.resgatar()
        self.estornar()
        resposta = self.client.get(reverse('clientes:resgates'))
        self.assertContains(resposta, 'O uso dos pontos foi desfeito')
        self.assertEqual(self.home().context['saldo'], Decimal('300'))
        self.assertEqual(self.home().context['expiracao']['pontos'], Decimal('300'))

    def test_estorno_sem_devolucao_preserva_consumo_historico(self):
        self.lote('300.00')
        self.resgatar()
        self.configurar(devolver_pontos_ao_estornar_resgate=False)
        self.estornar()
        self.configurar(devolver_pontos_ao_estornar_resgate=True)
        resposta = self.client.get(reverse('clientes:resgates'))
        self.assertContains(resposta, 'Este cancelamento não devolveu pontos')
        self.assertNotContains(resposta, 'O uso dos pontos foi desfeito')
        self.assertEqual(self.home().context['saldo'], Decimal('200'))
        self.assertEqual(self.home().context['expiracao']['pontos'], Decimal('200'))

    def test_estorno_de_lote_expirado_nao_promete_saldo_devolvido(self):
        lote = self.lote()
        self.resgatar()
        self.instante = lote.expira_em
        self.estornar()
        self.assertEqual(_saldo_atual(self.cliente.pk, self.instante), 0)
        self.assertContains(self.client.get(reverse('clientes:resgates')), 'A validade original continua valendo')

    def test_ranking_empates_compartilham_posicao_e_deixam_saltos(self):
        terceiro = Cliente.objects.create(usuario=self.sem_vinculo, empresa=self.empresa)
        self.lote('300.00')
        self.lote('300.00', cliente_cpf=self.outro_usuario.cpf)
        self.lote('100.00', cliente_cpf=self.sem_vinculo.cpf)
        self.assertEqual(self.home().context['ranking'], {'acumulado': 1, 'disponivel': 1})
        self.assertEqual(ranking_pessoal(terceiro, self.instante, Decimal('100'), Decimal('100')),
                         {'acumulado': 3, 'disponivel': 3})
        self.resgatar(pontos=200)
        self.assertEqual(self.home().context['ranking'], {'acumulado': 1, 'disponivel': 2})
        self.assertNotContains(self.home(), self.outro_usuario.cpf)

    def test_ranking_disponivel_considera_estorno_e_expiracao(self):
        self.lote('300.00')
        self.lote('500.00', cliente_cpf=self.outro_usuario.cpf)
        self.resgatar(cliente_cpf=self.outro_usuario.cpf, pontos=300)
        self.assertEqual(self.home().context['ranking']['disponivel'], 1)
        self.estornar()
        self.assertEqual(self.home().context['ranking']['disponivel'], 2)
        futuro = self.instante + timedelta(days=400)
        with patch('apps.clientes.consultas.timezone.now', return_value=futuro):
            self.assertEqual(resumo_cliente(self.cliente)['ranking'], {'acumulado': 2, 'disponivel': None})

    def test_paginacao_e_ordem_compras_e_resgates(self):
        for numero in range(11):
            self.lote('100.00')
            self.resgatar(identificador_externo=f'R-{numero}')
        for rota in ('pontos', 'resgates'):
            primeira = self.client.get(reverse(f'clientes:{rota}'))
            segunda = self.client.get(reverse(f'clientes:{rota}'), {'page': 2})
            self.assertEqual(len(primeira.context['historico']), 10)
            self.assertEqual(len(segunda.context['historico']), 1)
            self.assertGreater(primeira.context['historico'][0].pk, segunda.context['historico'][0].pk)
            self.assertContains(primeira, '?page=2')
            self.assertContains(segunda, 'Página 2 de 2')

    def test_isolamento_e_troca_valida(self):
        self.lote('300.00')
        self.resgatar()
        externo = Cliente.objects.create(usuario=self.usuario, empresa=self.outra)
        credencial, _ = self.emitir(membro=self.outro_membro)
        self.lote('900.00', credencial=credencial, loja_id=self.externa.pk)
        self.nivel()
        self.assertEqual(self.home().context['ranking']['acumulado'], 1)
        resposta = self.client.post(reverse('clientes:trocar_programa'), {'cliente_id': externo.pk})
        self.assertRedirects(resposta, reverse('clientes:area'))
        self.assertEqual(self.client.session[CONTEXTO_SESSAO], {
            'tipo_contexto': 'cliente', 'empresa_id': self.outra.pk, 'vinculo_id': externo.pk,
        })
        resposta = self.home()
        self.assertEqual(resposta.context['saldo'], Decimal('900'))
        self.assertIsNone(resposta.context['nivel'])
        self.assertEqual(resposta.context['ranking']['acumulado'], 1)
        self.assertEqual(resposta.context['expiracao']['pontos'], Decimal('900'))
        pontos = self.client.get(reverse('clientes:pontos'))
        self.assertContains(pontos, 'Outra')
        self.assertNotContains(pontos, 'Centro')
        self.assertEqual(self.client.get(reverse('clientes:resgates')).context['historico'].paginator.count, 0)

    def test_trocas_invalidas_preservam_contexto(self):
        antes = self.client.session[CONTEXTO_SESSAO]
        for dados in ({'cliente_id': self.outro_cliente.pk}, {'cliente_id': 999999},
                      {'cliente_id': 'abc'}, {'cliente_id': self.membro.pk, 'tipo_contexto': 'gestao'}):
            self.assertEqual(self.client.post(reverse('clientes:trocar_programa'), dados).status_code, 403)
            self.assertEqual(self.client.session[CONTEXTO_SESSAO], antes)
        self.assertEqual(self.client.get(reverse('clientes:trocar_programa')).status_code, 405)

    def test_gestao_nao_pode_usar_novo_fluxo(self):
        self.ativar(self.membro, 'gestao')
        self.assertEqual(self.client.post(reverse('clientes:trocar_programa'), {'cliente_id': self.cliente.pk}).status_code, 403)
        for rota in ('area', 'pontos', 'resgates'):
            self.assertEqual(self.client.get(reverse(f'clientes:{rota}')).status_code, 403)

    def test_csrf_e_autenticacao(self):
        navegador = Client(enforce_csrf_checks=True)
        navegador.force_login(self.usuario)
        self.assertEqual(navegador.post(reverse('clientes:trocar_programa'), {'cliente_id': self.cliente.pk}).status_code, 403)
        self.client.logout()
        for rota in ('area', 'pontos', 'resgates'):
            self.assertEqual(self.client.get(reverse(f'clientes:{rota}')).status_code, 302)

    def test_consultas_nao_crescem_por_item_no_historico_ou_populacao(self):
        self.lote('300.00')
        with CaptureQueriesContext(connection) as inicial:
            resumo_cliente(self.cliente)
        with CaptureQueriesContext(connection) as feed_inicial:
            self.client.get(reverse('clientes:pontos'))
        for _ in range(3):
            self.lote('100.00', cliente_cpf=self.outro_usuario.cpf)
            self.lote('100.00')
        with CaptureQueriesContext(connection) as ampliado:
            resumo_cliente(self.cliente)
        with CaptureQueriesContext(connection) as feed_ampliado:
            self.client.get(reverse('clientes:pontos'))
        self.assertEqual(len(inicial), len(ampliado))
        self.assertLessEqual(len(ampliado), 15)
        self.assertEqual(len(feed_inicial), len(feed_ampliado))
