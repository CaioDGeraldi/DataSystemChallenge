from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.fidelidade.eventos import criar_evento
from apps.fidelidade.models import (
    AlocacaoResgate,
    AplicacaoEfeitoEventoLote,
    Compra,
    LotePontos,
    Resgate,
)
from apps.fidelidade.niveis import criar_nivel
from apps.fidelidade.services import registrar_compra
from apps.fidelidade.test_resgates import DadosResgates


class SimulacaoCompraHTTPTests(DadosResgates, TestCase):
    def setUp(self):
        super().setUp()
        self.agora = self.instante + timedelta(days=3)

    def simular(
        self,
        *,
        chave=None,
        loja_id=None,
        cliente_cpf=None,
        valor="100.00",
        extras=None,
    ):
        payload = {
            "loja_id": self.loja.pk if loja_id is None else loja_id,
            "cliente_cpf": (
                self.usuario.cpf
                if cliente_cpf is None
                else cliente_cpf
            ),
            "valor": valor,
        }
        if extras:
            payload.update(extras)

        with patch(
            "apps.fidelidade.simulacoes.timezone.now",
            return_value=self.agora,
        ):
            return APIClient(enforce_csrf_checks=True).post(
                "/api/v1/compras/simular/",
                payload,
                format="json",
                HTTP_X_API_KEY=self.chave if chave is None else chave,
            )

    def assert_erro(self, resposta, status, codigo):
        self.assertEqual(resposta.status_code, status)
        self.assertEqual(set(resposta.json()), {"erro"})
        self.assertEqual(resposta.json()["erro"]["codigo"], codigo)

    def contagens_dominio(self):
        return {
            "compras": Compra.objects.count(),
            "lotes": LotePontos.objects.count(),
            "aplicacoes": AplicacaoEfeitoEventoLote.objects.count(),
            "resgates": Resgate.objects.count(),
            "alocacoes": AlocacaoResgate.objects.count(),
        }

    def test_primeira_compra_sem_campanha_e_sem_persistencia(self):
        criar_nivel(
            self.request(),
            nome="Inicial",
            pontos_minimos=Decimal("0"),
            bonus_pontos_percentual=Decimal("10"),
            desconto_percentual=Decimal("5"),
        )
        self.configurar(
            base_calculo_pontos="BRUTO",
            modo_aplicacao_nivel="ANTES_DA_COMPRA",
            modo_combinacao_descontos_percentuais="ADITIVO",
            inatividade_suspende_beneficios_nivel=True,
            promocao_retorno_ativa=False,
        )

        antes = self.contagens_dominio()

        resposta = self.simular(valor="100.00")

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("no-store", resposta["Cache-Control"])

        dados = resposta.json()

        self.assertEqual(
            set(dados),
            {
                "cliente",
                "simulada_em",
                "saldo",
                "resgate",
                "atividade",
                "nivel",
                "campanha",
                "promocao_retorno",
                "valores",
                "pontos",
            },
        )
        self.assertEqual(
            dados["cliente"],
            {
                "cpf": self.usuario.cpf,
                "nome": "Ana Silva",
            },
        )
        self.assertFalse(dados["atividade"]["ativo"])
        self.assertFalse(dados["atividade"]["retorno"])
        self.assertIsNone(dados["atividade"]["ultima_compra_em"])

        self.assertEqual(dados["nivel"]["atual"]["nome"], "Inicial")
        self.assertEqual(
            dados["nivel"]["bonus_pontos"]["nome"],
            "Inicial",
        )
        self.assertTrue(dados["nivel"]["beneficios_aplicaveis"])
        self.assertEqual(
            dados["nivel"]["bonus_pontos_percentual"],
            "10.0000",
        )
        self.assertEqual(
            dados["nivel"]["desconto_percentual"],
            "5.0000",
        )

        self.assertEqual(
            dados["campanha"],
            {
                "aplicavel": False,
                "nome": None,
                "multiplicador_pontos": "1.0000",
            },
        )
        self.assertFalse(dados["promocao_retorno"]["aplicavel"])

        self.assertEqual(
            dados["valores"],
            {
                "bruto": "100.00",
                "desconto_total": "5.00",
                "final": "95.00",
                "elegivel_pontos": "100.00",
            },
        )
        self.assertEqual(
            dados["pontos"],
            {
                "base": "100.0000",
                "apos_campanha": "100.0000",
                "bonus_nivel": "10.0000",
                "bonus_retorno": "0.0000",
                "total_estimado": "110.0000",
            },
        )

        self.assertEqual(self.contagens_dominio(), antes)

    def test_equivale_compra_real_com_campanha_nivel_e_retorno(self):
        self.lote(
            "100.00",
            ocorrida_em=self.agora - timedelta(days=181),
        )

        criar_nivel(
            self.request(),
            nome="Inicial",
            pontos_minimos=Decimal("0"),
            bonus_pontos_percentual=Decimal("10"),
            desconto_percentual=Decimal("5"),
        )
        criar_nivel(
            self.request(),
            nome="Ouro",
            pontos_minimos=Decimal("500"),
            bonus_pontos_percentual=Decimal("20"),
            desconto_percentual=Decimal("8"),
        )

        self.configurar(
            pontos_por_real=Decimal("1.00"),
            precisao_pontos=4,
            base_calculo_pontos="BRUTO",
            modo_aplicacao_nivel="ATINGIDO_NA_COMPRA",
            modo_combinacao_descontos_percentuais="ADITIVO",
            periodo_cliente_ativo_dias=180,
            inatividade_suspende_beneficios_nivel=True,
            beneficio_primeira_compra_apos_inatividade=(
                "COM_BENEFICIOS_NIVEL"
            ),
            promocao_retorno_ativa=True,
            bonus_pontos_retorno_percentual=Decimal("30"),
            desconto_retorno_percentual=Decimal("10"),
        )

        criar_evento(
            self.request(),
            nome="Semana do Cliente",
            inicio_em=self.agora - timedelta(days=1),
            fim_em=self.agora + timedelta(days=1),
            escopo="EMPRESA",
            efeitos=[
                {
                    "tipo": "MULTIPLICADOR_PONTOS",
                    "valor": Decimal("2.0000"),
                },
            ],
        )

        antes = self.contagens_dominio()

        resposta = self.simular(valor="250.00")

        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()

        self.assertEqual(self.contagens_dominio(), antes)

        self.assertFalse(dados["atividade"]["ativo"])
        self.assertTrue(dados["atividade"]["retorno"])

        self.assertEqual(dados["nivel"]["atual"]["nome"], "Inicial")
        self.assertEqual(
            dados["nivel"]["bonus_pontos"]["nome"],
            "Ouro",
        )
        self.assertTrue(dados["nivel"]["beneficios_aplicaveis"])
        self.assertEqual(
            dados["nivel"]["bonus_pontos_percentual"],
            "20.0000",
        )
        self.assertEqual(
            dados["nivel"]["desconto_percentual"],
            "5.0000",
        )

        self.assertEqual(
            dados["campanha"],
            {
                "aplicavel": True,
                "nome": "Semana do Cliente",
                "multiplicador_pontos": "2.0000",
            },
        )
        self.assertEqual(
            dados["promocao_retorno"],
            {
                "aplicavel": True,
                "bonus_pontos_percentual": "30.0000",
                "desconto_percentual": "10.0000",
            },
        )

        self.assertEqual(
            dados["valores"],
            {
                "bruto": "250.00",
                "desconto_total": "37.50",
                "final": "212.50",
                "elegivel_pontos": "250.00",
            },
        )
        self.assertEqual(
            dados["pontos"],
            {
                "base": "250.0000",
                "apos_campanha": "500.0000",
                "bonus_nivel": "50.0000",
                "bonus_retorno": "75.0000",
                "total_estimado": "625.0000",
            },
        )

        compra, criada = registrar_compra(
            credencial=self.credencial,
            loja_id=self.loja.pk,
            cliente_cpf=self.usuario.cpf,
            identificador_externo="EFETIVA-APOS-SIMULACAO",
            valor=Decimal("250.00"),
            ocorrida_em=self.agora,
        )

        self.assertTrue(criada)

        lote = compra.lote_pontos
        resultado = lote.beneficios_aplicados["resultado"]

        self.assertEqual(
            lote.pontos_base,
            Decimal(dados["pontos"]["base"]),
        )
        self.assertEqual(
            lote.pontos_concedidos,
            Decimal(dados["pontos"]["total_estimado"]),
        )
        self.assertEqual(
            lote.multiplicador_pontos_aplicado,
            Decimal(dados["campanha"]["multiplicador_pontos"]),
        )

        self.assertEqual(
            Decimal(resultado["valor_final"]),
            Decimal(dados["valores"]["final"]),
        )
        self.assertEqual(
            Decimal(resultado["valor_elegivel_pontos"]),
            Decimal(dados["valores"]["elegivel_pontos"]),
        )
        self.assertEqual(
            Decimal(resultado["pontos_base"]),
            Decimal(dados["pontos"]["base"]),
        )
        self.assertEqual(
            Decimal(resultado["pontos_campanha"]).quantize(
                Decimal("0.0001"),
            ),
            Decimal(dados["pontos"]["apos_campanha"]),
        )
        self.assertEqual(
            Decimal(resultado["pontos_bonus_nivel"]).quantize(
                Decimal("0.0001"),
            ),
            Decimal(dados["pontos"]["bonus_nivel"]),
        )
        self.assertEqual(
            Decimal(resultado["pontos_bonus_retorno"]).quantize(
                Decimal("0.0001"),
            ),
            Decimal(dados["pontos"]["bonus_retorno"]),
        )

        self.assertEqual(
            resultado["nivel_anterior"]["nome"],
            dados["nivel"]["atual"]["nome"],
        )
        self.assertEqual(
            resultado["nivel_bonus"]["nome"],
            dados["nivel"]["bonus_pontos"]["nome"],
        )
        self.assertEqual(
            resultado["ativo_antes"],
            dados["atividade"]["ativo"],
        )
        self.assertEqual(
            resultado["retorno"],
            dados["atividade"]["retorno"],
        )
        self.assertEqual(
            resultado["beneficios_nivel_aplicaveis"],
            dados["nivel"]["beneficios_aplicaveis"],
        )

        self.assertEqual(
            AplicacaoEfeitoEventoLote.objects.filter(
                lote=lote,
            ).count(),
            1,
        )

    def test_inatividade_suspende_nivel_mas_expoe_configuracao(self):
        self.lote(
            "100.00",
            ocorrida_em=self.agora - timedelta(days=181),
        )

        criar_nivel(
            self.request(),
            nome="Inicial",
            pontos_minimos=Decimal("0"),
            bonus_pontos_percentual=Decimal("20"),
            desconto_percentual=Decimal("5"),
        )

        self.configurar(
            base_calculo_pontos="BRUTO",
            periodo_cliente_ativo_dias=180,
            inatividade_suspende_beneficios_nivel=True,
            beneficio_primeira_compra_apos_inatividade=(
                "SEM_BENEFICIOS_NIVEL"
            ),
            promocao_retorno_ativa=True,
            bonus_pontos_retorno_percentual=Decimal("30"),
            desconto_retorno_percentual=Decimal("10"),
        )

        dados = self.simular(valor="200.00").json()

        self.assertFalse(dados["atividade"]["ativo"])
        self.assertTrue(dados["atividade"]["retorno"])

        self.assertFalse(dados["nivel"]["beneficios_aplicaveis"])
        self.assertEqual(
            dados["nivel"]["bonus_pontos_percentual"],
            "20.0000",
        )
        self.assertEqual(
            dados["nivel"]["desconto_percentual"],
            "5.0000",
        )

        self.assertEqual(dados["pontos"]["bonus_nivel"], "0.0000")
        self.assertEqual(dados["pontos"]["bonus_retorno"], "60.0000")
        self.assertEqual(dados["valores"]["desconto_total"], "20.00")
        self.assertEqual(dados["valores"]["final"], "180.00")

        self.assertTrue(dados["promocao_retorno"]["aplicavel"])

    def test_escopo_tenant_autenticacao_e_payload_estrito(self):
        _, chave_restrita = self.emitir("LOJAS", [self.loja])

        for loja_id in (
            self.segunda.pk,
            self.externa.pk,
            999999,
        ):
            with self.subTest(loja_id=loja_id):
                self.assert_erro(
                    self.simular(
                        chave=chave_restrita,
                        loja_id=loja_id,
                    ),
                    403,
                    "loja_fora_do_escopo",
                )

        inexistente = self.simular(
            cliente_cpf="39053344705",
        )
        outro_tenant = self.simular(
            cliente_cpf=self.sem_vinculo.cpf,
        )

        self.assert_erro(
            inexistente,
            404,
            "cliente_nao_encontrado",
        )
        self.assertEqual(
            outro_tenant.json(),
            inexistente.json(),
        )

        sem_chave = APIClient().post(
            "/api/v1/compras/simular/",
            {
                "loja_id": self.loja.pk,
                "cliente_cpf": self.usuario.cpf,
                "valor": "100.00",
            },
            format="json",
        )
        self.assert_erro(
            sem_chave,
            401,
            "credencial_invalida",
        )

        payloads_invalidos = (
            {
                "cliente_cpf": self.usuario.cpf,
                "valor": "100.00",
            },
            {
                "loja_id": self.loja.pk,
                "valor": "100.00",
            },
            {
                "loja_id": self.loja.pk,
                "cliente_cpf": self.usuario.cpf,
            },
            {
                "loja_id": self.loja.pk,
                "cliente_cpf": "abc",
                "valor": "100.00",
            },
            {
                "loja_id": self.loja.pk,
                "cliente_cpf": self.usuario.cpf,
                "valor": 100.0,
            },
            {
                "loja_id": self.loja.pk,
                "cliente_cpf": self.usuario.cpf,
                "valor": "100.00",
                "ocorrida_em": self.agora.isoformat(),
            },
            {
                "loja_id": self.loja.pk,
                "cliente_cpf": self.usuario.cpf,
                "valor": "100.00",
                "pontos": "9999.0000",
            },
            {
                "loja_id": self.loja.pk,
                "cliente_cpf": self.usuario.cpf,
                "valor": "100.00",
                "desconto_percentual": "99.0000",
            },
        )

        for payload in payloads_invalidos:
            with self.subTest(payload=payload):
                resposta = APIClient().post(
                    "/api/v1/compras/simular/",
                    payload,
                    format="json",
                    HTTP_X_API_KEY=self.chave,
                )
                self.assert_erro(
                    resposta,
                    400,
                    "requisicao_invalida",
                )

    def test_metodos_diferentes_de_post_nao_sao_aceitos(self):
        caminho = "/api/v1/compras/simular/"
        api = APIClient()

        for metodo in ("get", "put", "patch", "delete"):
            with self.subTest(metodo=metodo):
                resposta = getattr(api, metodo)(
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
