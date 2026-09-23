import secrets
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class MigracaoPontosTests(TransactionTestCase):
    def test_incremental_preserva_f301_configuracoes_e_nao_cria_lotes(self):
        executor = MigrationExecutor(connection)
        destino = executor.loader.graph.leaf_nodes()
        origem = [('empresas', '0008_credenciais_integracao'), ('fidelidade', '0001_initial')]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(destino))
        executor.migrate(origem)
        antigos = executor.loader.project_state(origem).apps
        usuario = antigos.get_model('usuarios', 'Usuario').objects.create(cpf='52998224725', password='!')
        empresa = antigos.get_model('empresas', 'Empresa').objects.create(nome='Empresa', slug='empresa', cnpj='11222333000181')
        loja = antigos.get_model('empresas', 'Loja').objects.create(empresa_id=empresa.pk, nome='Centro', cidade='Araras')
        membro = antigos.get_model('empresas', 'MembroEmpresa').objects.create(
            usuario_id=usuario.pk, empresa_id=empresa.pk, papel='ADMINISTRADOR', ativo=True,
        )
        cliente = antigos.get_model('clientes', 'Cliente').objects.create(usuario_id=usuario.pk, empresa_id=empresa.pk)
        credencial = antigos.get_model('empresas', 'CredencialIntegracao').objects.create(
            empresa_id=empresa.pk, criada_por_id=membro.pk, nome='PDV', escopo='LOJAS',
            identificador=secrets.token_urlsafe(18), segredo_hash='!', ativa=False,
        )
        antigos.get_model('empresas', 'CredencialAcessoLoja').objects.create(credencial_id=credencial.pk, loja_id=loja.pk)
        antigos.get_model('empresas', 'ConfiguracaoFidelidadeEmpresa').objects.create(
            empresa_id=empresa.pk, pontos_por_real=Decimal('2.50'), validade_pontos_meses=24,
            resgate_minimo_pontos=200, incremento_resgate_pontos=50,
            valor_monetario_por_ponto=Decimal('0.10'), periodo_cliente_ativo_dias=90,
        )
        antigos.get_model('empresas', 'OverrideFidelidadeLoja').objects.create(loja_id=loja.pk, pontos_por_real=Decimal('1.25'))
        antigos.get_model('fidelidade', 'Compra').objects.create(
            loja_id=loja.pk, cliente_id=cliente.pk, credencial_origem_id=credencial.pk,
            identificador_externo='LEGADA', valor=Decimal('49.90'), ocorrida_em=timezone.now(),
        )
        modelos = [
            ('usuarios', 'Usuario'), ('empresas', 'Empresa'), ('empresas', 'Loja'),
            ('empresas', 'MembroEmpresa'), ('clientes', 'Cliente'),
            ('empresas', 'CredencialIntegracao'), ('empresas', 'CredencialAcessoLoja'),
            ('empresas', 'ConfiguracaoFidelidadeEmpresa'), ('empresas', 'OverrideFidelidadeLoja'),
            ('fidelidade', 'Compra'),
        ]
        antes = {modelo: list(antigos.get_model(*modelo).objects.order_by('pk').values()) for modelo in modelos}
        executor = MigrationExecutor(connection)
        executor.migrate(destino)
        atuais = executor.loader.project_state(destino).apps
        for modelo, registros in antes.items():
            campos = list(registros[0])
            with self.subTest(modelo=modelo):
                self.assertEqual(list(atuais.get_model(*modelo).objects.order_by('pk').values(*campos)), registros)
        config = atuais.get_model('empresas', 'ConfiguracaoFidelidadeEmpresa').objects.get()
        self.assertEqual(config.precisao_pontos, 2)
        self.assertEqual(config.modo_arredondamento_pontos, 'HALF_UP')
        self.assertEqual(atuais.get_model('fidelidade', 'Compra').objects.count(), 1)
        self.assertFalse(atuais.get_model('fidelidade', 'LotePontos').objects.exists())
