from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Barrier, local
from unittest.mock import patch

from django.db import close_old_connections, connection, connections
from django.test import SimpleTestCase, TransactionTestCase
from rest_framework.test import APIClient

from .estornos import _chave_lock_estorno, _travar_chave_estorno
from .models import EstornoResgate, Resgate
from .resgates import _chave_lock_resgate, _travar_chave_resgate
from .test_estornos import DadosEstornos


class ChaveEstornoTests(SimpleTestCase):
    def test_namespace_proprio_deterministico(self):
        esperado = int.from_bytes(sha256(b'estorno-resgate:7:ABC').digest()[:8], 'big', signed=True)
        self.assertEqual(_chave_lock_estorno(7, 'ABC'), esperado)
        self.assertNotEqual(_chave_lock_estorno(7, 'ABC'), _chave_lock_resgate(7, 'ABC'))
        self.assertNotEqual(_chave_lock_estorno(7, 'ABC'), _chave_lock_estorno(7, 'abc'))


class ConcorrenciaEstornoTests(DadosEstornos, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(connection.vendor, 'postgresql')
        self.lote()
        self.resgatar()

    def disputar(self, entradas):
        barreira = Barrier(2)
        worker = local()
        def arbitrar(travar, loja_id, identificador):
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '10s'")
                cursor.execute("SET LOCAL statement_timeout = '20s'")
                cursor.execute('SELECT pg_backend_pid()')
                worker.pid = cursor.fetchone()[0]
            barreira.wait(timeout=15)
            travar(loja_id, identificador)
        def executar(entrada):
            close_old_connections()
            try:
                novo = entrada.pop('novo', False)
                dados = dict(loja_id=self.loja.pk, identificador_externo='ESTORNO-001')
                if novo:
                    dados.update(cliente_cpf=self.usuario.cpf, pontos=100)
                else:
                    dados['resgate_identificador_externo'] = 'RESGATE-001'
                dados.update(entrada)
                url = '/api/v1/resgates/' if novo else '/api/v1/resgates/estornar/'
                resposta = APIClient().post(url, dados, format='json', HTTP_X_API_KEY=self.chave)
                return resposta.status_code, resposta.json(), worker.pid
            finally:
                connections.close_all()
        with patch('apps.fidelidade.estornos._travar_chave_estorno',
                   side_effect=lambda *args: arbitrar(_travar_chave_estorno, *args)), \
                patch('apps.fidelidade.resgates._travar_chave_resgate',
                      side_effect=lambda *args: arbitrar(_travar_chave_resgate, *args)), \
                patch('apps.fidelidade.estornos.timezone.now', return_value=self.instante), \
                ThreadPoolExecutor(max_workers=2) as pool:
            futuros = [pool.submit(executar, dict(e)) for e in entradas]
            resultados = [f.result(timeout=45) for f in futuros]
        self.assertEqual(len({pid for _, _, pid in resultados}), 2)
        self.assertEqual(EstornoResgate.objects.count(), 1)
        self.assert_invariantes()
        return [(status, dados) for status, dados, _ in resultados]

    def test_mesma_chave_um_201_um_200(self):
        respostas = self.disputar([{}, {}])
        self.assertCountEqual([s for s, _ in respostas], [201, 200])
        self.assertEqual(respostas[0][1], respostas[1][1])
        self.assertEqual(self.consulta()['saldo']['pontos'], '100.0000')

    def test_duas_chaves_mesmo_resgate(self):
        respostas = self.disputar([{}, {'identificador_externo': 'OUTRO'}])
        self.assertCountEqual([s for s, _ in respostas], [201, 409])
        self.assertEqual([d['erro']['codigo'] for s, d in respostas if s == 409], ['resgate_ja_estornado'])
        self.assertEqual(self.consulta()['saldo']['pontos'], '100.0000')

    def test_estorno_e_novo_resgate_ordem_serial(self):
        respostas = self.disputar([{}, {'novo': True, 'identificador_externo': 'NOVO'}])
        self.assertEqual(respostas[0][0], 201)
        status, dados = respostas[1]
        self.assertIn(status, (201, 400))
        if status == 201:
            self.assertEqual(self.consulta()['saldo']['pontos'], '0.0000')
            self.assertEqual(Resgate.objects.count(), 2)
        else:
            self.assertEqual(dados['erro']['codigo'], 'saldo_insuficiente')
            self.assertEqual(self.consulta()['saldo']['pontos'], '100.0000')
            self.assertEqual(Resgate.objects.count(), 1)
