from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier, local
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase

from . import niveis
from .models import NivelFidelidade
from .test_niveis import DadosNiveis


class ConcorrenciaNivelTests(DadosNiveis, TransactionTestCase):
    def disputar(self, operacoes, empresas_distintas=False):
        self.assertEqual(connection.vendor, 'postgresql')
        barreira, depois_lock = Barrier(2), Barrier(2)
        worker = local()
        travar = niveis._travar_configuracao

        def sincronizar(request):
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '10s'")
                cursor.execute('SELECT pg_backend_pid()')
                worker.pid = cursor.fetchone()[0]
            barreira.wait(timeout=15)
            empresa = travar(request)
            if empresas_distintas:
                depois_lock.wait(timeout=15)  # Empresas distintas não bloqueiam entre si.
            return empresa

        def executar(operacao):
            close_old_connections()
            try:
                try:
                    operacao()
                except ValidationError:
                    return 'invalido', worker.pid
                return 'ok', worker.pid
            finally:
                connections.close_all()

        with patch('apps.fidelidade.niveis._travar_configuracao', sincronizar), ThreadPoolExecutor(max_workers=2) as pool:
            futuros = [pool.submit(executar, op) for op in operacoes]
            resultados = [f.result(timeout=45) for f in futuros]
        self.assertEqual(len({pid for _, pid in resultados}), 2)
        for empresa in (self.empresa, self.outra):
            limites = list(NivelFidelidade.objects.filter(empresa=empresa).values_list('pontos_minimos', flat=True))
            self.assertEqual(len(limites), len(set(limites)))
            if limites:
                self.assertEqual(min(limites), Decimal('0'))
        return [estado for estado, _ in resultados]

    def test_primeira_criacao_concorrente_um_zero(self):
        self.assertCountEqual(self.disputar([lambda: self.nivel('A'), lambda: self.nivel('B')]), ['ok', 'invalido'])
        self.assertEqual(NivelFidelidade.objects.count(), 1)

    def test_edicoes_concorrentes_nao_duplicam_threshold(self):
        zero, a, b = self.faixas()
        self.assertCountEqual(self.disputar([
            lambda: niveis.editar_nivel(self.request(), a.pk, nome='A', pontos_minimos=Decimal('2000')),
            lambda: niveis.editar_nivel(self.request(), b.pk, nome='B', pontos_minimos=Decimal('2000')),
        ]), ['ok', 'invalido'])
        self.assertEqual(NivelFidelidade.objects.count(), 3)

    def test_excluir_zero_e_criar_positivo_nao_deixam_configuracao_invalida(self):
        zero = self.nivel()
        self.assertCountEqual(self.disputar([
            lambda: niveis.excluir_nivel(self.request(), zero.pk), lambda: self.nivel('Novo', '100'),
        ]), ['ok', 'invalido'])

    def test_exclusoes_simultaneas_preservam_zero_ou_configuracao_vazia(self):
        zero = self.nivel()
        alto = self.nivel('Alto', '100')
        resultados = self.disputar([lambda: niveis.excluir_nivel(self.request(), zero.pk),
                                   lambda: niveis.excluir_nivel(self.request(), alto.pk)])
        self.assertIn('ok', resultados)
        self.assertFalse(NivelFidelidade.objects.filter(pontos_minimos__gt=0).exists())

    def test_mover_zero_concorrente_com_criacao_nao_remove_inicio(self):
        zero = self.nivel()
        self.assertCountEqual(self.disputar([
            lambda: niveis.editar_nivel(self.request(), zero.pk, nome='Movido', pontos_minimos=Decimal('10')),
            lambda: self.nivel('Novo', '100'),
        ]), ['invalido', 'ok'])
        self.assertEqual(NivelFidelidade.objects.count(), 2)

    def test_empresas_distintas_permitem_mesmo_threshold_sem_serializacao_global(self):
        self.assertEqual(self.disputar([lambda: self.nivel(),
            lambda: self.nivel(request=self.request(self.outro_membro))], empresas_distintas=True), ['ok', 'ok'])

    def test_ordem_de_locks_empresa_antes_de_membro(self):
        consultas = []

        def observar(execute, sql, params, many, context):
            if 'FOR UPDATE' in sql or 'FOR NO KEY UPDATE' in sql:
                consultas.append(sql)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(observar):
            self.nivel()
        self.assertEqual(len(consultas), 2)
        self.assertIn('empresas_empresa', consultas[0])
        self.assertIn('FOR NO KEY UPDATE', consultas[0])
        self.assertIn('empresas_membroempresa', consultas[1])
