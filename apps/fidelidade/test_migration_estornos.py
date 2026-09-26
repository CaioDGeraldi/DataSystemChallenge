from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.state import ModelState
from django.test import TransactionTestCase

from apps.empresas.models import ConfiguracaoFidelidadeEmpresa
from .models import EstornoResgate
from .test_resgates import DadosResgates


class MigracaoEstornosTests(DadosResgates, TransactionTestCase):
    def test_preserva_historico_configuracao_existente_default_true_sem_estornos(self):
        self.lote()
        self.resgatar()
        executor = MigrationExecutor(connection)
        destino = executor.loader.graph.leaf_nodes()
        origem = [('empresas', '0010_beneficios_fidelidade'), ('fidelidade', '0006_beneficios_fidelidade')]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(destino))
        executor.migrate(origem)
        antigos = executor.loader.project_state(origem).apps
        modelos = [('empresas', 'ConfiguracaoFidelidadeEmpresa'), ('fidelidade', 'Resgate'),
                   ('fidelidade', 'AlocacaoResgate'), ('fidelidade', 'LotePontos')]
        antes = {m: list(antigos.get_model(*m).objects.order_by('pk').values()) for m in modelos}
        executor = MigrationExecutor(connection)
        executor.migrate(destino)
        estado = executor.loader.project_state(destino)
        for modelo, registros in antes.items():
            campos = [f.attname for f in antigos.get_model(*modelo)._meta.fields]
            self.assertEqual(list(estado.apps.get_model(*modelo).objects.order_by('pk').values(*campos)), registros)
        self.assertIs(ConfiguracaoFidelidadeEmpresa.objects.get(empresa=self.empresa).devolver_pontos_ao_estornar_resgate, True)
        self.assertFalse(EstornoResgate.objects.exists())
        real = ModelState.from_model(EstornoResgate)
        migrado = estado.models[('fidelidade', 'estornoresgate')]
        for nome in real.fields:
            self.assertEqual(real.fields[nome].deconstruct(), migrado.fields[nome].deconstruct())
        self.assertEqual(real.options['constraints'], migrado.options['constraints'])
