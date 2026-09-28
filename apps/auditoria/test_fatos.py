from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.fidelidade.models import Compra, EstornoResgate, LotePontos, Resgate
from apps.fidelidade.test_estornos import DadosEstornos

from .contexto import contexto_auditoria
from .models import EventoAuditoria


# Contrato independente do SQL da migration: nenhum campo extra é aceito.
ALLOWLISTS = {
    Compra: {
        'id', 'resgate_id', 'loja_id', 'cliente_id', 'credencial_origem_id',
        'identificador_externo', 'valor', 'ocorrida_em', 'criada_em',
    },
    Resgate: {
        'id', 'loja_id', 'cliente_id', 'credencial_origem_id', 'identificador_externo',
        'pontos_resgatados', 'resgate_minimo_pontos_aplicado',
        'incremento_resgate_pontos_aplicado', 'valor_monetario_por_ponto_aplicado',
        'valor_desconto', 'resgatado_em',
    },
    EstornoResgate: {
        'id', 'resgate_id', 'loja_id', 'cliente_id', 'credencial_origem_id',
        'identificador_externo', 'devolve_pontos_aplicado', 'estornado_em',
    },
    LotePontos: {
        'id', 'compra_id', 'cliente_id', 'pontos_base', 'pontos_concedidos',
        'pontos_por_real_aplicado', 'multiplicador_pontos_aplicado',
        'precisao_pontos_aplicada', 'modo_arredondamento_aplicado',
        'validade_pontos_meses_aplicada', 'adquiridos_em', 'expira_em',
        'criado_em', 'beneficios_aplicados',
    },
}


class DadosFatos(DadosEstornos):
    def compra_sql(self, *, loja=None, cliente=None, credencial=None, identificador='SQL'):
        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO fidelidade_compra '
                '(loja_id, cliente_id, credencial_origem_id, identificador_externo, '
                'valor, ocorrida_em, criada_em) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id',
                [(loja or self.loja).pk, (cliente or self.cliente).pk,
                 (credencial or self.credencial).pk, identificador, Decimal('100.00'),
                 self.instante, self.instante],
            )
            return Compra.objects.get(pk=cursor.fetchone()[0])

    def resgate_sql(self):
        # Fato independente de alocações, para exercitar DELETE e PK via SQL.
        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO fidelidade_resgate '
                '(loja_id, cliente_id, credencial_origem_id, identificador_externo, '
                'pontos_resgatados, resgate_minimo_pontos_aplicado, '
                'incremento_resgate_pontos_aplicado, valor_monetario_por_ponto_aplicado, '
                'valor_desconto, resgatado_em) '
                'VALUES (%s, %s, %s, %s, 100, 100, 50, 0.05, 5.00, %s) RETURNING id',
                [self.loja.pk, self.cliente.pk, self.credencial.pk, 'SQL-RESGATE', self.instante],
            )
            return Resgate.objects.get(pk=cursor.fetchone()[0])

    def estorno_sql(self):
        resgate = self.resgate_sql()
        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO fidelidade_estornoresgate '
                '(resgate_id, loja_id, cliente_id, credencial_origem_id, '
                'identificador_externo, devolve_pontos_aplicado, estornado_em) '
                'VALUES (%s, %s, %s, %s, %s, true, %s) RETURNING id',
                [resgate.pk, self.loja.pk, self.cliente.pk, self.credencial.pk,
                 'SQL-ESTORNO', self.instante],
            )
            return EstornoResgate.objects.get(pk=cursor.fetchone()[0])

    def evento(self, objeto, operacao):
        return EventoAuditoria.objects.get(
            tabela_origem=objeto._meta.db_table, registro_id=str(objeto.pk), operacao=operacao,
        )

    def assert_snapshot(self, dados, objeto):
        self.assertEqual(set(dados), ALLOWLISTS[type(objeto)])
        for campo, valor in dados.items():
            esperado = getattr(objeto, campo)
            if isinstance(esperado, datetime):
                valor = datetime.fromisoformat(valor)
            elif isinstance(esperado, Decimal):
                valor = Decimal(str(valor))
            self.assertEqual(valor, esperado, campo)

    def assert_tenant(self, evento, loja=None):
        loja = loja or self.loja
        self.assertEqual((evento.empresa_id, evento.loja_id), (loja.empresa_id, loja.pk))

    def assert_ator_api(self, evento):
        self.assertEqual(evento.origem, EventoAuditoria.Origem.API)
        self.assertEqual(evento.credencial_id, self.credencial.pk)
        self.assertIsNone(evento.usuario_id)

    def post(self, caminho, dados):
        with patch('django.utils.timezone.now', return_value=self.instante):
            return APIClient().post(caminho, dados, format='json', HTTP_X_API_KEY=self.chave)


class FatosAPITests(DadosFatos, TestCase):
    def test_compra_api_allowlist_lote_sem_insert_e_retry_sem_novo_evento(self):
        dados = dict(loja_id=self.loja.pk, cliente_cpf=self.usuario.cpf,
                     identificador_externo='API-COMPRA', valor='200.00',
                     ocorrida_em=self.instante.isoformat())
        resposta = self.post('/api/v1/compras/', dados)
        self.assertEqual(resposta.status_code, 201, resposta.content)
        compra = Compra.objects.get()
        evento = self.evento(compra, 'INSERT')
        self.assertEqual(evento.tipo_evento, 'COMPRA_CRIADA')
        self.assert_tenant(evento)
        self.assert_ator_api(evento)
        self.assertIsNone(evento.dados_anteriores)
        self.assert_snapshot(evento.dados_novos, compra)
        self.assertEqual(LotePontos.objects.get().compra_id, compra.pk)
        self.assertFalse(EventoAuditoria.objects.filter(tabela_origem='fidelidade_lotepontos').exists())
        self.assertEqual(EventoAuditoria.objects.count(), 1)
        retry = self.post('/api/v1/compras/', dados)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json(), resposta.json())
        self.assertEqual(EventoAuditoria.objects.count(), 1)
        # Mesma conexão após o endpoint: credencial da API não contamina SQL direto.
        seguinte = self.evento(self.compra_sql(), 'INSERT')
        self.assertEqual((seguinte.origem, seguinte.usuario_id, seguinte.credencial_id), (None, None, None))

    def test_resgate_api_e_retry(self):
        self.lote('300.00')
        dados = dict(loja_id=self.loja.pk, cliente_cpf=self.usuario.cpf,
                     identificador_externo='API-RESGATE', pontos=100)
        resposta = self.post('/api/v1/resgates/', dados)
        self.assertEqual(resposta.status_code, 201, resposta.content)
        resgate = Resgate.objects.get()
        evento = self.evento(resgate, 'INSERT')
        self.assertEqual(evento.tipo_evento, 'RESGATE_CRIADO')
        self.assert_tenant(evento)
        self.assert_ator_api(evento)
        self.assertIsNone(evento.dados_anteriores)
        self.assert_snapshot(evento.dados_novos, resgate)
        antes = list(EventoAuditoria.objects.order_by('pk').values())
        retry = self.post('/api/v1/resgates/', dados)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json(), resposta.json())
        self.assertEqual(list(EventoAuditoria.objects.order_by('pk').values()), antes)
        self.assertEqual(EventoAuditoria.objects.filter(tipo_evento='RESGATE_CRIADO').count(), 1)

    def test_estorno_api_e_retry(self):
        self.lote()
        self.resgatar()
        dados = dict(loja_id=self.loja.pk, resgate_identificador_externo='RESGATE-001',
                     identificador_externo='API-ESTORNO')
        resposta = self.post('/api/v1/resgates/estornar/', dados)
        self.assertEqual(resposta.status_code, 201, resposta.content)
        estorno = EstornoResgate.objects.get()
        evento = self.evento(estorno, 'INSERT')
        self.assertEqual(evento.tipo_evento, 'ESTORNO_RESGATE_CRIADO')
        self.assert_tenant(evento)
        self.assert_ator_api(evento)
        self.assertIsNone(evento.dados_anteriores)
        self.assert_snapshot(evento.dados_novos, estorno)
        antes = list(EventoAuditoria.objects.order_by('pk').values())
        retry = self.post('/api/v1/resgates/estornar/', dados)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json(), resposta.json())
        self.assertEqual(list(EventoAuditoria.objects.order_by('pk').values()), antes)
        self.assertEqual(EventoAuditoria.objects.filter(tipo_evento='ESTORNO_RESGATE_CRIADO').count(), 1)

    def test_consultas_e_simulacoes_nao_abrem_contexto_nem_auditam_autenticacao(self):
        self.lote('300.00')
        antes = EventoAuditoria.objects.count()
        consulta = dict(loja_id=self.loja.pk, cliente_cpf=self.usuario.cpf)
        with patch('apps.api.views.contexto_auditoria', side_effect=AssertionError('Contexto indevido')):
            for caminho, dados in (
                ('/api/v1/contexto/', {}), ('/api/v1/clientes/fidelidade/', consulta),
            ):
                resposta = APIClient().get(caminho, dados, HTTP_X_API_KEY=self.chave)
                self.assertEqual(resposta.status_code, 200, resposta.content)
            for caminho, dados in (
                ('/api/v1/compras/simular/', dict(consulta, valor='100.00')),
                ('/api/v1/resgates/simular/', dict(consulta, pontos=100)),
            ):
                resposta = self.post(caminho, dados)
                self.assertEqual(resposta.status_code, 200, resposta.content)
        self.assertEqual(EventoAuditoria.objects.count(), antes)
        self.credencial.refresh_from_db()
        self.assertIsNotNone(self.credencial.ultimo_uso_em)

    def test_falha_apos_insert_compra_desfaz_fato_e_auditoria_na_api(self):
        def falhar(compra):
            self.assertTrue(Compra.objects.filter(pk=compra.pk).exists())
            self.assert_ator_api(self.evento(compra, 'INSERT'))
            raise RuntimeError('Falha após INSERT e auditoria')

        with patch('apps.fidelidade.services._criar_lote_da_nova_compra', side_effect=falhar):
            with self.assertRaisesMessage(RuntimeError, 'Falha após INSERT e auditoria'):
                self.post('/api/v1/compras/', dict(
                    loja_id=self.loja.pk, cliente_cpf=self.usuario.cpf,
                    identificador_externo='ROLLBACK', valor='100.00',
                    ocorrida_em=self.instante.isoformat(),
                ))
        self.assertFalse(Compra.objects.exists())
        self.assertFalse(LotePontos.objects.exists())
        self.assertFalse(EventoAuditoria.objects.exists())


class FatosSQLTests(DadosFatos, TestCase):
    def test_insert_sql_sem_ator_e_tempo_real_do_trigger(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT transaction_timestamp(), clock_timestamp()')
            inicio, antes = cursor.fetchone()
        compra = self.compra_sql()
        with connection.cursor() as cursor:
            cursor.execute('SELECT clock_timestamp()')
            depois = cursor.fetchone()[0]
        evento = self.evento(compra, 'INSERT')
        self.assert_tenant(evento)
        self.assertEqual((evento.origem, evento.usuario_id, evento.credencial_id), (None, None, None))
        self.assert_snapshot(evento.dados_novos, compra)
        self.assertIsNone(evento.dados_anteriores)
        self.assertGreater(evento.ocorrido_em, inicio)
        self.assertGreaterEqual(evento.ocorrido_em, antes)
        self.assertLessEqual(evento.ocorrido_em, depois)

    def test_compra_update_sql_tenant_antigo_e_old_new(self):
        compra = self.compra_sql()
        with connection.cursor() as cursor:
            cursor.execute('UPDATE fidelidade_compra SET valor = 150, loja_id = %s WHERE id = %s',
                           [self.externa.pk, compra.pk])
        evento = self.evento(compra, 'UPDATE')
        self.assertEqual(evento.tipo_evento, 'COMPRA_ALTERADA')
        self.assert_tenant(evento)
        self.assert_snapshot(evento.dados_anteriores, compra)
        compra.refresh_from_db()
        self.assert_snapshot(evento.dados_novos, compra)
        self.assertEqual(evento.dados_novos['loja_id'], self.externa.pk)
        self.assertEqual(evento.dados_novos['valor'], 150)

    def test_compra_delete_sql_sem_dependencias(self):
        compra = self.compra_sql()
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM fidelidade_compra WHERE id = %s', [compra.pk])
        evento = self.evento(compra, 'DELETE')
        self.assertEqual(evento.tipo_evento, 'COMPRA_EXCLUIDA')
        self.assert_tenant(evento)
        self.assert_snapshot(evento.dados_anteriores, compra)
        self.assertIsNone(evento.dados_novos)
        self.assertFalse(Compra.objects.filter(pk=compra.pk).exists())

    def test_resgate_e_estorno_sql_insert_update_delete_e_tenant_old(self):
        for criar, prefixo in ((self.resgate_sql, 'RESGATE'), (self.estorno_sql, 'ESTORNO_RESGATE')):
            with self.subTest(prefixo=prefixo), transaction.atomic():
                objeto = criar()
                insercao = self.evento(objeto, 'INSERT')
                self.assertEqual(insercao.tipo_evento, prefixo + '_CRIADO')
                self.assertIsNone(insercao.dados_anteriores)
                self.assert_snapshot(insercao.dados_novos, objeto)
                self.assert_tenant(insercao)
                self.assertEqual((insercao.origem, insercao.usuario_id, insercao.credencial_id), (None, None, None))
                tabela = connection.ops.quote_name(objeto._meta.db_table)
                with connection.cursor() as cursor:
                    cursor.execute(f'UPDATE {tabela} SET loja_id = %s WHERE id = %s',
                                   [self.externa.pk, objeto.pk])
                alteracao = self.evento(objeto, 'UPDATE')
                self.assertEqual(alteracao.tipo_evento, prefixo + '_ALTERADO')
                self.assert_tenant(alteracao)
                self.assert_snapshot(alteracao.dados_anteriores, objeto)
                objeto.refresh_from_db()
                self.assert_snapshot(alteracao.dados_novos, objeto)
                with connection.cursor() as cursor:
                    cursor.execute(f'DELETE FROM {tabela} WHERE id = %s', [objeto.pk])
                exclusao = self.evento(objeto, 'DELETE')
                self.assertEqual(exclusao.tipo_evento, prefixo + '_EXCLUIDO')
                self.assert_tenant(exclusao, self.externa)
                self.assert_snapshot(exclusao.dados_anteriores, objeto)
                self.assertIsNone(exclusao.dados_novos)
                transaction.set_rollback(True)

    def test_lote_update_delete_allowlist_inclui_snapshot_sem_insert(self):
        lote = self.lote()
        self.assertFalse(EventoAuditoria.objects.filter(tabela_origem=lote._meta.db_table).exists())
        with connection.cursor() as cursor:
            cursor.execute('UPDATE fidelidade_lotepontos SET pontos_concedidos = 150 WHERE id = %s', [lote.pk])
        evento = self.evento(lote, 'UPDATE')
        self.assertEqual(evento.tipo_evento, 'LOTE_PONTOS_ALTERADO')
        self.assert_tenant(evento)
        self.assert_snapshot(evento.dados_anteriores, lote)
        lote.refresh_from_db()
        self.assert_snapshot(evento.dados_novos, lote)
        self.assertIsNotNone(evento.dados_novos['beneficios_aplicados'])
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM fidelidade_lotepontos WHERE id = %s', [lote.pk])
        evento = self.evento(lote, 'DELETE')
        self.assertEqual(evento.tipo_evento, 'LOTE_PONTOS_EXCLUIDO')
        self.assert_tenant(evento)
        self.assert_snapshot(evento.dados_anteriores, lote)
        self.assertIsNone(evento.dados_novos)
        self.assertFalse(LotePontos.objects.exists())

    def test_lote_trocando_compra_preserva_tenant_da_compra_old(self):
        lote = self.lote()
        credencial, _ = self.emitir(membro=self.outro_membro)
        outra = self.compra_sql(loja=self.externa, cliente=self.cliente_externo, credencial=credencial)
        with connection.cursor() as cursor:
            cursor.execute('UPDATE fidelidade_lotepontos SET compra_id = %s WHERE id = %s', [outra.pk, lote.pk])
        evento = self.evento(lote, 'UPDATE')
        self.assert_tenant(evento)
        self.assertEqual(evento.dados_anteriores['compra_id'], lote.compra_id)
        self.assertEqual(evento.dados_novos['compra_id'], outra.pk)

    def test_update_noop_nas_quatro_tabelas_nao_gera_evento(self):
        lote = self.lote()
        estorno = self.estorno_sql()
        antes = EventoAuditoria.objects.count()
        for objeto in (lote.compra, lote, estorno.resgate, estorno):
            with self.subTest(tabela=objeto._meta.db_table), connection.cursor() as cursor:
                tabela = connection.ops.quote_name(objeto._meta.db_table)
                cursor.execute(f'UPDATE {tabela} SET id = id WHERE id = %s', [objeto.pk])
        self.assertEqual(EventoAuditoria.objects.count(), antes)

    def test_update_pk_preserva_registro_id_antigo_nas_quatro_tabelas(self):
        for criar in (self.compra_sql, self.resgate_sql, self.estorno_sql, self.lote):
            with self.subTest(fabrica=criar.__name__), transaction.atomic():
                objeto = criar()
                novo_id = objeto.pk + 1000000
                tabela = connection.ops.quote_name(objeto._meta.db_table)
                with connection.cursor() as cursor:
                    cursor.execute(f'UPDATE {tabela} SET id = %s WHERE id = %s', [novo_id, objeto.pk])
                evento = self.evento(objeto, 'UPDATE')
                self.assertEqual(evento.dados_anteriores['id'], objeto.pk)
                self.assertEqual(evento.dados_novos['id'], novo_id)
                self.assert_tenant(evento)
                transaction.set_rollback(True)

    def test_falha_no_insert_da_auditoria_aborta_operacao(self):
        # ID negativo viola a constraint real da auditoria; não simula a função SQL.
        with self.assertRaises(IntegrityError) as erro:
            with contexto_auditoria(origem='API', credencial_id=-1):
                self.compra_sql()
        self.assertEqual(erro.exception.__cause__.diag.table_name, 'auditoria_eventoauditoria')
        self.assertFalse(Compra.objects.exists())
        self.assertFalse(EventoAuditoria.objects.exists())


class MigrationFatosTests(DadosFatos, TransactionTestCase):
    FUNCOES = {
        'auditoria_registrar_evento', 'auditoria_compra_fatos', 'auditoria_resgate_fatos',
        'auditoria_estorno_resgate_fatos', 'auditoria_lote_pontos_fatos',
    }
    TRIGGERS = {
        ('fidelidade_compra', 'auditoria_compra_fatos_trg', 1 | 4 | 8 | 16),
        ('fidelidade_resgate', 'auditoria_resgate_fatos_trg', 1 | 4 | 8 | 16),
        ('fidelidade_estornoresgate', 'auditoria_estorno_resgate_fatos_trg', 1 | 4 | 8 | 16),
        ('fidelidade_lotepontos', 'auditoria_lote_pontos_fatos_trg', 1 | 8 | 16),
    }

    def funcoes(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT proname FROM pg_proc WHERE proname = ANY(%s) '
                           'AND pronamespace = current_schema()::regnamespace', [list(self.FUNCOES)])
            return {nome for nome, in cursor.fetchall()}

    def triggers(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT c.relname, t.tgname, t.tgtype FROM pg_trigger t "
                           "JOIN pg_class c ON c.oid = t.tgrelid "
                           "WHERE NOT t.tgisinternal AND t.tgname LIKE 'auditoria_%%_fatos_trg'")
            return set(cursor.fetchall())

    def test_funcoes_triggers_reversao_e_reaplicacao_preservam_historico(self):
        self.assertEqual(connection.vendor, 'postgresql')
        self.assertEqual(self.funcoes(), self.FUNCOES)
        self.assertEqual(self.triggers(), self.TRIGGERS)
        compra = self.compra_sql()
        evento = self.evento(compra, 'INSERT')
        destino = MigrationExecutor(connection).loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(destino))
        MigrationExecutor(connection).migrate([('auditoria', '0001_initial')])
        self.assertEqual(self.funcoes(), set())
        self.assertEqual(self.triggers(), set())
        self.assertTrue(EventoAuditoria.objects.filter(pk=evento.pk).exists())
        with connection.cursor() as cursor:
            cursor.execute('UPDATE fidelidade_compra SET valor = 200 WHERE id = %s', [compra.pk])
        self.assertEqual(EventoAuditoria.objects.count(), 1)
        MigrationExecutor(connection).migrate(destino)
        self.assertEqual(self.funcoes(), self.FUNCOES)
        self.assertEqual(self.triggers(), self.TRIGGERS)
        with connection.cursor() as cursor:
            cursor.execute('UPDATE fidelidade_compra SET valor = 300 WHERE id = %s', [compra.pk])
        alteracao = self.evento(compra, 'UPDATE')
        self.assertEqual(alteracao.dados_anteriores['valor'], 200)
        self.assertEqual(alteracao.dados_novos['valor'], 300)
        self.assertEqual(EventoAuditoria.objects.count(), 2)
