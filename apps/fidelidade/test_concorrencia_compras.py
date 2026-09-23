from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.db import close_old_connections, connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from .models import Compra, LotePontos
from .test_compras import DadosCompras


class ConcorrenciaCompraTests(DadosCompras, TransactionTestCase):
    def disputar(self, valores):
        barreira = Barrier(2)
        original = Compra.save

        def salvar_simultaneamente(compra, *args, **kwargs):
            # Ambos já consultaram a chave e chegaram ao INSERT: exercita a constraint real.
            barreira.wait(timeout=15)
            return original(compra, *args, **kwargs)

        def executar(valor):
            close_old_connections()
            try:
                resposta = APIClient().post("/api/v1/compras/", {
                    "loja_id": self.loja.pk, "identificador_externo": "CONCORRENTE",
                    "cliente_cpf": self.usuario.cpf, "valor": valor, "ocorrida_em": self.instante.isoformat(),
                }, format="json", HTTP_X_API_KEY=self.chave)
                return resposta.status_code, resposta.json()
            finally:
                connections.close_all()

        with patch.object(Compra, "save", salvar_simultaneamente), ThreadPoolExecutor(max_workers=2) as pool:
            futuros = [pool.submit(executar, valor) for valor in valores]
            return [futuro.result(timeout=45) for futuro in futuros]

    def test_requests_equivalentes_concorrem_para_uma_compra(self):
        respostas = self.disputar(["199.90", "199.90"])
        self.assertCountEqual([status for status, _ in respostas], [201, 200])
        self.assertEqual(Compra.objects.count(), 1)
        self.assertEqual(LotePontos.objects.count(), 1)
        self.assertEqual(LotePontos.objects.get().compra_id, Compra.objects.get().pk)
        self.assertEqual(respostas[0][1], respostas[1][1])

    def test_requests_divergentes_criam_uma_compra_e_um_conflito(self):
        respostas = self.disputar(["199.90", "200.00"])
        self.assertCountEqual([status for status, _ in respostas], [201, 409])
        self.assertEqual(Compra.objects.count(), 1)
        self.assertEqual(LotePontos.objects.count(), 1)
        self.assertEqual(LotePontos.objects.get().compra_id, Compra.objects.get().pk)
        for status, dados in respostas:
            if status == 201:
                self.assertEqual(str(Compra.objects.get().valor), dados["valor"])
                self.assertEqual(str(LotePontos.objects.get().pontos_base), dados["fidelidade"]["pontos_base"])
            else:
                self.assertEqual(dados, {"erro": {
                    "codigo": "idempotencia_conflitante",
                    "mensagem": "Identificador externo já utilizado com dados diferentes.",
                }})
