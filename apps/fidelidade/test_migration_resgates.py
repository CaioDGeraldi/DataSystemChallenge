from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.state import ModelState
from django.test import TransactionTestCase

from .eventos import criar_evento
from .models import AlocacaoResgate, Resgate
from .test_resgates import DadosResgates


class MigracaoResgatesTests(DadosResgates, TransactionTestCase):
    def test_0003_0004_preserva_compras_lotes_campanhas_e_configuracao_sem_backfill(self):
        criar_evento(self.request(), nome='Campanha preservada', escopo='LOJAS', lojas=[self.loja],
            inicio_em=self.instante - timedelta(days=1), fim_em=self.instante + timedelta(days=1),
            efeitos=[{'tipo': 'MULTIPLICADOR_PONTOS', 'valor': Decimal('2.0000')}])
        lote = self.lote()
        legada = self.model(identificador_externo='LEGADA')
        legada.save()
        executor = MigrationExecutor(connection)
        destino = executor.loader.graph.leaf_nodes()
        origem = [('fidelidade', '0003_eventos_fidelidade')]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(destino))
        executor.migrate(origem)
        antigos = executor.loader.project_state(origem).apps
        modelos = [('usuarios', 'Usuario'), ('empresas', 'Empresa'), ('empresas', 'Loja'),
            ('empresas', 'MembroEmpresa'), ('clientes', 'Cliente'), ('empresas', 'CredencialIntegracao'),
            ('empresas', 'ConfiguracaoFidelidadeEmpresa'), ('fidelidade', 'Compra'), ('fidelidade', 'LotePontos'),
            ('fidelidade', 'EventoFidelidade'), ('fidelidade', 'EventoLoja'), ('fidelidade', 'EfeitoEvento'),
            ('fidelidade', 'AplicacaoEfeitoEventoLote')]
        antes = {m: list(antigos.get_model(*m).objects.order_by('pk').values()) for m in modelos}
        executor = MigrationExecutor(connection)
        executor.migrate(destino)
        estado = executor.loader.project_state(destino)
        atuais = estado.apps
        for modelo, registros in antes.items():
            with self.subTest(modelo=modelo):
                self.assertEqual(list(atuais.get_model(*modelo).objects.order_by('pk').values()), registros)
        Lote = atuais.get_model('fidelidade', 'LotePontos')
        self.assertEqual(Lote.objects.get(pk=lote.pk).pontos_concedidos, Decimal('200'))
        self.assertFalse(Lote.objects.filter(compra_id=legada.pk).exists())
        for modelo in (Resgate, AlocacaoResgate):
            self.assertFalse(atuais.get_model('fidelidade', modelo.__name__).objects.exists())
            real = ModelState.from_model(modelo)
            migrado = estado.models[('fidelidade', modelo._meta.model_name)]
            self.assertEqual(set(real.fields), set(migrado.fields))
            for nome in real.fields:
                self.assertEqual(real.fields[nome].deconstruct(), migrado.fields[nome].deconstruct())
            self.assertEqual(real.options['constraints'], migrado.options['constraints'])
