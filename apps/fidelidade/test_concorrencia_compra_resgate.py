from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase

from .estornos import estornar_resgate
from .exceptions import ResgateJaEstornado, ResgateVinculadoCompra
from .models import Compra, EstornoResgate
from .test_resgates import DadosResgates


class ConcorrenciaCompraResgateTests(DadosResgates, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.lote('1000')
        self.resgate, _ = self.resgatar()

    def disputar(self, *, estorno=False, retry=False):
        barreira = Barrier(2)

        def executar(indice):
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '10s'")
                        cursor.execute("SET LOCAL statement_timeout = '20s'")
                        cursor.execute('SELECT pg_backend_pid()')
                        pid = cursor.fetchone()[0]
                    barreira.wait(timeout=15)
                    try:
                        with transaction.atomic():
                            if estorno and indice:
                                _, criado = estornar_resgate(
                                    credencial=self.credencial, loja_id=self.loja.pk,
                                    resgate_identificador_externo='RESGATE-001', identificador_externo='E1',
                                )
                            else:
                                _, criado = self.registrar(
                                    identificador_externo='C0' if retry else f'C{indice}',
                                    valor=Decimal('100'), resgate_identificador_externo='RESGATE-001',
                                )
                        return pid, 'criado' if criado else 'retry'
                    except (ResgateJaEstornado, ResgateVinculadoCompra) as exc:
                        return pid, type(exc).__name__
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futuros = [pool.submit(executar, i) for i in range(2)]
            respostas = [f.result(timeout=45) for f in futuros]
        self.assertEqual(len({pid for pid, _ in respostas}), 2)
        self.assert_invariantes()
        return [resultado for _, resultado in respostas]

    def test_duas_compras_um_resgate(self):
        self.assertCountEqual(self.disputar(), ['criado', 'ResgateVinculadoCompra'])
        self.assertEqual(Compra.objects.filter(resgate=self.resgate).count(), 1)

    def test_retry_concorrente_preserva_vinculo(self):
        self.assertCountEqual(self.disputar(retry=True), ['criado', 'retry'])
        self.assertEqual(Compra.objects.filter(resgate=self.resgate).count(), 1)

    def test_compra_e_estorno_serializam_sem_estado_duplo(self):
        resultados = self.disputar(estorno=True)
        self.assertEqual(resultados.count('criado'), 1)
        compras = Compra.objects.filter(resgate=self.resgate).count()
        estornos = EstornoResgate.objects.filter(resgate=self.resgate).count()
        self.assertEqual(compras + estornos, 1)
        self.assertIn('ResgateVinculadoCompra' if compras else 'ResgateJaEstornado', resultados)
