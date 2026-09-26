from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.empresas.services import desativar_credencial
from apps.fidelidade.models import AlocacaoResgate, EstornoResgate, LotePontos, Resgate
from apps.fidelidade.test_resgates import DadosResgates

URL = '/api/v1/resgates/estornar/'


class EstornoHTTPTests(DadosResgates, TestCase):
    def setUp(self):
        super().setUp()
        self.lote('300.00')
        self.resgatar(pontos=200)

    def payload(self, **alteracoes):
        return dict(dict(loja_id=self.loja.pk, resgate_identificador_externo='RESGATE-001',
                         identificador_externo='ESTORNO-001'), **alteracoes)

    def enviar(self, chave=None, **alteracoes):
        with patch('apps.fidelidade.estornos.timezone.now', return_value=self.instante):
            return APIClient(enforce_csrf_checks=True).post(URL, self.payload(**alteracoes), format='json',
                HTTP_X_API_KEY=self.chave if chave is None else chave)

    def assert_erro(self, resposta, status, codigo):
        self.assertEqual(resposta.status_code, status, resposta.content)
        self.assertEqual(resposta.json()['erro']['codigo'], codigo)
        self.assertIn('no-store', resposta['Cache-Control'])

    def test_201_200_integral_contrato_snapshot_historico_intacto(self):
        antes = [list(m.objects.values()) for m in (Resgate, AlocacaoResgate, LotePontos)]
        primeira = self.enviar()
        self.assertEqual(primeira.status_code, 201, primeira.content)
        dados = primeira.json()
        self.assertEqual(set(dados), {'identificador_externo', 'resgate_identificador_externo', 'loja',
            'cliente', 'pontos_estornados', 'valor_desconto_original', 'devolve_pontos_aplicado', 'estornado_em'})
        self.assertEqual(dados['loja'], {'id': self.loja.pk, 'nome': 'Centro'})
        self.assertEqual(dados['cliente'], {'cpf': self.usuario.cpf})
        self.assertIs(type(dados['pontos_estornados']), int)
        self.assertEqual(dados['pontos_estornados'], 200)
        self.assertEqual(dados['valor_desconto_original'], '10.00')
        self.assertIs(dados['devolve_pontos_aplicado'], True)
        self.assertIn('no-store', primeira['Cache-Control'])
        self.configurar(devolver_pontos_ao_estornar_resgate=False)
        self.instante += timedelta(days=800)
        _, chave = self.emitir('LOJAS', [self.loja])
        with patch('apps.fidelidade.estornos.resolver_configuracao', side_effect=AssertionError('Retry')):
            retry = self.enviar(chave=chave, identificador_externo=' ESTORNO-001 ',
                                resgate_identificador_externo=' RESGATE-001 ')
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json(), dados)
        self.assertEqual(EstornoResgate.objects.count(), 1)
        self.assertEqual(EstornoResgate.objects.get().credencial_origem_id, self.credencial.pk)
        self.assertEqual(antes, [list(m.objects.values()) for m in (Resgate, AlocacaoResgate, LotePontos)])

    def test_snapshot_false_e_retry_nao_muda_para_true(self):
        self.configurar(devolver_pontos_ao_estornar_resgate=False)
        primeira = self.enviar()
        self.assertEqual(primeira.status_code, 201)
        self.assertIs(primeira.json()['devolve_pontos_aplicado'], False)
        self.configurar(devolver_pontos_ao_estornar_resgate=True)
        self.assertEqual(self.enviar().json(), primeira.json())

    def test_conflitos(self):
        self.resgatar(identificador_externo='OUTRO')
        self.enviar()
        self.assert_erro(self.enviar(resgate_identificador_externo='OUTRO'), 409, 'idempotencia_conflitante')
        self.assert_erro(self.enviar(identificador_externo='OUTRA'), 409, 'resgate_ja_estornado')
        self.assertEqual(EstornoResgate.objects.count(), 1)

    def test_404_403_tenant_e_escopo(self):
        inexistente = self.enviar(resgate_identificador_externo='AUSENTE')
        outra_loja = self.enviar(loja_id=self.segunda.pk)
        self.assert_erro(inexistente, 404, 'resgate_nao_encontrado')
        self.assertEqual(inexistente.json(), outra_loja.json())
        # O isolamento é definido pela Loja autorizada: uma chave existente fora dela é indistinguível.
        _, chave = self.emitir('LOJAS', [self.segunda])
        self.assert_erro(self.enviar(chave=chave), 403, 'loja_fora_do_escopo')
        for loja_id in (self.externa.pk, 999999):
            self.assert_erro(self.enviar(loja_id=loja_id), 403, 'loja_fora_do_escopo')
        self.assertFalse(EstornoResgate.objects.exists())

    def test_autenticacao(self):
        self.assert_erro(APIClient().post(URL, self.payload(), format='json'), 401, 'credencial_invalida')
        self.assert_erro(self.enviar(chave='invalida'), 401, 'credencial_invalida')
        desativar_credencial(self.request(), self.credencial.pk)
        self.assert_erro(self.enviar(), 401, 'credencial_invalida')
        self.assertFalse(EstornoResgate.objects.exists())

    def test_resgate_existente_em_outro_tenant_nao_vaza(self):
        credencial, _ = self.emitir(membro=self.outro_membro)
        self.lote(credencial=credencial, loja_id=self.externa.pk, cliente_cpf=self.sem_vinculo.cpf)
        self.resgatar(credencial=credencial, loja_id=self.externa.pk, cliente_cpf=self.sem_vinculo.cpf,
                      identificador_externo='EXCLUSIVO-EXTERNO')
        externa = self.enviar(resgate_identificador_externo='EXCLUSIVO-EXTERNO')
        inexistente = self.enviar(resgate_identificador_externo='INEXISTENTE')
        self.assert_erro(externa, 404, 'resgate_nao_encontrado')
        self.assertEqual(externa.json(), inexistente.json())
        self.assertFalse(EstornoResgate.objects.exists())

    def test_payload_estrito_sem_backdating(self):
        for campo in ('cliente_cpf', 'pontos', 'valor_desconto', 'saldo', 'estornado_em', 'resgatado_em',
                      'ocorrida_em', 'devolve_pontos_aplicado', 'credencial_origem', 'snapshot'):
            self.assert_erro(self.enviar(**{campo: 'indevido'}), 400, 'requisicao_invalida')
        for campo in self.payload():
            dados = self.payload()
            dados.pop(campo)
            self.assert_erro(APIClient().post(URL, dados, format='json', HTTP_X_API_KEY=self.chave),
                             400, 'requisicao_invalida')
        for campo in ('identificador_externo', 'resgate_identificador_externo'):
            for valor in ('', ' \t', 'a' * 256, None, 123, True, [], {}):
                self.assert_erro(self.enviar(**{campo: valor}), 400, 'requisicao_invalida')
        self.assertFalse(EstornoResgate.objects.exists())

    def test_identificadores_preservam_case_e_conteudo_interno(self):
        self.resgatar(identificador_externo='Resgate  Ab')
        resposta = self.enviar(resgate_identificador_externo=' Resgate  Ab ', identificador_externo=' Estorno  Ab ')
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(resposta.json()['identificador_externo'], 'Estorno  Ab')
        self.assertEqual(resposta.json()['resgate_identificador_externo'], 'Resgate  Ab')
        self.assert_erro(self.enviar(resgate_identificador_externo='resgate  Ab', identificador_externo='outro'),
                         404, 'resgate_nao_encontrado')

    def test_metodos(self):
        for metodo in ('get', 'put', 'patch', 'delete', 'head'):
            resposta = getattr(APIClient(), metodo)(URL, HTTP_X_API_KEY=self.chave)
            self.assertEqual(resposta.status_code, 405)
            if metodo != 'head':
                self.assert_erro(resposta, 405, 'metodo_nao_permitido')
        self.assertEqual(APIClient().options(URL, HTTP_X_API_KEY=self.chave).status_code, 200)


class EstornoOpenAPITests(SimpleTestCase):
    def test_contrato(self):
        schema = self.client.get('/api/schema/', HTTP_ACCEPT='application/vnd.oai.openapi+json').json()
        rota = schema['paths'][URL]
        self.assertEqual(set(rota), {'post'})
        post = rota['post']
        self.assertEqual(post['security'], [{'X-API-Key': []}])
        self.assertEqual(set(post['responses']), {'201', '200', '400', '401', '403', '404', '409', '405'})
        def componente(conteudo):
            return schema['components']['schemas'][conteudo['content']['application/json']['schema']['$ref'].split('/')[-1]]
        entrada = componente(post['requestBody'])
        self.assertEqual(set(entrada['properties']), {'loja_id', 'resgate_identificador_externo', 'identificador_externo'})
        self.assertEqual(set(entrada['required']), set(entrada['properties']))
        self.assertFalse(entrada['additionalProperties'])
        for campo in ('resgate_identificador_externo', 'identificador_externo'):
            self.assertEqual(entrada['properties'][campo]['maxLength'], 255)
        for status in ('201', '200'):
            saida = componente(post['responses'][status])['properties']
            self.assertEqual(set(saida), {'identificador_externo', 'resgate_identificador_externo', 'loja', 'cliente',
                'pontos_estornados', 'valor_desconto_original', 'devolve_pontos_aplicado', 'estornado_em'})
            self.assertEqual(saida['pontos_estornados']['type'], 'integer')
            self.assertEqual(saida['valor_desconto_original']['type'], 'string')
        self.assertIn('resgate_nao_encontrado', post['responses']['404']['description'])
        for codigo in ('idempotencia_conflitante', 'resgate_ja_estornado'):
            self.assertIn(codigo, post['responses']['409']['description'])
