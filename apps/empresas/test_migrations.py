from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class MigracaoMultiempresaTests(TransactionTestCase):
    def test_preserva_gestor_cliente_e_identidade_existentes(self):
        executor = MigrationExecutor(connection)
        destino = executor.loader.graph.leaf_nodes()
        origem = [("empresas", "0001_initial"), ("clientes", "0001_initial")]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(destino))
        executor.migrate(origem)
        antigos = executor.loader.project_state(origem).apps
        usuario = antigos.get_model("usuarios", "Usuario").objects.create(
            cpf="52998224725", first_name="Ana", last_name="Silva", password="!"
        )
        empresa = antigos.get_model("empresas", "Empresa").objects.create(
            nome="Empresa A", cnpj="11222333000181"
        )
        gestor = antigos.get_model("empresas", "Gestor").objects.create(usuario_id=usuario.pk, empresa_id=empresa.pk)
        cliente = antigos.get_model("clientes", "Cliente").objects.create(usuario_id=usuario.pk, empresa_id=empresa.pk)
        loja = antigos.get_model("empresas", "Loja").objects.create(empresa_id=empresa.pk, nome="Centro", cidade="Franca")

        executor = MigrationExecutor(connection)
        executor.migrate(destino)
        novos = executor.loader.project_state(destino).apps
        membro = novos.get_model("empresas", "MembroEmpresa").objects.get(pk=gestor.pk)
        cliente_migrado = novos.get_model("clientes", "Cliente").objects.get(pk=cliente.pk)
        self.assertEqual((membro.usuario_id, membro.empresa_id), (usuario.pk, empresa.pk))
        self.assertEqual(membro.papel, "GESTOR")
        self.assertTrue(membro.ativo)
        self.assertEqual((cliente_migrado.usuario_id, cliente_migrado.empresa_id), (usuario.pk, empresa.pk))
        self.assertEqual(cliente_migrado.cadastrado_em, cliente.cadastrado_em)
        self.assertEqual(novos.get_model("empresas", "Loja").objects.get(pk=loja.pk).empresa_id, empresa.pk)
        usuario_migrado = novos.get_model("usuarios", "Usuario").objects.get(pk=usuario.pk)
        self.assertEqual((usuario_migrado.cpf, usuario_migrado.first_name, usuario_migrado.last_name, usuario_migrado.password),
                         (usuario.cpf, usuario.first_name, usuario.last_name, usuario.password))
