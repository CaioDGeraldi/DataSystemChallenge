from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

from django.db import close_old_connections, connections
from django.test import TransactionTestCase

from .test_resgates import DadosResgates
from .services import registrar_compra


class ConcorrenciaBeneficiosTests(DadosResgates, TransactionTestCase):
    def test_duas_compras_no_retorno_somente_uma_recebe_promocao(self):
        self.lote(ocorrida_em=self.instante - timedelta(days=181))
        self.configurar(
            promocao_retorno_ativa=True,
            bonus_pontos_retorno_percentual=Decimal('30'),
        )
        barreira = Barrier(2)

        def executar(chave):
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                compra, _ = registrar_compra(
                    **self.dados(
                        identificador_externo=chave,
                        valor=Decimal('100.00'),
                    ),
                )
                return (
                    compra.lote_pontos.beneficios_aplicados['resultado']
                    ['retorno']
                )
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futuros = [pool.submit(executar, str(i)) for i in range(2)]
            self.assertCountEqual(
                [f.result(timeout=30) for f in futuros],
                [True, False],
            )
