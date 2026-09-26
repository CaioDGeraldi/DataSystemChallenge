from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.fidelidade.models import AlocacaoResgate, Compra, LotePontos, Resgate
from apps.fidelidade.niveis import criar_nivel
from apps.fidelidade.test_resgates import DadosResgates


class ConsultaFidelidadeHTTPTests(DadosResgates, TestCase):
    def setUp(self):
        super().setUp()
        self.agora = self.instante + timedelta(days=3)

    def consultar(self, *, chave=None, loja_id=None, cliente_cpf=None):
        with patch(
            "apps.fidelidade.consultas.timezone.now",
            return_value=self.agora,
        ):
            return APIClient(enforce_csrf_checks=True).get(
                "/api/v1/clientes/fidelidade/",
                {
                    "loja_id": self.loja.pk if loja_id is None else loja_id,
                    "cliente_cpf": (
                        self.usuario.cpf
                        if cliente_cpf is None
                        else cliente_cpf
                    ),
                },
                HTTP_X_API_KEY=self.chave if chave is None else chave,
            )

    def assert_erro(self, resposta, status, codigo):
        self.assertEqual(resposta.status_code, status)
        self.assertEqual(set(resposta.json()), {"erro"})
        self.assertEqual(resposta.json()["erro"]["codigo"], codigo)

    def test_contrato_cliente_ativo_nivel_saldo_e_sem_escrita(self):
        criar_nivel(
            self.request(),
            nome="Inicial",
            pontos_minimos=Decimal("0"),
            bonus_pontos_percentual=Decimal("20"),
            desconto_percentual=Decimal("5"),
        )
        self.lote(
            "200.00",
            ocorrida_em=self.agora - timedelta(days=1),
        )

        antes = {
            "compras": Compra.objects.count(),
            "lotes": LotePontos.objects.count(),
            "resgates": Resgate.objects.count(),
            "alocacoes": AlocacaoResgate.objects.count(),
        }

        resposta = self.consultar()

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("no-store", resposta["Cache-Control"])

        dados = resposta.json()
        self.assertEqual(
            set(dados),
            {
                "cliente",
                "atividade",
                "nivel",
                "saldo",
                "promocao_retorno",
                "resgate",
            },
        )
        self.assertEqual(
            dados["cliente"],
            {
                "cpf": self.usuario.cpf,
                "nome": "Ana Silva",
            },
        )
        self.assertTrue(dados["atividade"]["ativo"])
        self.assertIsNotNone(dados["atividade"]["ultima_compra_em"])
        self.assertEqual(
            dados["atividade"]["periodo_cliente_ativo_dias"],
            180,
        )

        self.assertEqual(dados["nivel"]["pontos_historicos"], "240.0000")
        self.assertEqual(dados["nivel"]["atual"]["nome"], "Inicial")
        self.assertEqual(
            dados["nivel"]["atual"]["pontos_minimos"],
            "0.0000",
        )
        self.assertEqual(
            dados["nivel"]["atual"]["beneficios"],
            {
                "bonus_pontos_percentual": "20.0000",
                "desconto_percentual": "5.0000",
                "aplicaveis": True,
            },
        )

        self.assertEqual(dados["saldo"]["pontos"], "240.0000")
        self.assertEqual(
            dados["promocao_retorno"],
            {
                "aplicavel": False,
                "bonus_pontos_percentual": "0.0000",
                "desconto_percentual": "0.0000",
            },
        )
        self.assertEqual(
            dados["resgate"],
            {
                "minimo_pontos": 100,
                "incremento_pontos": 50,
                "valor_monetario_por_ponto": "0.05",
            },
        )

        depois = {
            "compras": Compra.objects.count(),
            "lotes": LotePontos.objects.count(),
            "resgates": Resgate.objects.count(),
            "alocacoes": AlocacaoResgate.objects.count(),
        }
        self.assertEqual(depois, antes)

    def test_sem_compra_nao_e_retorno_e_mantem_beneficio_normal(self):
        criar_nivel(
            self.request(),
            nome="Inicial",
            pontos_minimos=Decimal("0"),
            bonus_pontos_percentual=Decimal("20"),
            desconto_percentual=Decimal("5"),
        )
        self.configurar(
            promocao_retorno_ativa=True,
            bonus_pontos_retorno_percentual=Decimal("30"),
            desconto_retorno_percentual=Decimal("10"),
            inatividade_suspende_beneficios_nivel=True,
        )

        dados = self.consultar().json()

        self.assertFalse(dados["atividade"]["ativo"])
        self.assertIsNone(dados["atividade"]["ultima_compra_em"])
        self.assertEqual(dados["nivel"]["pontos_historicos"], "0.0000")
        self.assertEqual(dados["saldo"]["pontos"], "0.0000")
        self.assertEqual(dados["nivel"]["atual"]["nome"], "Inicial")
        self.assertTrue(
            dados["nivel"]["atual"]["beneficios"]["aplicaveis"],
        )
        self.assertEqual(
            dados["promocao_retorno"],
            {
                "aplicavel": False,
                "bonus_pontos_percentual": "0.0000",
                "desconto_percentual": "0.0000",
            },
        )

    def test_inatividade_suspensao_politica_de_retorno_e_promocao(self):
        criar_nivel(
            self.request(),
            nome="Inicial",
            pontos_minimos=Decimal("0"),
            bonus_pontos_percentual=Decimal("20"),
            desconto_percentual=Decimal("5"),
        )
        self.lote(
            "100.00",
            ocorrida_em=self.agora - timedelta(days=181),
        )
        self.configurar(
            periodo_cliente_ativo_dias=180,
            inatividade_suspende_beneficios_nivel=True,
            beneficio_primeira_compra_apos_inatividade=(
                "SEM_BENEFICIOS_NIVEL"
            ),
            promocao_retorno_ativa=True,
            bonus_pontos_retorno_percentual=Decimal("30"),
            desconto_retorno_percentual=Decimal("10"),
        )

        dados = self.consultar().json()

        self.assertFalse(dados["atividade"]["ativo"])
        self.assertFalse(
            dados["nivel"]["atual"]["beneficios"]["aplicaveis"],
        )
        self.assertEqual(
            dados["promocao_retorno"],
            {
                "aplicavel": True,
                "bonus_pontos_percentual": "30.0000",
                "desconto_percentual": "10.0000",
            },
        )

        self.configurar(
            beneficio_primeira_compra_apos_inatividade=(
                "COM_BENEFICIOS_NIVEL"
            ),
        )
        dados = self.consultar().json()

        self.assertTrue(
            dados["nivel"]["atual"]["beneficios"]["aplicaveis"],
        )
        self.assertTrue(dados["promocao_retorno"]["aplicavel"])

    def test_saldo_exclui_expirados_e_desconta_resgate_sem_reduzir_nivel(self):
        self.lote(
            "100.00",
            ocorrida_em=self.agora - timedelta(days=400),
        )
        self.lote(
            "300.00",
            ocorrida_em=self.agora - timedelta(days=10),
        )

        self.resgatar(pontos=100)

        dados = self.consultar().json()

        self.assertEqual(dados["nivel"]["pontos_historicos"], "400.0000")
        self.assertIsNone(dados["nivel"]["atual"])
        self.assertEqual(dados["saldo"]["pontos"], "200.0000")

    def test_escopo_loja_tenant_autenticacao_e_validacao(self):
        _, chave_restrita = self.emitir("LOJAS", [self.loja])

        for loja_id in (
            self.segunda.pk,
            self.externa.pk,
            999999,
        ):
            with self.subTest(loja_id=loja_id):
                self.assert_erro(
                    self.consultar(
                        chave=chave_restrita,
                        loja_id=loja_id,
                    ),
                    403,
                    "loja_fora_do_escopo",
                )

        inexistente = self.consultar(cliente_cpf="39053344705")
        outro_tenant = self.consultar(
            cliente_cpf=self.sem_vinculo.cpf,
        )

        self.assert_erro(
            inexistente,
            404,
            "cliente_nao_encontrado",
        )
        self.assertEqual(outro_tenant.json(), inexistente.json())

        sem_chave = APIClient().get(
            "/api/v1/clientes/fidelidade/",
            {
                "loja_id": self.loja.pk,
                "cliente_cpf": self.usuario.cpf,
            },
        )
        self.assert_erro(
            sem_chave,
            401,
            "credencial_invalida",
        )

        for parametros in (
            {"cliente_cpf": self.usuario.cpf},
            {"loja_id": self.loja.pk},
            {
                "loja_id": self.loja.pk,
                "cliente_cpf": "abc",
            },
            {
                "loja_id": "invalida",
                "cliente_cpf": self.usuario.cpf,
            },
        ):
            with self.subTest(parametros=parametros):
                resposta = APIClient().get(
                    "/api/v1/clientes/fidelidade/",
                    parametros,
                    HTTP_X_API_KEY=self.chave,
                )
                self.assert_erro(
                    resposta,
                    400,
                    "requisicao_invalida",
                )

    def test_metodos_de_escrita_nao_sao_aceitos(self):
        caminho = (
            "/api/v1/clientes/fidelidade/"
            f"?loja_id={self.loja.pk}"
            f"&cliente_cpf={self.usuario.cpf}"
        )

        for metodo in ("post", "put", "patch", "delete"):
            with self.subTest(metodo=metodo):
                resposta = getattr(APIClient(), metodo)(
                    caminho,
                    {},
                    format="json",
                    HTTP_X_API_KEY=self.chave,
                )
                self.assert_erro(
                    resposta,
                    405,
                    "metodo_nao_permitido",
                )
