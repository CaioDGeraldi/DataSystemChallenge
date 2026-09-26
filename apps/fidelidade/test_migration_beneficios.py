from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from .test_resgates import DadosResgates


class MigracaoBeneficiosTests(DadosResgates, TransactionTestCase):
    def test_incremental_preserva_lote_legado_e_defaults_neutros(self):
        lote = self.lote()
        executor = MigrationExecutor(connection)
        destino = executor.loader.graph.leaf_nodes()
        origem = [
            ('empresas', '0009_politica_arredondamento_pontos'),
            ('fidelidade', '0005_nivelfidelidade'),
        ]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(destino))
        executor.migrate(origem)
        antigos = executor.loader.project_state(origem).apps
        antes = antigos.get_model('fidelidade', 'LotePontos').objects.values().get(
            pk=lote.pk,
        )
        executor = MigrationExecutor(connection)
        executor.migrate(destino)
        atuais = executor.loader.project_state(destino).apps
        novo = atuais.get_model('fidelidade', 'LotePontos').objects.get(pk=lote.pk)
        self.assertIsNone(novo.beneficios_aplicados)
        for campo, valor in antes.items():
            self.assertEqual(getattr(novo, campo), valor)
        cfg = atuais.get_model('empresas', 'ConfiguracaoFidelidadeEmpresa').objects.get(
            empresa_id=self.empresa.pk,
        )
        self.assertFalse(cfg.promocao_retorno_ativa)
        self.assertFalse(cfg.inatividade_suspende_beneficios_nivel)
        self.assertEqual(cfg.base_calculo_pontos, 'BRUTO')
        self.assertEqual(cfg.bonus_pontos_retorno_percentual, 0)
