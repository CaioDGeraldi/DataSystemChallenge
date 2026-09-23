import secrets
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class MigracaoIntegracoesTests(TransactionTestCase):
    def test_0007_para_0008_preserva_dominio_e_cria_tabelas_vazias(self):
        executor = MigrationExecutor(connection)
        estado_final = executor.loader.graph.leaf_nodes()
        origem = [
            ("empresas", "0007_configuracao_fidelidade"),
            ("clientes", "0002_alter_cliente_usuario_and_more"),
        ]
        destino = [
            ("empresas", "0008_credenciais_integracao"),
            ("clientes", "0002_alter_cliente_usuario_and_more"),
        ]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(estado_final))
        executor.migrate(origem)
        antigos = executor.loader.project_state(origem).apps
        Usuario = antigos.get_model("usuarios", "Usuario")
        Empresa = antigos.get_model("empresas", "Empresa")
        Loja = antigos.get_model("empresas", "Loja")
        Membro = antigos.get_model("empresas", "MembroEmpresa")
        usuario = Usuario.objects.create(cpf="52998224725", first_name="Ana", last_name="Silva", password="!")
        gestor = Usuario.objects.create(cpf="11144477735", password="!")
        empresa = Empresa.objects.create(nome="Empresa A", slug="a", cnpj="11222333000181")
        outra = Empresa.objects.create(nome="Empresa B", slug="b", cnpj="11444777000161")
        loja = Loja.objects.create(empresa_id=empresa.pk, nome="Centro", cidade="Araras")
        Loja.objects.create(empresa_id=outra.pk, nome="Outra", cidade="Campinas")
        admin = Membro.objects.create(usuario_id=usuario.pk, empresa_id=empresa.pk, papel="ADMINISTRADOR", ativo=True)
        membro = Membro.objects.create(usuario_id=gestor.pk, empresa_id=empresa.pk, papel="GESTOR", ativo=True)
        antigos.get_model("empresas", "AcessoLoja").objects.create(membro_id=membro.pk, loja_id=loja.pk)
        antigos.get_model("clientes", "Cliente").objects.create(usuario_id=usuario.pk, empresa_id=empresa.pk)
        convite = antigos.get_model("empresas", "ConviteMembro").objects.create(
            empresa_id=empresa.pk, criado_por_id=admin.pk, cpf="12345678909", papel="GESTOR",
            token_hash=secrets.token_hex(32), expira_em=timezone.now() + timedelta(days=7),
        )
        antigos.get_model("empresas", "ConviteAcessoLoja").objects.create(convite_id=convite.pk, loja_id=loja.pk)
        antigos.get_model("empresas", "ConfiguracaoFidelidadeEmpresa").objects.create(
            empresa_id=empresa.pk, pontos_por_real=Decimal("2.50"), validade_pontos_meses=24,
            resgate_minimo_pontos=200, incremento_resgate_pontos=50,
            valor_monetario_por_ponto=Decimal("0.10"), periodo_cliente_ativo_dias=90,
        )
        antigos.get_model("empresas", "OverrideFidelidadeLoja").objects.create(
            loja_id=loja.pk, pontos_por_real=Decimal("3.25"),
        )
        modelos = [
            ("usuarios", "Usuario"), ("clientes", "Cliente"),
            ("empresas", "Empresa"), ("empresas", "Loja"), ("empresas", "MembroEmpresa"),
            ("empresas", "AcessoLoja"), ("empresas", "ConviteMembro"),
            ("empresas", "ConviteAcessoLoja"), ("empresas", "ConfiguracaoFidelidadeEmpresa"),
            ("empresas", "OverrideFidelidadeLoja"),
        ]
        anteriores = {
            modelo: list(antigos.get_model(*modelo).objects.order_by("pk").values())
            for modelo in modelos
        }
        executor = MigrationExecutor(connection)
        executor.migrate(destino)
        novos = executor.loader.project_state(destino).apps
        for modelo, registros in anteriores.items():
            with self.subTest(modelo=modelo):
                self.assertEqual(list(novos.get_model(*modelo).objects.order_by("pk").values()), registros)
        self.assertFalse(novos.get_model("empresas", "CredencialIntegracao").objects.exists())
        self.assertFalse(novos.get_model("empresas", "CredencialAcessoLoja").objects.exists())
