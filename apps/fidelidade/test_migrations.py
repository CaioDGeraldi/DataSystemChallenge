import secrets
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class MigracaoCompraTests(TransactionTestCase):
    def test_inicial_preserva_dominio_existente_inclusive_credenciais_e_configuracoes(self):
        executor = MigrationExecutor(connection)
        destino = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(destino))
        executor.migrate([("fidelidade", None)])
        origem = [node for node in destino if node[0] != "fidelidade"]
        antigos = executor.loader.project_state(origem).apps
        usuario = antigos.get_model("usuarios", "Usuario").objects.create(
            cpf="52998224725", first_name="Ana", last_name="Silva", password="!",
        )
        empresa = antigos.get_model("empresas", "Empresa").objects.create(nome="Empresa", slug="empresa", cnpj="11222333000181")
        loja = antigos.get_model("empresas", "Loja").objects.create(empresa_id=empresa.pk, nome="Centro", cidade="Araras")
        membro = antigos.get_model("empresas", "MembroEmpresa").objects.create(
            usuario_id=usuario.pk, empresa_id=empresa.pk, papel="ADMINISTRADOR", ativo=True,
        )
        antigos.get_model("clientes", "Cliente").objects.create(usuario_id=usuario.pk, empresa_id=empresa.pk)
        credencial = antigos.get_model("empresas", "CredencialIntegracao").objects.create(
            empresa_id=empresa.pk, criada_por_id=membro.pk, nome="PDV", escopo="LOJAS",
            identificador=secrets.token_urlsafe(18), segredo_hash=make_password(secrets.token_urlsafe(32)),
        )
        antigos.get_model("empresas", "CredencialAcessoLoja").objects.create(credencial_id=credencial.pk, loja_id=loja.pk)
        antigos.get_model("empresas", "ConfiguracaoFidelidadeEmpresa").objects.create(
            empresa_id=empresa.pk, pontos_por_real=Decimal("2.50"),
        )
        antigos.get_model("empresas", "OverrideFidelidadeLoja").objects.create(loja_id=loja.pk, pontos_por_real=Decimal("3.00"))
        convite = antigos.get_model("empresas", "ConviteMembro").objects.create(
            empresa_id=empresa.pk, criado_por_id=membro.pk, cpf="11144477735", papel="GESTOR",
            token_hash=secrets.token_hex(32), expira_em=timezone.now() + timedelta(days=7),
        )
        antigos.get_model("empresas", "ConviteAcessoLoja").objects.create(convite_id=convite.pk, loja_id=loja.pk)
        modelos = [
            ("usuarios", "Usuario"), ("clientes", "Cliente"), ("empresas", "Empresa"),
            ("empresas", "Loja"), ("empresas", "MembroEmpresa"), ("empresas", "AcessoLoja"),
            ("empresas", "CredencialIntegracao"), ("empresas", "CredencialAcessoLoja"),
            ("empresas", "ConfiguracaoFidelidadeEmpresa"), ("empresas", "OverrideFidelidadeLoja"),
            ("empresas", "ConviteMembro"), ("empresas", "ConviteAcessoLoja"),
        ]
        antes = {modelo: list(antigos.get_model(*modelo).objects.order_by("pk").values()) for modelo in modelos}
        executor = MigrationExecutor(connection)
        executor.migrate(destino)
        atuais = executor.loader.project_state(destino).apps
        for modelo, registros in antes.items():
            with self.subTest(modelo=modelo):
                self.assertEqual(list(atuais.get_model(*modelo).objects.order_by("pk").values()), registros)
        self.assertFalse(atuais.get_model("fidelidade", "Compra").objects.exists())
