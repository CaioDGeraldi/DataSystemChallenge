import json
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.empresas.models import ConfiguracaoFidelidadeEmpresa
from apps.empresas.services import desativar_credencial
from apps.fidelidade.models import Compra, LotePontos
from apps.fidelidade.test_compras import DadosCompras


class FidelidadeHTTPTests(DadosCompras, TestCase):
    def enviar(self, chave=None, **alteracoes):
        return APIClient().post('/api/v1/compras/', dict({
            'loja_id': self.loja.pk, 'cliente_cpf': self.usuario.cpf,
            'identificador_externo': 'VENDA-000123', 'valor': '49.90',
            'ocorrida_em': self.instante.isoformat(),
        }, **alteracoes), format='json', HTTP_X_API_KEY=chave or self.chave)

    def test_201_e_200_resultado_real_historico_apos_mudanca_e_outra_credencial(self):
        config = ConfiguracaoFidelidadeEmpresa.objects.create(empresa=self.empresa, pontos_por_real=Decimal('1.25'))
        resposta = self.enviar(pontos_concedidos='9999.0000')
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(resposta.json()['fidelidade'], {
            'pontos_base': '62.3750', 'pontos_concedidos': '62.3800',
            'expira_em': '2027-09-23T10:30:00-03:00',
        })
        self.assertEqual(set(resposta.json()['fidelidade']), {'pontos_base', 'pontos_concedidos', 'expira_em'})
        antes = LotePontos.objects.values().get()
        config.pontos_por_real = Decimal('2.00')
        config.validade_pontos_meses = 2147483647
        config.save()
        _, outra_chave = self.emitir()
        desativar_credencial(self.request(), self.credencial.pk)
        with patch('apps.fidelidade.services.resolver_configuracao', side_effect=AssertionError('Retry não resolve')):
            retry = self.enviar(chave=outra_chave)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json(), resposta.json())
        self.assertEqual(LotePontos.objects.values().get(), antes)
        conflito = self.enviar(chave=outra_chave, valor='50.00')
        self.assertEqual(conflito.status_code, 409)
        self.assertEqual(conflito.json()['erro']['codigo'], 'idempotencia_conflitante')
        self.assertEqual(LotePontos.objects.values().get(), antes)
        self.assertEqual(Compra.objects.count(), 1)

    def test_expiracao_irrepresentavel_400_rollback_preserva_registros_anteriores(self):
        self.assertEqual(self.enviar().status_code, 201)
        compras, lotes = list(Compra.objects.values()), list(LotePontos.objects.values())
        resposta = self.enviar(identificador_externo='FORA-DO-INTERVALO', ocorrida_em='9999-09-23T10:30:00-03:00')
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(resposta.json()['erro']['codigo'], 'requisicao_invalida')
        self.assertEqual(resposta.json()['erro']['mensagem'], 'Dados inválidos.')
        for detalhe in ('OverflowError', 'ValueError', 'Traceback', 'year out of range'):
            self.assertNotIn(detalhe, resposta.content.decode())
        self.assertEqual(list(Compra.objects.values()), compras)
        self.assertEqual(list(LotePontos.objects.values()), lotes)

    def test_validade_grande_permitida_configuracao_mas_combinacao_rejeitada_400(self):
        config = ConfiguracaoFidelidadeEmpresa.objects.create(empresa=self.empresa, validade_pontos_meses=2147483647)
        config.full_clean()
        resposta = self.enviar()
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(resposta.json()['erro']['codigo'], 'requisicao_invalida')
        self.assertFalse(Compra.objects.exists())
        self.assertFalse(LotePontos.objects.exists())

    def test_validationerror_do_lote_tambem_vira_400_com_rollback(self):
        with patch('apps.fidelidade.services.LotePontos.save', side_effect=ValidationError('Dados inválidos.')):
            resposta = self.enviar()
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(resposta.json()['erro']['codigo'], 'requisicao_invalida')
        self.assertFalse(Compra.objects.exists())
        self.assertFalse(LotePontos.objects.exists())

    def test_legado_null_campo_presente_sem_calcular_pontos_ou_validade(self):
        compra = self.model(valor=Decimal('49.90'), ocorrida_em=self.instante.replace(year=9999))
        compra.save()  # Fixture de Compra F3.01, sem concessão.
        antes = Compra.objects.values().get()
        ConfiguracaoFidelidadeEmpresa.objects.create(empresa=self.empresa, validade_pontos_meses=2147483647)
        with patch('apps.fidelidade.services._criar_lote_da_nova_compra', side_effect=AssertionError('Sem backfill')):
            resposta = self.enviar(ocorrida_em=compra.ocorrida_em.isoformat())
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('fidelidade', resposta.json())
        self.assertIsNone(resposta.json()['fidelidade'])
        self.assertEqual(Compra.objects.values().get(), antes)
        self.assertFalse(LotePontos.objects.exists())


class FidelidadeOpenAPITests(SimpleTestCase):
    def test_fidelidade_nullable_decimais_e_security_sem_features_futuras(self):
        resposta = self.client.get('/api/schema/', HTTP_ACCEPT='application/vnd.oai.openapi+json')
        self.assertEqual(resposta.status_code, 200)
        schema = json.loads(resposta.content)
        self.assertEqual(set(schema['paths']), {'/api/v1/health/', '/api/v1/contexto/', '/api/v1/clientes/fidelidade/', '/api/v1/compras/simular/', '/api/v1/compras/', '/api/v1/resgates/estornar/', '/api/v1/resgates/simular/', '/api/v1/resgates/'})
        post = schema['paths']['/api/v1/compras/']['post']
        self.assertEqual(post['security'], [{'X-API-Key': []}])
        for status in ('200', '201', '400', '409'):
            self.assertIn(status, post['responses'])
        tipos = schema['components']['schemas']
        for status in ('200', '201'):
            ref = post['responses'][status]['content']['application/json']['schema']['$ref'].split('/')[-1]
            fidelidade = tipos[ref]['properties']['fidelidade']
            self.assertTrue(fidelidade['nullable'])
            self.assertIn('quatro casas', fidelidade['description'])
        pontos = tipos['FidelidadeCompra']['properties']
        self.assertEqual(set(pontos), {'pontos_base', 'pontos_concedidos', 'expira_em'})
        for campo in ('pontos_base', 'pontos_concedidos'):
            self.assertEqual(pontos[campo]['type'], 'string')
            self.assertEqual(pontos[campo]['format'], 'decimal')
            self.assertIn('quatro casas decimais', pontos[campo]['description'])
        self.assertEqual(pontos['expira_em']['format'], 'date-time')
        for nome in ('LotePontos', 'Evento', 'Campanha', 'AlocacaoResgate', 'Nivel'):
            self.assertNotIn(nome, tipos)
