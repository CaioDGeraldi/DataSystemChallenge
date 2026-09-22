from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone
from datetime import timedelta


class MigracaoParametrosTests(TransactionTestCase):
    def test_incremental_preserva_empresa_loja_membro_e_convite(self):
        executor = MigrationExecutor(connection)
        destino = executor.loader.graph.leaf_nodes()
        origem = [("empresas", "0006_convitemembro_conviteacessoloja")]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(destino))
        executor.migrate(origem)
        antigos = executor.loader.project_state(origem).apps
        usuario = antigos.get_model("usuarios", "Usuario").objects.create(cpf="52998224725", password="!")
        empresa = antigos.get_model("empresas", "Empresa").objects.create(nome="Empresa", slug="empresa", cnpj="11222333000181")
        loja = antigos.get_model("empresas", "Loja").objects.create(empresa_id=empresa.pk, nome="Centro", cidade="Franca")
        membro = antigos.get_model("empresas", "MembroEmpresa").objects.create(usuario_id=usuario.pk, empresa_id=empresa.pk, papel="ADMINISTRADOR", ativo=True)
        convite = antigos.get_model("empresas", "ConviteMembro").objects.create(
            empresa_id=empresa.pk, criado_por_id=membro.pk, cpf="11144477735", papel="GESTOR",
            token_hash="a" * 64, expira_em=timezone.now() + timedelta(days=7),
        )
        acesso = antigos.get_model("empresas", "ConviteAcessoLoja").objects.create(convite_id=convite.pk, loja_id=loja.pk)
        executor = MigrationExecutor(connection)
        executor.migrate(destino)
        novos = executor.loader.project_state(destino).apps
        self.assertEqual(novos.get_model("empresas", "Empresa").objects.get(pk=empresa.pk).slug, "empresa")
        self.assertEqual(novos.get_model("empresas", "Loja").objects.get(pk=loja.pk).empresa_id, empresa.pk)
        self.assertEqual(novos.get_model("empresas", "MembroEmpresa").objects.get(pk=membro.pk).usuario_id, usuario.pk)
        self.assertEqual(novos.get_model("empresas", "ConviteMembro").objects.get(pk=convite.pk).token_hash, convite.token_hash)
        self.assertEqual(novos.get_model("empresas", "ConviteAcessoLoja").objects.get(pk=acesso.pk).loja_id, loja.pk)
        self.assertFalse(novos.get_model("empresas", "ConfiguracaoFidelidadeEmpresa").objects.exists())
        self.assertFalse(novos.get_model("empresas", "OverrideFidelidadeLoja").objects.exists())
