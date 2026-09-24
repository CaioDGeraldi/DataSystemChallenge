from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.state import ModelState
from django.test import TransactionTestCase

from .eventos import criar_evento
from .models import NivelFidelidade
from .test_resgates import DadosResgates


class MigracaoNiveisTests(DadosResgates, TransactionTestCase):
    def test_0004_0005_preserva_f301_a_f304_sem_niveis_implicitos(self):
        criar_evento(self.request(), nome='2x', escopo='EMPRESA',
            inicio_em=self.instante - timedelta(days=1), fim_em=self.instante + timedelta(days=1),
            efeitos=[{'tipo': 'MULTIPLICADOR_PONTOS', 'valor': Decimal('2.0000')}])
        self.lote()
        self.resgatar()
        self.model(identificador_externo='LEGADA').save()
        executor = MigrationExecutor(connection)
        destino = executor.loader.graph.leaf_nodes()
        origem = [('fidelidade', '0004_resgate_alocacaoresgate')]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(destino))
        executor.migrate(origem)
        antigos = executor.loader.project_state(origem).apps
        modelos = [('usuarios', 'Usuario'), ('empresas', 'Empresa'), ('empresas', 'Loja'),
            ('empresas', 'MembroEmpresa'), ('clientes', 'Cliente'), ('empresas', 'CredencialIntegracao'),
            ('empresas', 'ConfiguracaoFidelidadeEmpresa'), ('fidelidade', 'Compra'), ('fidelidade', 'LotePontos'),
            ('fidelidade', 'EventoFidelidade'), ('fidelidade', 'EfeitoEvento'), ('fidelidade', 'AplicacaoEfeitoEventoLote'),
            ('fidelidade', 'Resgate'), ('fidelidade', 'AlocacaoResgate')]
        antes = {m: list(antigos.get_model(*m).objects.order_by('pk').values()) for m in modelos}
        campos_cliente = {f.name for f in antigos.get_model('clientes', 'Cliente')._meta.fields}
        executor = MigrationExecutor(connection)
        executor.migrate(destino)
        estado = executor.loader.project_state(destino)
        atuais = estado.apps
        for modelo, registros in antes.items():
            with self.subTest(modelo=modelo):
                self.assertEqual(list(atuais.get_model(*modelo).objects.order_by('pk').values()), registros)
        self.assertFalse(atuais.get_model('fidelidade', 'NivelFidelidade').objects.exists())
        self.assertEqual({f.name for f in atuais.get_model('clientes', 'Cliente')._meta.fields}, campos_cliente)
        real = ModelState.from_model(NivelFidelidade)
        migrado = estado.models[('fidelidade', 'nivelfidelidade')]
        self.assertEqual(set(real.fields), set(migrado.fields))
        for nome in real.fields:
            self.assertEqual(real.fields[nome].deconstruct(), migrado.fields[nome].deconstruct())
        self.assertEqual(real.options['constraints'], migrado.options['constraints'])
        self.assertEqual(real.options['ordering'], migrado.options['ordering'])
