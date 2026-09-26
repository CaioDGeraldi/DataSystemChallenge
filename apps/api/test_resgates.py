import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.empresas.services import desativar_credencial
from apps.fidelidade.calculos_resgate import MAX_PONTOS_RESGATE
from apps.fidelidade.models import AlocacaoResgate, Resgate
from apps.fidelidade.test_resgates import DadosResgates


class ResgateHTTPTests(DadosResgates, TestCase):
    def setUp(self):
        super().setUp()
        self.lote('1000.00')

    def payload(self, **alteracoes):
        return dict(dict(loja_id=self.loja.pk, identificador_externo='RESGATE-001',
                         cliente_cpf=self.usuario.cpf, pontos=200), **alteracoes)

    def enviar(self, chave=None, **alteracoes):
        with patch('apps.fidelidade.resgates.timezone.now', return_value=self.instante):
            return APIClient(enforce_csrf_checks=True).post('/api/v1/resgates/', self.payload(**alteracoes),
                format='json', HTTP_X_API_KEY=self.chave if chave is None else chave)

    def assert_erro(self, resposta, status, codigo):
        self.assertEqual(resposta.status_code, status)
        self.assertEqual(set(resposta.json()), {'erro'})
        self.assertEqual(resposta.json()['erro']['codigo'], codigo)

    def test_201_200_contrato_inteiro_monetario_string_sem_alocacoes(self):
        primeira = self.enviar()
        self.assertEqual(primeira.status_code, 201)
        dados = primeira.json()
        self.assertEqual(set(dados), {'id', 'identificador_externo', 'loja', 'cliente',
                                     'pontos_resgatados', 'valor_desconto', 'resgatado_em'})
        self.assertEqual(dados['loja'], {'id': self.loja.pk, 'nome': 'Centro'})
        self.assertEqual(dados['cliente'], {'cpf': self.usuario.cpf})
        self.assertIs(type(dados['pontos_resgatados']), int)
        self.assertEqual(dados['pontos_resgatados'], 200)
        self.assertEqual(dados['valor_desconto'], '10.00')
        self.assertIn('no-store', primeira['Cache-Control'])
        retry = self.enviar(identificador_externo=' RESGATE-001 ', cliente_cpf='529.982.247-25')
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json(), dados)
        self.assertEqual((Resgate.objects.count(), AlocacaoResgate.objects.count()), (1, 1))

    def test_pontos_json_estrito_rejeita_float_string_bool_limites(self):
        for pontos in (100.0, 100.5, '100', '100.00', True, None, 0, -1, MAX_PONTOS_RESGATE + 1, [], {}):
            with self.subTest(pontos=pontos):
                self.assert_erro(self.enviar(pontos=pontos), 400, 'requisicao_invalida')
        self.assertFalse(Resgate.objects.exists())

    def test_campos_extras_backdating_e_obrigatorios(self):
        for campo in ('ocorrida_em', 'resgatado_em', 'timestamp', 'valor_desconto', 'credencial_origem', 'alocacoes'):
            self.assert_erro(self.enviar(**{campo: self.instante.isoformat()}), 400, 'requisicao_invalida')
        for campo in self.payload():
            dados = self.payload()
            dados.pop(campo)
            resposta = APIClient().post('/api/v1/resgates/', dados, format='json', HTTP_X_API_KEY=self.chave)
            self.assert_erro(resposta, 400, 'requisicao_invalida')
        self.assertFalse(Resgate.objects.exists())

    def test_identificador_textual_e_cpf_invalido(self):
        for identificador in ('', ' \t', 'a' * 256, None, 123, 1.5, True):
            self.assert_erro(self.enviar(identificador_externo=identificador), 400, 'requisicao_invalida')
        for cpf in ('abc', '', '52998224726', '529/982/247-25'):
            self.assert_erro(self.enviar(cliente_cpf=cpf), 400, 'requisicao_invalida')
        for identificador in (' Venda  A-b ', 'venda  A-b', ' ' + 'A' * 255 + ' '):
            resposta = self.enviar(identificador_externo=identificador)
            self.assertEqual(resposta.status_code, 201)
            self.assertEqual(resposta.json()['identificador_externo'], identificador.strip())

    def test_401_sem_chave_invalida_desativada(self):
        sem_chave = APIClient().post('/api/v1/resgates/', self.payload(), format='json')
        self.assert_erro(sem_chave, 401, 'credencial_invalida')
        self.assertEqual(sem_chave['WWW-Authenticate'], 'X-API-Key')
        self.assertEqual(self.enviar(chave='invalida').json(), sem_chave.json())
        desativar_credencial(self.request(), self.credencial.pk)
        self.assertEqual(self.enviar().json(), sem_chave.json())
        self.assertFalse(Resgate.objects.exists())

    def test_403_loja_fora_escopo_404_cliente_cross_tenant_sem_vazamento(self):
        _, chave = self.emitir('LOJAS', [self.loja])
        for loja_id in (self.segunda.pk, self.externa.pk, 999999):
            self.assert_erro(self.enviar(chave=chave, loja_id=loja_id), 403, 'loja_fora_do_escopo')
        inexistente = self.enviar(cliente_cpf='39053344705')
        externo = self.enviar(cliente_cpf=self.sem_vinculo.cpf)
        self.assert_erro(externo, 404, 'cliente_nao_encontrado')
        self.assertEqual(externo.json(), inexistente.json())
        self.assertFalse(Resgate.objects.exists())

    def test_erros_minimo_incremento_saldo_e_financeiro(self):
        for pontos, codigo in ((99, 'pontos_abaixo_do_minimo'), (101, 'incremento_resgate_invalido'),
                               (1050, 'saldo_insuficiente')):
            self.assert_erro(self.enviar(pontos=pontos), 400, codigo)
        with patch('apps.fidelidade.resgates.calcular_desconto', side_effect=ValidationError('Capacidade excedida')):
            self.assert_erro(self.enviar(), 400, 'requisicao_invalida')
        self.assertFalse(Resgate.objects.exists())
        self.assertFalse(AlocacaoResgate.objects.exists())

    def test_409_divergencias_preservam_historico(self):
        self.assertEqual(self.enviar().status_code, 201)
        antes = Resgate.objects.values().get()
        alocacoes = list(AlocacaoResgate.objects.values())
        for alteracoes in ({'pontos': 150}, {'cliente_cpf': self.outro_usuario.cpf}):
            self.assert_erro(self.enviar(**alteracoes), 409, 'idempotencia_conflitante')
        self.assertEqual(Resgate.objects.values().get(), antes)
        self.assertEqual(list(AlocacaoResgate.objects.values()), alocacoes)

    def test_retry_outra_credencial_configuracao_e_expiracao_preserva_tudo(self):
        primeira = self.enviar()
        origem = Resgate.objects.get().credencial_origem_id
        _, chave = self.emitir('LOJAS', [self.loja])
        desativar_credencial(self.request(), self.credencial.pk)
        self.configurar(valor_monetario_por_ponto=Decimal('1.00'), resgate_minimo_pontos=1000)
        self.instante += timedelta(days=800)
        with patch('apps.fidelidade.resgates.resolver_configuracao', side_effect=AssertionError('Retry')):
            retry = self.enviar(chave=chave)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json(), primeira.json())
        self.assertEqual(Resgate.objects.get().credencial_origem_id, origem)
        self.assertEqual(AlocacaoResgate.objects.count(), 1)

    def test_metodos_nao_implementados(self):
        for metodo in ('get', 'put', 'patch', 'delete'):
            resposta = getattr(APIClient(), metodo)('/api/v1/resgates/', HTTP_X_API_KEY=self.chave)
            self.assert_erro(resposta, 405, 'metodo_nao_permitido')


class ResgateOpenAPITests(SimpleTestCase):
    def test_contrato_real_sem_endpoints_futuros_ou_limite_int64(self):
        resposta = self.client.get('/api/schema/', HTTP_ACCEPT='application/vnd.oai.openapi+json')
        self.assertEqual(resposta.status_code, 200)
        schema = json.loads(resposta.content)
        self.assertEqual(set(schema['paths']), {'/api/v1/health/', '/api/v1/contexto/',
                                               '/api/v1/clientes/fidelidade/',
                                               '/api/v1/compras/simular/',
                                               '/api/v1/compras/', '/api/v1/resgates/'})
        rota = schema['paths']['/api/v1/resgates/']
        self.assertEqual(set(rota), {'post'})
        post = rota['post']
        self.assertEqual(post['security'], [{'X-API-Key': []}])
        self.assertEqual(set(post['responses']), {'200', '201', '400', '401', '403', '404', '405', '409'})

        def componente(conteudo):
            ref = conteudo['content']['application/json']['schema']['$ref'].split('/')[-1]
            return schema['components']['schemas'][ref]

        entrada = componente(post['requestBody'])
        self.assertEqual(set(entrada['required']), {'loja_id', 'identificador_externo', 'cliente_cpf', 'pontos'})
        self.assertEqual(set(entrada['properties']), set(entrada['required']))
        self.assertFalse(entrada['additionalProperties'])
        self.assertEqual(entrada['properties']['identificador_externo']['maxLength'], 255)
        for campo in [entrada['properties']['pontos']] + [
                componente(post['responses'][status])['properties']['pontos_resgatados'] for status in ('200', '201')]:
            self.assertEqual(campo['type'], 'integer')
            self.assertEqual(campo['minimum'], 1)
            self.assertEqual(campo['maximum'], MAX_PONTOS_RESGATE)
            self.assertNotIn('format', campo)  # O teto de 20 dígitos excede int64.
        for status in ('200', '201'):
            saida = componente(post['responses'][status])['properties']
            self.assertEqual(set(saida), {'id', 'identificador_externo', 'loja', 'cliente',
                                         'pontos_resgatados', 'valor_desconto', 'resgatado_em'})
            self.assertEqual(saida['valor_desconto']['type'], 'string')
            self.assertEqual(saida['resgatado_em']['format'], 'date-time')
