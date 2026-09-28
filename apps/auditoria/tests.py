from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from .contexto import CHAVES, contexto_auditoria
from .models import EventoAuditoria


def ler_contexto():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT NULLIF(current_setting(%s, true), ''), "
            "NULLIF(current_setting(%s, true), ''), "
            "NULLIF(current_setting(%s, true), '')",
            CHAVES,
        )
        return cursor.fetchone()


def inserir_evento():
    # SQL direto comprova a garantia sem depender de save() ou signals.
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO auditoria_eventoauditoria "
            "(tipo_evento, operacao, tabela_origem, registro_id, ocorrido_em) "
            "VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP) RETURNING id",
            ["TESTE_CRIADO", "INSERT", "tabela_teste", "registro-uuid-textual"],
        )
        return cursor.fetchone()[0]


class EventoAuditoriaTests(TestCase):
    def test_insert_direto_permitido_sem_ator_ficticio(self):
        self.assertEqual(connection.vendor, "postgresql")
        evento = EventoAuditoria.objects.get(pk=inserir_evento())
        self.assertEqual(evento.registro_id, "registro-uuid-textual")
        for campo in ("empresa_id", "loja_id", "usuario_id", "credencial_id",
                      "origem", "dados_anteriores", "dados_novos"):
            self.assertIsNone(getattr(evento, campo))
        self.assertFalse(any(campo.is_relation for campo in EventoAuditoria._meta.fields))
        self.assertEqual(EventoAuditoria.objects.count(), 1)

    def test_update_rejeitado(self):
        pk = inserir_evento()
        with self.assertRaisesMessage(DatabaseError, "append-only") as erro:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE auditoria_eventoauditoria SET registro_id = %s WHERE id = %s",
                        ["alterado", pk],
                    )
        self.assertEqual(erro.exception.__cause__.sqlstate, "55000")
        self.assertEqual(EventoAuditoria.objects.get(pk=pk).registro_id, "registro-uuid-textual")
        inserir_evento()
        self.assertEqual(EventoAuditoria.objects.count(), 2)

    def test_delete_rejeitado(self):
        pk = inserir_evento()
        with self.assertRaisesMessage(DatabaseError, "append-only"):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM auditoria_eventoauditoria WHERE id = %s", [pk])
        self.assertTrue(EventoAuditoria.objects.filter(pk=pk).exists())
        inserir_evento()
        self.assertEqual(EventoAuditoria.objects.count(), 2)

    def test_rollback_remove_evento(self):
        with self.assertRaisesMessage(ValueError, "rollback"):
            with transaction.atomic():
                inserir_evento()
                raise ValueError("rollback")
        self.assertFalse(EventoAuditoria.objects.exists())

    def test_unica_trigger_apenas_bloqueia_update_delete_sem_recursao(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT t.tgname, t.tgtype, p.prosrc FROM pg_trigger t "
                "JOIN pg_proc p ON p.oid = t.tgfoid "
                "WHERE t.tgrelid = 'auditoria_eventoauditoria'::regclass AND NOT t.tgisinternal"
            )
            triggers = cursor.fetchall()
        self.assertEqual(len(triggers), 1)
        nome, tipo, corpo = triggers[0]
        self.assertEqual(nome, "auditoria_evento_append_only_trg")
        self.assertEqual(tipo, 1 | 2 | 8 | 16)  # ROW | BEFORE | DELETE | UPDATE
        self.assertNotIn("INSERT", corpo.upper())
        self.assertIn("RAISE EXCEPTION", corpo.upper())
        inserir_evento()
        self.assertEqual(EventoAuditoria.objects.count(), 1)


class ContextoAuditoriaTests(TransactionTestCase):
    def assertSemContexto(self):
        self.assertEqual(ler_contexto(), (None, None, None))

    def test_api_e_transacao_propria_sem_vazamento_apos_commit(self):
        self.assertFalse(connection.in_atomic_block)
        self.assertSemContexto()
        with contexto_auditoria(origem="API", credencial_id=42, using="default"):
            self.assertTrue(connection.in_atomic_block)
            self.assertEqual(ler_contexto(), ("API", None, "42"))
        self.assertFalse(connection.in_atomic_block)
        with transaction.atomic():
            self.assertSemContexto()

    def test_gestao_web(self):
        with contexto_auditoria(origem="GESTAO_WEB", usuario_id=23):
            self.assertEqual(ler_contexto(), ("GESTAO_WEB", "23", None))
        self.assertSemContexto()

    def test_sistema_sem_ator(self):
        with contexto_auditoria(origem="SISTEMA"):
            self.assertEqual(ler_contexto(), ("SISTEMA", None, None))
        self.assertSemContexto()

    def test_ausencia_de_valores(self):
        with contexto_auditoria():
            self.assertSemContexto()
        self.assertSemContexto()

    def test_aninhamento_restaura_externo_inclusive_atomic_intermediario(self):
        with transaction.atomic():
            with contexto_auditoria(origem="API", credencial_id=42):
                with transaction.atomic():
                    with contexto_auditoria(origem="GESTAO_WEB", usuario_id=23):
                        self.assertEqual(ler_contexto(), ("GESTAO_WEB", "23", None))
                    self.assertEqual(ler_contexto(), ("API", None, "42"))
                with contexto_auditoria():
                    self.assertSemContexto()
                self.assertEqual(ler_contexto(), ("API", None, "42"))
            self.assertSemContexto()
        self.assertSemContexto()

    def test_excecao_python_preservada_e_sem_vazamento(self):
        original = ValueError("falha original")
        with self.assertRaises(ValueError) as erro:
            with contexto_auditoria(origem="API", credencial_id=42):
                inserir_evento()
                raise original
        self.assertIs(erro.exception, original)
        with transaction.atomic():
            self.assertSemContexto()
            self.assertFalse(EventoAuditoria.objects.exists())

    def test_erro_postgresql_interno_restaura_externo_sem_mascarar_erro(self):
        with contexto_auditoria(origem="API", credencial_id=42):
            with self.assertRaises(DatabaseError) as erro:
                with contexto_auditoria(origem="GESTAO_WEB", usuario_id=23):
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT 1 / 0")
            self.assertEqual(erro.exception.__cause__.sqlstate, "22012")
            self.assertEqual(ler_contexto(), ("API", None, "42"))
        self.assertSemContexto()

    def test_transacao_marcada_para_rollback_nao_consulta_restauracao(self):
        with contexto_auditoria(origem="API", credencial_id=42):
            with contexto_auditoria(origem="GESTAO_WEB", usuario_id=23):
                transaction.set_rollback(True)
            self.assertEqual(ler_contexto(), ("API", None, "42"))
        self.assertSemContexto()

    def test_rollback_externo_nao_vaza(self):
        with self.assertRaisesMessage(ValueError, "rollback externo"):
            with transaction.atomic():
                with contexto_auditoria(origem="API", credencial_id=42):
                    self.assertEqual(ler_contexto(), ("API", None, "42"))
                raise ValueError("rollback externo")
        with transaction.atomic():
            self.assertSemContexto()

    def test_origem_invalida_rejeitada_sem_alterar_contexto(self):
        with contexto_auditoria(origem="API", credencial_id=42):
            for origem in ("api", "INVALIDA", ""):
                with self.subTest(origem=origem):
                    with self.assertRaisesMessage(ValueError, "Origem de auditoria inválida"):
                        with contexto_auditoria(origem=origem):
                            self.fail("Não deve entrar no contexto inválido")
                    self.assertEqual(ler_contexto(), ("API", None, "42"))


class MigrationAuditoriaTests(TransactionTestCase):
    def test_reversao_remove_trigger_funcao_tabela_e_reaplicacao_funciona(self):
        destino = [("auditoria", "0001_initial")]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(destino))
        MigrationExecutor(connection).migrate([("auditoria", None)])
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('auditoria_eventoauditoria'), "
                           "to_regprocedure('auditoria_evento_append_only()')")
            self.assertEqual(cursor.fetchone(), (None, None))
            cursor.execute("SELECT count(*) FROM pg_trigger "
                           "WHERE tgname = 'auditoria_evento_append_only_trg'")
            self.assertEqual(cursor.fetchone()[0], 0)
        MigrationExecutor(connection).migrate(destino)
        pk = inserir_evento()
        with self.assertRaisesMessage(DatabaseError, "append-only"):
            with transaction.atomic():
                EventoAuditoria.objects.filter(pk=pk).update(registro_id="alterado")
        self.assertTrue(EventoAuditoria.objects.filter(pk=pk).exists())
