from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.fidelidade.models import Compra, Resgate
from apps.fidelidade.test_resgates import DadosResgates


class CompraResgateHTTPTests(DadosResgates, TestCase):
    def post(self, rota, dados):
        return APIClient().post('/api/v1/' + rota + '/', dados, format='json', HTTP_X_API_KEY=self.chave)

    def compra(self, **dados):
        return self.post('compras', dict({
            'loja_id': self.loja.pk, 'cliente_cpf': self.usuario.cpf,
            'identificador_externo': 'C1', 'valor': '100.00',
            'ocorrida_em': self.instante.isoformat(), 'resgate_identificador_externo': 'RESGATE-001',
        }, **dados))

    def test_resposta_explicavel_desconto_historico_retry_e_erros(self):
        self.lote('1000')
        self.resgatar()
        resposta = self.compra()
        self.assertEqual(resposta.status_code, 201)
        dados = resposta.json()
        self.assertEqual(dados['resgate'], {'identificador_externo': 'RESGATE-001', 'pontos_resgatados': 100, 'valor_desconto': '5.00'})
        self.assertEqual(dados['resumo']['valores'], {'bruto': '100.00', 'desconto_total': '5.00', 'final': '95.00', 'elegivel_pontos': '95.00'})
        self.assertEqual(dados['resumo']['pontos']['total'], '95.0000')
        self.assertNotIn('snapshot', str(dados))
        self.assertNotIn('alocacoes', str(dados))
        self.configurar(limite_resgate_percentual=Decimal('0'))
        self.assertEqual(self.compra().json(), dados)
        for resposta, codigo in (
            (self.compra(identificador_externo='C2'), 'resgate_vinculado_compra'),
            (self.compra(resgate_identificador_externo='OUTRO'), 'idempotencia_conflitante'),
            (self.post('resgates/estornar', {'loja_id': self.loja.pk, 'identificador_externo': 'E1', 'resgate_identificador_externo': 'RESGATE-001'}), 'resgate_vinculado_compra'),
        ):
            self.assertEqual(resposta.status_code, 409)
            self.assertEqual(resposta.json()['erro']['codigo'], codigo)

    def test_consulta_e_simulacao_maximos_sem_persistencia(self):
        self.lote('1099.99')
        self.configurar(limite_resgate_percentual=Decimal('50'))
        with patch('apps.fidelidade.consultas.timezone.now', return_value=self.instante):
            consulta = APIClient().get('/api/v1/clientes/fidelidade/', {'loja_id': self.loja.pk, 'cliente_cpf': self.usuario.cpf}, HTTP_X_API_KEY=self.chave).json()
            sim = self.post('compras/simular', {'loja_id': self.loja.pk, 'cliente_cpf': self.usuario.cpf, 'valor': '101.99'}).json()
        self.assertEqual(consulta['saldo']['pontos'], '1099.9900')
        self.assertEqual(consulta['resgate']['maximo_pontos'], 1050)
        self.assertEqual(consulta['resgate']['maximo_desconto'], '52.50')
        self.assertTrue(consulta['resgate']['possivel'])
        self.assertEqual(sim['saldo'], consulta['saldo'])
        self.assertEqual(sim['resgate'], {'possivel': True, 'maximo_pontos': 1000, 'maximo_desconto': '50.00', 'limite_resgate_percentual': '50.0000'})
        self.assertEqual(Compra.objects.count(), 1)
        self.assertFalse(Resgate.objects.exists())

    def test_compra_rejeita_todos_os_campos_extras(self):
        self.lote('2000')
        self.resgatar()
        for campo in ('valor_desconto', 'pontos_concedidos', 'saldo', 'nivel',
                      'desconto_percentual', 'percentual de desconto', 'campo_desconhecido'):
            with self.subTest(campo=campo):
                resposta = self.compra(**{campo: '999.99'})
                self.assertEqual(resposta.status_code, 400)
                self.assertEqual(resposta.json()['erro']['codigo'], 'requisicao_invalida')
                self.assertFalse(Compra.objects.filter(identificador_externo='C1').exists())

    def test_maximo_efetivo_simulado_e_rejeicao_do_historico_excessivo(self):
        from django.db import transaction
        from apps.fidelidade.niveis import criar_nivel

        self.lote('2000')
        self.configurar(limite_resgate_percentual=Decimal('50'))
        criar_nivel(self.request(), nome='Inicial', pontos_minimos=Decimal('0'),
                    desconto_percentual=Decimal('70'))
        for ordem, pontos, desconto in (
            ('ANTES_DOS_DESCONTOS_PERCENTUAIS', 1000, '50.00'),
            ('DEPOIS_DOS_DESCONTOS_PERCENTUAIS', 600, '30.00'),
        ):
            with self.subTest(ordem=ordem), transaction.atomic():
                self.configurar(ordem_aplicacao_resgate=ordem)
                with patch('apps.fidelidade.simulacoes.timezone.now', return_value=self.instante):
                    resposta = self.post('compras/simular', {
                        'loja_id': self.loja.pk, 'cliente_cpf': self.usuario.cpf, 'valor': '100.00',
                    })
                self.assertEqual(resposta.status_code, 200)
                self.assertEqual(resposta.json()['resgate']['maximo_pontos'], pontos)
                self.assertEqual(resposta.json()['resgate']['maximo_desconto'], desconto)
                self.assertFalse(Resgate.objects.exists())
                self.resgatar(pontos=1000)
                resposta = self.compra()
                if pontos == 1000:
                    self.assertEqual(resposta.status_code, 201)
                else:
                    self.assertEqual(resposta.status_code, 400)
                    self.assertEqual(resposta.json()['erro']['codigo'], 'limite_resgate_excedido')
                    self.assertEqual(resposta.json()['erro']['mensagem'],
                                     'Desconto do Resgate excede o máximo aplicável à Compra.')
                    self.assertFalse(Compra.objects.filter(identificador_externo='C1').exists())
                    self.resgatar(pontos=600, identificador_externo='R600')
                    resposta = self.compra(resgate_identificador_externo='R600')
                    self.assertEqual(resposta.status_code, 201)
                    self.assertEqual(resposta.json()['resumo']['valores']['final'], '0.00')
                transaction.set_rollback(True)

    def test_identificador_invalido_e_teto(self):
        self.lote()
        self.resgatar()
        for alvo in (123, '', None):
            self.assertEqual(self.compra(resgate_identificador_externo=alvo).status_code, 400)
        self.configurar(limite_resgate_percentual=Decimal('1'))
        resposta = self.compra()
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(resposta.json()['erro']['codigo'], 'limite_resgate_excedido')

    def test_openapi_descreve_campos_aditivos_e_conflitos(self):
        schema = APIClient().get('/api/schema/', HTTP_ACCEPT='application/vnd.oai.openapi+json').json()
        componentes = schema['components']['schemas']
        compra = componentes['RegistrarCompra']
        self.assertIn('resgate_identificador_externo', compra['properties'])
        self.assertNotIn('resgate_identificador_externo', compra['required'])
        self.assertEqual(set(componentes['DisponibilidadeResgate']['properties']), {'possivel', 'maximo_pontos', 'maximo_desconto', 'limite_resgate_percentual'})
        self.assertIn('resumo', componentes['Compra']['properties'])
        self.assertIn('resgate', componentes['Compra']['properties'])
        for rota in ('/api/v1/compras/', '/api/v1/resgates/estornar/'):
            self.assertIn('resgate_vinculado_compra', schema['paths'][rota]['post']['responses']['409']['description'])
