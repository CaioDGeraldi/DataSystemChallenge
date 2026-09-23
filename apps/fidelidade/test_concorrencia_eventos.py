from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import TransactionTestCase

from . import test_concorrencia_compras as compras_concorrentes
from .eventos import criar_evento
from .models import AplicacaoEfeitoEventoLote, EventoFidelidade
from .test_eventos import DadosEventos


class ConcorrenciaCriacaoEventoTests(DadosEventos, TransactionTestCase):
    def test_criacao_concorrente_empresa_loja_tem_um_vencedor(self):
        barreira = Barrier(2)

        def executar(escopo):
            close_old_connections()
            try:
                barreira.wait(timeout=15)
                try:
                    self.evento(escopo=escopo, lojas=[self.loja] if escopo == 'LOJAS' else [])
                except ValidationError:
                    return 'conflito'
                return 'criado'
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futuros = [pool.submit(executar, escopo) for escopo in ('EMPRESA', 'LOJAS')]
            self.assertCountEqual([f.result(timeout=45) for f in futuros], ['criado', 'conflito'])
        self.assertEqual(EventoFidelidade.objects.count(), 1)
        self.assertEqual(EventoFidelidade.objects.get().efeitos.count(), 1)


class ConcorrenciaCompraEventoTests(compras_concorrentes.ConcorrenciaCompraTests):
    def setUp(self):
        super().setUp()
        criar_evento(self.request(), nome='Campanha', inicio_em=self.instante - timedelta(days=1),
                     fim_em=self.instante + timedelta(days=1), escopo='EMPRESA',
                     efeitos=[{'tipo': 'MULTIPLICADOR_PONTOS', 'valor': Decimal('2.0000')}])

    def disputar(self, valores):
        respostas = super().disputar(valores)
        self.assertEqual(AplicacaoEfeitoEventoLote.objects.count(), 1)
        aplicacao = AplicacaoEfeitoEventoLote.objects.select_related('lote__compra').get()
        self.assertEqual(aplicacao.lote.pontos_concedidos, aplicacao.lote.compra.valor * Decimal('2'))
        return respostas
