from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class MigracaoConvitesTests(TransactionTestCase):
    def test_migration_incremental_preserva_dominio_existente(self):
        executor = MigrationExecutor(connection)
        destino = executor.loader.graph.leaf_nodes()
        origem = [("empresas", "0005_empresa_slug")]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(destino))
        executor.migrate(origem)
        anteriores = executor.loader.project_state(origem).apps
        usuario = anteriores.get_model("usuarios", "Usuario").objects.create(cpf="52998224725", password="!")
        empresa = anteriores.get_model("empresas", "Empresa").objects.create(nome="Empresa", slug="empresa", cnpj="11222333000181")
        loja = anteriores.get_model("empresas", "Loja").objects.create(empresa_id=empresa.pk, nome="Centro", cidade="Franca")
        membro = anteriores.get_model("empresas", "MembroEmpresa").objects.create(usuario_id=usuario.pk, empresa_id=empresa.pk, papel="GESTOR", ativo=True)
        acesso = anteriores.get_model("empresas", "AcessoLoja").objects.create(membro_id=membro.pk, loja_id=loja.pk)
        executor = MigrationExecutor(connection)
        executor.migrate(destino)
        atuais = executor.loader.project_state(destino).apps
        self.assertEqual(atuais.get_model("empresas", "Empresa").objects.get(pk=empresa.pk).slug, "empresa")
        self.assertEqual(atuais.get_model("empresas", "MembroEmpresa").objects.get(pk=membro.pk).usuario_id, usuario.pk)
        self.assertEqual(atuais.get_model("empresas", "AcessoLoja").objects.get(pk=acesso.pk).loja_id, loja.pk)
        self.assertFalse(atuais.get_model("empresas", "ConviteMembro").objects.exists())
        self.assertFalse(atuais.get_model("empresas", "ConviteAcessoLoja").objects.exists())
