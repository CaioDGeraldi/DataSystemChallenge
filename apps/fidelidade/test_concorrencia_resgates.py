from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Barrier, local
from unittest.mock import patch

from django.db import close_old_connections, connection, connections, transaction
from django.test import SimpleTestCase, TransactionTestCase
from rest_framework.test import APIClient

from .escrita_resgates import _permitir_escrita_resgates
from .models import AlocacaoResgate, Resgate
from .resgates import _chave_lock_resgate, _selecionar_lotes_fefo, _travar_chave_resgate
from .test_resgates import DadosResgates


class ChaveAdvisoryTests(SimpleTestCase):
    def test_sha256_signed_64_deterministico_sem_hash_python(self):
        # Vetor definido pelo contrato, inclusive case e UTF-8; hash() não pode ser usado.
        esperado = int.from_bytes(sha256(b'resgate:7:RESGATE-001').digest()[:8], 'big', signed=True)
        with patch('builtins.hash', side_effect=AssertionError('hash randomizado proibido')):
            self.assertEqual(_chave_lock_resgate(7, 'RESGATE-001'), esperado)
            self.assertEqual(_chave_lock_resgate(7, 'RESGATE-001'), esperado)
            diferente = _chave_lock_resgate(7, 'resgate-001')
            unicode = _chave_lock_resgate(8, 'Resgate-ação')
        self.assertNotEqual(diferente, esperado)
        self.assertGreaterEqual(unicode, -(2**63))
        self.assertLess(unicode, 2**63)


class ConcorrenciaResgateTests(DadosResgates, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(connection.vendor, 'postgresql', 'Esta suíte exige PostgreSQL real.')

    def disputar(self, entradas, *, mesma_chave=True, clientes_independentes=False, sem_advisory=False):
        barreira = Barrier(2)
        independentes = Barrier(2)
        worker = local()

        def arbitrar(loja_id, identificador):
            # Captura a conexão da transação de Resgate, após a autenticação HTTP.
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '10s'")
                cursor.execute("SET LOCAL statement_timeout = '20s'")
                cursor.execute('SELECT pg_backend_pid()')
                worker.pid = cursor.fetchone()[0]
            # Chave igual: encontro ANTES do advisory, pois só um pode obtê-lo.
            # Chaves distintas: encontro DEPOIS, imediatamente antes do lock Cliente.
            if mesma_chave:
                barreira.wait(timeout=15)
            if not sem_advisory:
                _travar_chave_resgate(loja_id, identificador)
            if not mesma_chave:
                barreira.wait(timeout=15)

        def selecionar(cliente, instante):
            if clientes_independentes:
                # Prova progresso simultâneo depois dos locks de Clientes diferentes.
                independentes.wait(timeout=15)
            return _selecionar_lotes_fefo(cliente, instante)

        def executar(entrada):
            close_old_connections()
            try:
                dados = dict(loja_id=self.loja.pk, identificador_externo='CONCORRENTE',
                             cliente_cpf=self.usuario.cpf, pontos=100)
                dados.update(entrada)
                resposta = APIClient().post('/api/v1/resgates/', dados, format='json', HTTP_X_API_KEY=self.chave)
                return resposta.status_code, resposta.json(), worker.pid
            finally:
                connections.close_all()

        with patch('apps.fidelidade.resgates._travar_chave_resgate', arbitrar), \
                patch('apps.fidelidade.resgates._selecionar_lotes_fefo', selecionar), \
                patch('apps.fidelidade.resgates.timezone.now', return_value=self.instante), \
                ThreadPoolExecutor(max_workers=2) as pool:
            futuros = [pool.submit(executar, entrada) for entrada in entradas]
            resultados = [futuro.result(timeout=45) for futuro in futuros]
        self.assertEqual(len({pid for _, _, pid in resultados}), 2)
        self.assert_invariantes()
        return [(status, dados) for status, dados, _ in resultados]

    def test_mesma_chave_payload_equivalente(self):
        self.lote()
        respostas = self.disputar([{}, {}])
        self.assertCountEqual([s for s, _ in respostas], [201, 200])
        self.assertEqual(respostas[0][1], respostas[1][1])
        self.assertEqual((Resgate.objects.count(), AlocacaoResgate.objects.count()), (1, 1))

    def test_mesma_chave_cliente_divergente(self):
        self.lote()
        self.lote(cliente_cpf=self.outro_usuario.cpf)
        respostas = self.disputar([{}, {'cliente_cpf': self.outro_usuario.cpf}])
        self.assertCountEqual([s for s, _ in respostas], [201, 409])
        self.assertEqual([d['erro']['codigo'] for s, d in respostas if s == 409], ['idempotencia_conflitante'])
        self.assertEqual((Resgate.objects.count(), AlocacaoResgate.objects.count()), (1, 1))

    def test_mesma_chave_pontos_divergentes(self):
        self.lote('300.00')
        respostas = self.disputar([{}, {'pontos': 150}])
        self.assertCountEqual([s for s, _ in respostas], [201, 409])
        self.assertEqual((Resgate.objects.count(), AlocacaoResgate.objects.count()), (1, 1))

    def test_double_spend_chaves_distintas_mesmo_cliente(self):
        self.lote()
        respostas = self.disputar([{'identificador_externo': 'A'}, {'identificador_externo': 'B'}], mesma_chave=False)
        self.assertCountEqual([s for s, _ in respostas], [201, 400])
        self.assertEqual([d['erro']['codigo'] for s, d in respostas if s == 400], ['saldo_insuficiente'])
        self.assertEqual((Resgate.objects.count(), AlocacaoResgate.objects.count()), (1, 1))

    def test_mesmo_cliente_saldo_suficiente_para_ambos(self):
        self.lote('200.00')
        respostas = self.disputar([{'identificador_externo': 'A'}, {'identificador_externo': 'B'}], mesma_chave=False)
        self.assertEqual([s for s, _ in respostas], [201, 201])
        self.assertNotEqual(respostas[0][1]['id'], respostas[1][1]['id'])
        self.assertEqual((Resgate.objects.count(), AlocacaoResgate.objects.count()), (2, 2))

    def test_chaves_e_clientes_distintos_progridem_independentemente(self):
        self.lote()
        self.lote(cliente_cpf=self.outro_usuario.cpf)
        respostas = self.disputar([{'identificador_externo': 'A'},
            {'identificador_externo': 'B', 'cliente_cpf': self.outro_usuario.cpf}],
            mesma_chave=False, clientes_independentes=True)
        self.assertEqual([s for s, _ in respostas], [201, 201])
        self.assertEqual(Resgate.objects.count(), 2)

    def test_constraint_residual_mesma_chave_clientes_distintos_sem_advisory(self):
        self.lote()
        self.lote(cliente_cpf=self.outro_usuario.cpf)
        inserir = Resgate.save
        barreira_insert = Barrier(2)

        def inserir_juntos(resgate, *args, **kwargs):
            barreira_insert.wait(timeout=15)
            return inserir(resgate, *args, **kwargs)

        with patch.object(Resgate, 'save', inserir_juntos):
            respostas = self.disputar([{}, {'cliente_cpf': self.outro_usuario.cpf}], sem_advisory=True)
        self.assertCountEqual([s for s, _ in respostas], [201, 409])
        self.assertEqual((Resgate.objects.count(), AlocacaoResgate.objects.count()), (1, 1))

    def test_colisao_advisory_apenas_serializa_identidades_independentes(self):
        self.lote('200.00')
        # Encontro antes do lock: chaves textuais distintas colidem no bigint.
        with patch('apps.fidelidade.resgates._chave_lock_resgate', return_value=7):
            respostas = self.disputar([{'identificador_externo': 'A'}, {'identificador_externo': 'B'}])
        self.assertEqual([s for s, _ in respostas], [201, 201])
        self.assertEqual(Resgate.objects.count(), 2)

    def test_advisory_transacional_libera_no_commit_e_rollback(self):
        chave = _chave_lock_resgate(self.loja.pk, 'LIBERACAO')

        def tentar():
            close_old_connections()
            try:
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute('SELECT pg_try_advisory_xact_lock(%s)', [chave])
                    return cursor.fetchone()[0]
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            for rollback in (False, True):
                with transaction.atomic():
                    _travar_chave_resgate(self.loja.pk, 'LIBERACAO')
                    self.assertFalse(pool.submit(tentar).result(timeout=10))
                    if rollback:
                        transaction.set_rollback(True)
                self.assertTrue(pool.submit(tentar).result(timeout=10))
        with self.assertRaises(RuntimeError):
            _travar_chave_resgate(self.loja.pk, 'SEM-TRANSACAO')
        with self.assertRaises(RuntimeError), _permitir_escrita_resgates(Resgate()):
            pass

    def test_ordem_sql_dos_locks_e_retry_sem_lock_de_cliente(self):
        self.lote()
        consultas = []

        def observar(execute, sql, params, many, context):
            consultas.append(sql)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(observar):
            self.resgatar()
        locks = [sql for sql in consultas if 'pg_advisory' in sql or 'FOR ' in sql]
        self.assertEqual(len(locks), 3)
        self.assertIn('pg_advisory_xact_lock', locks[0])
        self.assertIn('clientes_cliente', locks[1])
        self.assertIn('FOR NO KEY UPDATE', locks[1])
        self.assertIn('fidelidade_lotepontos', locks[2])
        self.assertIn('FOR UPDATE', locks[2])
        self.assertRegex(locks[2], r'ORDER BY .*expira_em.* ASC, .*adquiridos_em.* ASC, .*id.* ASC')
        consultas.clear()
        with connection.execute_wrapper(observar):
            self.assertFalse(self.resgatar()[1])
        self.assertEqual(len([sql for sql in consultas if 'pg_advisory' in sql]), 1)
        self.assertFalse(any('FOR UPDATE' in sql or 'FOR NO KEY UPDATE' in sql for sql in consultas))
