from copy import deepcopy
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from .test_resgates import DadosResgates


class MigracaoCompraResgateTests(DadosResgates, TransactionTestCase):
    def test_preserva_historico_sem_backfill_e_adiciona_default(self):
        lote = self.lote()
        self.resgatar()
        executor = MigrationExecutor(connection)
        destino = executor.loader.graph.leaf_nodes()
        origem = [('empresas', '0011_configuracaofidelidadeempresa_devolver_pontos_ao_estornar_resgate'),
                  ('fidelidade', '0007_estornoresgate')]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(destino))
        executor.migrate(origem)
        apps = executor.loader.project_state(origem).apps
        antigo = deepcopy(lote.beneficios_aplicados)
        antigo['versao'] = 1
        antigo.pop('desconto_resgate')
        antigo['politica'].pop('limite_resgate_percentual')
        apps.get_model('fidelidade', 'LotePontos').objects.filter(pk=lote.pk).update(beneficios_aplicados=antigo)
        modelos = [('fidelidade', nome) for nome in ('Compra', 'LotePontos', 'Resgate', 'AlocacaoResgate')]
        antes = {m: list(apps.get_model(*m).objects.order_by('pk').values()) for m in modelos}
        executor = MigrationExecutor(connection)
        executor.migrate(destino)
        novos = executor.loader.project_state(destino).apps
        for modelo, registros in antes.items():
            campos = [f.attname for f in apps.get_model(*modelo)._meta.fields]
            self.assertEqual(list(novos.get_model(*modelo).objects.order_by('pk').values(*campos)), registros)
        self.assertIsNone(novos.get_model('fidelidade', 'Compra').objects.get().resgate_id)
        self.assertEqual(novos.get_model('empresas', 'ConfiguracaoFidelidadeEmpresa').objects.get().limite_resgate_percentual, Decimal('100.0000'))
