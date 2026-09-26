import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.empresas.models import OverrideFidelidadeLoja
from apps.empresas.services import desativar_credencial
from apps.fidelidade.calculos_resgate import MAX_PONTOS_RESGATE
from apps.fidelidade.consultas import consultar_fidelidade_cliente
from apps.fidelidade.models import AlocacaoResgate, LotePontos, Resgate
from apps.fidelidade.resgates import simular_resgate
from apps.fidelidade.test_resgates import DadosResgates


URL = '/api/v1/resgates/simular/'


class SimulacaoResgateHTTPTests(DadosResgates, TestCase):
    def setUp(self):
        super().setUp()
        self.lote('250.00')

    def payload(self, **alteracoes):
        return dict(dict(loja_id=self.loja.pk, cliente_cpf=self.usuario.cpf, pontos=100), **alteracoes)

    def enviar(self, chave=None, **alteracoes):
        with patch('apps.fidelidade.resgates.timezone.now', return_value=self.instante):
            return APIClient(enforce_csrf_checks=True).post(
                URL, self.payload(**alteracoes), format='json',
                HTTP_X_API_KEY=self.chave if chave is None else chave,
            )

    def assert_erro(self, resposta, status, codigo):
        self.assertEqual(resposta.status_code, status)
        self.assertEqual(resposta.json()['erro']['codigo'], codigo)

    def estado(self):
        return [list(model.objects.order_by('pk').values()) for model in (Resgate, AlocacaoResgate, LotePontos)]

    def test_sucesso_contrato_cache_instante_unico_sem_locks_ou_escritas(self):
        antes = self.estado()
        with patch('apps.fidelidade.resgates.timezone.now', return_value=self.instante) as agora:
            with CaptureQueriesContext(connection) as consultas:
                simular_resgate(credencial=self.credencial, **self.payload())
            agora.assert_called_once_with()
        resposta = self.enviar()
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual(dados, {
            'cliente': {'cpf': self.usuario.cpf, 'nome': 'Ana Silva'},
            'simulada_em': self.instante.isoformat(),
            'pontos_resgatados': 100, 'valor_desconto': '5.00',
            'saldo': {'atual': '250.0000', 'projetado': '150.0000'},
        })
        self.assertIs(type(dados['pontos_resgatados']), int)
        self.assertIn('no-store', resposta['Cache-Control'])
        for consulta in consultas:
            sql = consulta['sql'].upper()
            for proibido in ('FOR UPDATE', 'FOR NO KEY UPDATE', 'PG_ADVISORY', 'INSERT ', 'UPDATE ', 'DELETE '):
                self.assertNotIn(proibido, sql)
        self.assertEqual(self.estado(), antes)
        self.assertEqual(self.enviar().json(), dados)
        self.assertEqual(self.estado(), antes)

    def test_expiracao_estrita_aquisicao_futura_e_consumos_anteriores(self):
        self.lote('900.00', ocorrida_em=self.instante - timedelta(days=366))
        limite = self.lote('800.00', ocorrida_em=self.instante - timedelta(days=365))
        self.assertEqual(limite.expira_em, self.instante)
        valido = self.lote('50.25', ocorrida_em=self.instante - timedelta(days=365) + timedelta(microseconds=1))
        self.assertGreater(valido.expira_em, self.instante)
        self.lote('99.75', ocorrida_em=self.instante + timedelta(days=1))
        self.resgatar()
        antes = self.estado()
        self.assertEqual(self.enviar().json()['saldo'], {'atual': '300.0000', 'projetado': '200.0000'})
        self.assertEqual(self.estado(), antes)

    def test_equivalencia_com_resgate_real_e_consulta_publica(self):
        simulado = self.enviar().json()
        real, _ = self.resgatar()
        self.assertEqual(str(real.valor_desconto), simulado['valor_desconto'])
        self.assertEqual(real.pontos_resgatados, simulado['pontos_resgatados'])
        with patch('apps.fidelidade.consultas.timezone.now', return_value=self.instante):
            consulta = consultar_fidelidade_cliente(
                credencial=self.credencial, loja_id=self.loja.pk, cliente_cpf=self.usuario.cpf,
            )
        self.assertEqual(consulta['saldo']['pontos'], simulado['saldo']['projetado'])

    def test_configuracao_loja_e_incremento_a_partir_do_minimo(self):
        OverrideFidelidadeLoja.objects.create(loja=self.loja, pontos_por_real=Decimal('2.00'))
        self.configurar(
            resgate_minimo_pontos=75, incremento_resgate_pontos=50,
            valor_monetario_por_ponto=Decimal('0.07'),
        )
        self.assertEqual(self.enviar(pontos=125).json()['valor_desconto'], '8.75')
        self.assert_erro(self.enviar(pontos=100), 400, 'incremento_resgate_invalido')

    def test_erros_materiais(self):
        for pontos, codigo in ((99, 'pontos_abaixo_do_minimo'), (101, 'incremento_resgate_invalido'),
                               (300, 'saldo_insuficiente')):
            with self.subTest(pontos=pontos):
                self.assert_erro(self.enviar(pontos=pontos), 400, codigo)

    def test_pontos_json_estrito(self):
        for pontos in (100.0, 100.5, '100', True, False, None, 0, -1, MAX_PONTOS_RESGATE + 1, [], {}):
            with self.subTest(pontos=pontos):
                self.assert_erro(self.enviar(pontos=pontos), 400, 'requisicao_invalida')
        self.assert_erro(self.enviar(pontos=MAX_PONTOS_RESGATE), 400, 'incremento_resgate_invalido')

    def test_campos_extras_obrigatorios_loja_e_cpf(self):
        for campo in ('identificador_externo', 'resgatado_em', 'ocorrida_em', 'valor_desconto',
                      'valor_monetario_por_ponto', 'saldo', 'qualquer_extra'):
            self.assert_erro(self.enviar(**{campo: 'extra'}), 400, 'requisicao_invalida')
        for campo in self.payload():
            dados = self.payload()
            dados.pop(campo)
            self.assert_erro(APIClient().post(URL, dados, format='json', HTTP_X_API_KEY=self.chave),
                             400, 'requisicao_invalida')
        for loja in (0, -1, True, 1.5):
            self.assert_erro(self.enviar(loja_id=loja), 400, 'requisicao_invalida')
        for loja in (float(self.loja.pk), str(self.loja.pk)):
            self.assertEqual(self.enviar(loja_id=loja).status_code, 200)
        for cpf in ('abc', '', '52998224726', '529/982/247-25'):
            self.assert_erro(self.enviar(cliente_cpf=cpf), 400, 'requisicao_invalida')
        self.assertEqual(self.enviar(cliente_cpf='529.982.247-25').status_code, 200)

    def test_escopos_empresa_lojas_sem_vazamento(self):
        self.assertEqual(self.enviar(loja_id=self.segunda.pk).status_code, 200)
        _, restrita = self.emitir('LOJAS', [self.loja])
        self.assertEqual(self.enviar(chave=restrita).status_code, 200)
        referencia = self.enviar(loja_id=999999)
        self.assert_erro(referencia, 403, 'loja_fora_do_escopo')
        for chave, lojas in ((self.chave, (self.externa.pk,)), (restrita, (self.segunda.pk, self.externa.pk, 999999))):
            for loja in lojas:
                resposta = self.enviar(chave=chave, loja_id=loja)
                self.assertEqual(resposta.status_code, 403)
                self.assertEqual(resposta.json(), referencia.json())
        inexistente = self.enviar(cliente_cpf='39053344705')
        externo = self.enviar(cliente_cpf=self.sem_vinculo.cpf)
        self.assert_erro(inexistente, 404, 'cliente_nao_encontrado')
        self.assert_erro(externo, 404, 'cliente_nao_encontrado')
        self.assertEqual(inexistente.json(), externo.json())

    def test_autenticacao(self):
        sem_chave = APIClient().post(URL, self.payload(), format='json')
        self.assert_erro(sem_chave, 401, 'credencial_invalida')
        self.assertEqual(sem_chave['WWW-Authenticate'], 'X-API-Key')
        self.assert_erro(self.enviar(chave='invalida'), 401, 'credencial_invalida')
        desativar_credencial(self.request(), self.credencial.pk)
        self.assert_erro(self.enviar(), 401, 'credencial_invalida')

    def test_metodos(self):
        for metodo in ('get', 'put', 'patch', 'delete'):
            self.assert_erro(getattr(APIClient(), metodo)(URL, HTTP_X_API_KEY=self.chave),
                             405, 'metodo_nao_permitido')
        self.assertEqual(APIClient().options(URL, HTTP_X_API_KEY=self.chave).status_code, 200)

    def test_invariante_corrompida_nao_vira_saldo_insuficiente(self):
        self.resgatar()
        # Corrupção deliberada fora do contrato de escrita do domínio.
        AlocacaoResgate._base_manager.all().update(pontos_consumidos=Decimal('251.0000'))
        with self.assertRaisesMessage(ValidationError, 'excede sua concessão'):
            simular_resgate(credencial=self.credencial, **self.payload())
        with self.assertRaisesMessage(ValidationError, 'excede sua concessão'):
            self.resgatar(identificador_externo='HISTORICO-INCONSISTENTE')
        resposta = self.enviar()
        self.assert_erro(resposta, 400, 'requisicao_invalida')
        self.assertIn('O histórico de consumo do Lote excede sua concessão.',
                      resposta.json()['erro']['detalhes'])

    def test_dominio_reutiliza_validacao_fisica(self):
        for pontos in ('100', 100.0, True):
            with self.assertRaises(ValidationError):
                simular_resgate(credencial=self.credencial, loja_id=self.loja.pk,
                               cliente_cpf=self.usuario.cpf, pontos=pontos)


class SimulacaoResgateOpenAPITests(SimpleTestCase):
    def test_contrato(self):
        resposta = self.client.get('/api/schema/', HTTP_ACCEPT='application/vnd.oai.openapi+json')
        self.assertEqual(resposta.status_code, 200)
        schema = json.loads(resposta.content)
        rota = schema['paths'][URL]
        self.assertEqual(set(rota), {'post'})
        post = rota['post']
        self.assertEqual(post['security'], [{'X-API-Key': []}])
        self.assertEqual(set(post['responses']), {'200', '400', '401', '403', '404', '405'})

        def resolver(valor):
            return schema['components']['schemas'][valor['$ref'].split('/')[-1]]

        entrada = resolver(post['requestBody']['content']['application/json']['schema'])
        self.assertTrue(post['requestBody']['required'])
        self.assertEqual(set(entrada['required']), {'loja_id', 'cliente_cpf', 'pontos'})
        self.assertEqual(set(entrada['properties']), set(entrada['required']))
        self.assertFalse(entrada['additionalProperties'])
        saida = resolver(post['responses']['200']['content']['application/json']['schema'])['properties']
        self.assertEqual(set(saida), {'cliente', 'simulada_em', 'pontos_resgatados', 'valor_desconto', 'saldo'})
        for pontos in (entrada['properties']['pontos'], saida['pontos_resgatados']):
            self.assertEqual(pontos['type'], 'integer')
            self.assertEqual(pontos['minimum'], 1)
            self.assertEqual(pontos['maximum'], MAX_PONTOS_RESGATE)
            self.assertNotIn('format', pontos)
        self.assertEqual(saida['simulada_em']['format'], 'date-time')
        self.assertEqual(saida['valor_desconto']['type'], 'string')
        self.assertEqual(set(resolver(saida['cliente'])['properties']), {'cpf', 'nome'})
        saldo = resolver(saida['saldo'])['properties']
        self.assertEqual(set(saldo), {'atual', 'projetado'})
        self.assertTrue(all(campo['type'] == 'string' for campo in saldo.values()))
