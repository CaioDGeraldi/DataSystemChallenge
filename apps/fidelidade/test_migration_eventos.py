import secrets
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class MigracaoEventosTests(TransactionTestCase):
    def test_preserva_f302_default_neutro_sem_backfill_ou_aplicacoes(self):
        executor = MigrationExecutor(connection)
        destino = executor.loader.graph.leaf_nodes()
        origem = [
            ('empresas', '0009_politica_arredondamento_pontos'),
            ('fidelidade', '0002_lotepontos'),
        ]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(destino))
        executor.migrate(origem)
        antigos = executor.loader.project_state(origem).apps
        usuario = antigos.get_model('usuarios', 'Usuario').objects.create(
            cpf='52998224725',
            password='!',
        )
        empresa = antigos.get_model('empresas', 'Empresa').objects.create(
            nome='Empresa',
            slug='empresa',
            cnpj='11222333000181',
        )
        loja = antigos.get_model('empresas', 'Loja').objects.create(
            empresa_id=empresa.pk,
            nome='Centro',
            cidade='Araras',
        )
        membro = antigos.get_model('empresas', 'MembroEmpresa').objects.create(
            usuario_id=usuario.pk,
            empresa_id=empresa.pk,
            papel='ADMINISTRADOR',
            ativo=True,
        )
        cliente = antigos.get_model('clientes', 'Cliente').objects.create(
            usuario_id=usuario.pk,
            empresa_id=empresa.pk,
        )
        credencial = antigos.get_model('empresas', 'CredencialIntegracao').objects.create(
            empresa_id=empresa.pk,
            criada_por_id=membro.pk,
            nome='PDV',
            escopo='EMPRESA',
            identificador=secrets.token_urlsafe(18),
            segredo_hash='!',
            ativa=False,
        )
        agora = datetime(2026, 9, 23, 13, 30, tzinfo=datetime_timezone.utc)
        Compra = antigos.get_model('fidelidade', 'Compra')
        compra = Compra.objects.create(
            loja_id=loja.pk,
            cliente_id=cliente.pk,
            credencial_origem_id=credencial.pk,
            identificador_externo='F302',
            valor=Decimal('49.90'),
            ocorrida_em=agora,
        )
        legada = Compra.objects.create(
            loja_id=loja.pk,
            cliente_id=cliente.pk,
            credencial_origem_id=credencial.pk,
            identificador_externo='F301',
            valor=Decimal('20.00'),
            ocorrida_em=agora,
        )
        antigos.get_model('fidelidade', 'LotePontos').objects.create(
            compra_id=compra.pk,
            cliente_id=cliente.pk,
            pontos_base=Decimal('62.3750'),
            pontos_concedidos=Decimal('62.3800'),
            pontos_por_real_aplicado=Decimal('1.25'),
            precisao_pontos_aplicada=2,
            modo_arredondamento_aplicado='HALF_UP',
            validade_pontos_meses_aplicada=12,
            adquiridos_em=agora,
            expira_em=agora.replace(year=agora.year + 1),
        )
        antigos.get_model('empresas', 'ConfiguracaoFidelidadeEmpresa').objects.create(
            empresa_id=empresa.pk,
            pontos_por_real=Decimal('1.25'),
            precisao_pontos=2,
            modo_arredondamento_pontos='HALF_UP',
        )
        modelos = [
            ('usuarios', 'Usuario'),
            ('empresas', 'Empresa'),
            ('empresas', 'Loja'),
            ('empresas', 'MembroEmpresa'),
            ('clientes', 'Cliente'),
            ('empresas', 'CredencialIntegracao'),
            ('empresas', 'ConfiguracaoFidelidadeEmpresa'),
            ('fidelidade', 'Compra'),
            ('fidelidade', 'LotePontos'),
        ]
        antes = {m: list(antigos.get_model(*m).objects.order_by('pk').values()) for m in modelos}
        executor = MigrationExecutor(connection)
        executor.migrate(destino)
        atuais = executor.loader.project_state(destino).apps
        for modelo, registros in antes.items():
            self.assertEqual(
                list(
                    atuais.get_model(*modelo).objects.order_by('pk').values(
                        *registros[0],
                    ),
                ),
                registros,
            )
        lote = atuais.get_model('fidelidade', 'LotePontos').objects.get()
        self.assertEqual(lote.multiplicador_pontos_aplicado, Decimal('1.0000'))
        self.assertFalse(
            atuais.get_model('fidelidade', 'LotePontos').objects.filter(compra_id=legada.pk).exists(),
        )
        for nome in (
            'EventoFidelidade',
            'EventoLoja',
            'EfeitoEvento',
            'AplicacaoEfeitoEventoLote',
        ):
            self.assertFalse(
                atuais.get_model('fidelidade', nome).objects.exists(),
            )
