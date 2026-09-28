from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.fidelidade.seed_fatecalcados import POLITICA
from .forms import ConfiguracaoFidelidadeEmpresaForm, OverrideFidelidadeLojaForm
from .models import ConfiguracaoFidelidadeEmpresa, OverrideFidelidadeLoja
from .services import resolver_configuracao, salvar_configuracao_empresa, salvar_override_loja
from .test_parametros import DadosParametros


class ConfiguracaoRecompraTests(DadosParametros, TestCase):
    def test_default_model_produto_seed_e_sem_override(self):
        self.assertEqual(resolver_configuracao(self.empresa).periodo_recompra_dias, 180)
        self.assertEqual(ConfiguracaoFidelidadeEmpresa(empresa=self.empresa).periodo_recompra_dias, 180)
        self.assertEqual(POLITICA['periodo_recompra_dias'], 180)
        self.salvar(periodo_recompra_dias=90)
        salvar_override_loja(self.request(), self.loja.pk, pontos_por_real=Decimal('2'))
        self.assertEqual(resolver_configuracao(self.empresa, self.loja).periodo_recompra_dias, 90)
        self.assertNotIn('periodo_recompra_dias', [f.name for f in OverrideFidelidadeLoja._meta.fields])
        self.assertNotIn('periodo_recompra_dias', OverrideFidelidadeLojaForm().fields)
        valores = self.valores()
        valores.pop('periodo_recompra_dias')
        salvar_configuracao_empresa(self.request(), **valores)
        self.assertEqual(resolver_configuracao(self.empresa).periodo_recompra_dias, 90)

    def test_inteiro_estritamente_positivo_e_constraint(self):
        for valor in (0, -1, True, 1.5, '180', Decimal('180')):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                self.salvar(periodo_recompra_dias=valor)
        self.salvar(periodo_recompra_dias=1)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ConfiguracaoFidelidadeEmpresa.objects.filter(empresa=self.empresa).update(periodo_recompra_dias=0)
        for valor in ('0', '-1', '1.5', ''):
            form = ConfiguracaoFidelidadeEmpresaForm(data=self.valores(periodo_recompra_dias=valor))
            self.assertFalse(form.is_valid())
            self.assertIn('periodo_recompra_dias', form.errors)

    def test_http_administrador_edita_gestor_nao_edita(self):
        self.autenticar()
        url = reverse('empresas:configuracao_empresa')
        self.assertContains(self.client.get(url), 'Período de recompra (dias)')
        resposta = self.client.post(url, self.valores(periodo_recompra_dias=75))
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(resolver_configuracao(self.empresa).periodo_recompra_dias, 75)
        self.membro.papel = 'GESTOR'
        self.membro.save()
        self.assertEqual(self.client.post(url, self.valores(periodo_recompra_dias=10)).status_code, 403)
        with self.assertRaises(PermissionDenied):
            self.salvar(periodo_recompra_dias=10)
        self.assertEqual(resolver_configuracao(self.empresa).periodo_recompra_dias, 75)


class MigracaoRecompraTests(TransactionTestCase):
    def test_migration_preserva_configuracao_existente_com_default_180(self):
        executor = MigrationExecutor(connection)
        destino = executor.loader.graph.leaf_nodes()
        origem = [('empresas', '0012_configuracaofidelidadeempresa_limite_resgate_percentual_and_more')]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(destino))
        executor.migrate(origem)
        anteriores = executor.loader.project_state(origem).apps
        empresa = anteriores.get_model('empresas', 'Empresa').objects.create(
            nome='Existente', slug='existente', cnpj='11222333000181',
        )
        config = anteriores.get_model('empresas', 'ConfiguracaoFidelidadeEmpresa').objects.create(
            empresa_id=empresa.pk, periodo_cliente_ativo_dias=60,
        )
        executor = MigrationExecutor(connection)
        executor.migrate(destino)
        atuais = executor.loader.project_state(destino).apps
        migrada = atuais.get_model('empresas', 'ConfiguracaoFidelidadeEmpresa').objects.get(pk=config.pk)
        self.assertEqual(migrada.periodo_recompra_dias, 180)
        self.assertEqual(migrada.periodo_cliente_ativo_dias, 60)
