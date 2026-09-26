import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.clientes.models import Cliente
from apps.empresas.services import desativar_credencial
from apps.fidelidade.models import Compra
from apps.fidelidade.test_compras import DadosCompras


class CompraHTTPTests(DadosCompras, TestCase):
    def payload(self, **alteracoes):
        return dict({
            "loja_id": self.loja.pk, "identificador_externo": "VENDA-000123",
            "cliente_cpf": self.usuario.cpf, "valor": "199.90", "ocorrida_em": self.instante.isoformat(),
        }, **alteracoes)

    def enviar(self, chave=None, **alteracoes):
        return APIClient(enforce_csrf_checks=True).post(
            "/api/v1/compras/", self.payload(**alteracoes), format="json",
            HTTP_X_API_KEY=self.chave if chave is None else chave,
        )

    def assert_erro(self, resposta, status, codigo):
        self.assertEqual(resposta.status_code, status)
        self.assertEqual(set(resposta.json()), {"erro"})
        self.assertEqual(resposta.json()["erro"]["codigo"], codigo)

    def test_primeira_201_retry_200_contrato_publico_sem_dados_de_autenticacao(self):
        primeira = self.enviar()
        self.assertEqual(primeira.status_code, 201)
        dados = primeira.json()
        compra = Compra.objects.get()
        self.assertEqual(set(dados), {"id", "identificador_externo", "loja", "cliente", "valor", "ocorrida_em", "criada_em", "fidelidade"})
        self.assertEqual(dados["id"], compra.pk)
        self.assertEqual(dados["loja"], {"id": self.loja.pk, "nome": "Centro"})
        self.assertEqual(dados["cliente"], {"cpf": self.usuario.cpf})
        self.assertEqual(dados["valor"], "199.90")
        self.assertIn("no-store", primeira["Cache-Control"])
        for privado in ("segredo", "hash", "senha", "password", "credencial", self.chave):
            self.assertNotIn(privado, primeira.content.decode())
        retry = self.enviar(cliente_cpf="529.982.247-25", identificador_externo=" VENDA-000123 ")
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json(), dados)
        self.assertEqual(Compra.objects.count(), 1)

    def test_401_ausente_invalida_e_desativada_sem_compra(self):
        resposta = APIClient().post("/api/v1/compras/", self.payload(), format="json")
        self.assert_erro(resposta, 401, "credencial_invalida")
        self.assertEqual(self.enviar(chave="invalida").json(), resposta.json())
        desativar_credencial(self.request(), self.credencial.pk)
        inativa = self.enviar()
        self.assert_erro(inativa, 401, "credencial_invalida")
        self.assertEqual(inativa.json(), resposta.json())
        self.assertFalse(Compra.objects.exists())

    def test_empresa_pode_usar_duas_lojas_com_mesmo_identificador(self):
        primeira = self.enviar()
        segunda = self.enviar(loja_id=self.segunda.pk)
        self.assertEqual((primeira.status_code, segunda.status_code), (201, 201))
        self.assertNotEqual(primeira.json()["id"], segunda.json()["id"])
        self.assertEqual(Compra.objects.count(), 2)

    def test_lojas_restritas_cross_tenant_e_inexistente_403(self):
        _, chave = self.emitir("LOJAS", [self.loja])
        self.assertEqual(self.enviar(chave=chave).status_code, 201)
        respostas = [self.enviar(chave=chave, loja_id=loja_id) for loja_id in
                     (self.segunda.pk, self.externa.pk, 999999)]
        for resposta in respostas:
            self.assert_erro(resposta, 403, "loja_fora_do_escopo")
            self.assertEqual(resposta.json(), respostas[0].json())
        self.assertEqual(Compra.objects.count(), 1)

    def test_credencial_empresa_nao_atravessa_tenant(self):
        self.assert_erro(self.enviar(loja_id=self.externa.pk), 403, "loja_fora_do_escopo")
        self.assertFalse(Compra.objects.exists())

    def test_cliente_sem_vinculo_ou_inexistente_404_sem_criar_identidade(self):
        anterior = list(get_user_model().objects.order_by("pk").values())
        for cpf in (self.sem_vinculo.cpf, "39053344705"):
            resposta = self.enviar(cliente_cpf=cpf)
            self.assert_erro(resposta, 404, "cliente_nao_encontrado")
            self.assertEqual(resposta.json()["erro"]["mensagem"], "Cliente não encontrado.")
        self.assertEqual(list(get_user_model().objects.order_by("pk").values()), anterior)
        self.assertEqual(Cliente.objects.count(), 3)
        self.assertFalse(Compra.objects.exists())

    def test_cpf_invalido_400(self):
        for cpf in ("abc", "529/982/247-25", "52998224726", ""):
            self.assert_erro(self.enviar(cliente_cpf=cpf), 400, "requisicao_invalida")
        self.assertFalse(Compra.objects.exists())

    def test_valores_invalidos_400_e_limites_aceitos(self):
        for valor in ("0.00", "-0.01", "0.001", "10000000000.00", "NaN", "Infinity", "abc", None, 199.9, True):
            with self.subTest(valor=valor):
                self.assert_erro(self.enviar(valor=valor), 400, "requisicao_invalida")
        self.assertFalse(Compra.objects.exists())
        for valor in ("0.01", "9999999999.99"):
            resposta = self.enviar(valor=valor, identificador_externo=valor)
            self.assertEqual(resposta.status_code, 201)
            self.assertEqual(resposta.json()["valor"], valor)

    def test_identificador_normalizado_limite_case_e_espacos_internos(self):
        resposta = self.enviar(identificador_externo="  Venda  A-b \t")
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(resposta.json()["identificador_externo"], "Venda  A-b")
        self.assertEqual(self.enviar(identificador_externo="venda  A-b").status_code, 201)
        self.assertEqual(self.enviar(identificador_externo=" " + "a" * 255 + " ").status_code, 201)
        for identificador in ("", "  \t", "a" * 256):
            self.assert_erro(self.enviar(identificador_externo=identificador), 400, "requisicao_invalida")

    def test_datetime_invalido_ou_sem_timezone_400_e_offsets_equivalentes_200(self):
        for data in ("2026-09-23T10:30:00", "2026-09-23", "2026-02-30T10:00:00Z", "invalido", None):
            with self.subTest(data=data):
                self.assert_erro(self.enviar(ocorrida_em=data), 400, "requisicao_invalida")
        self.assertFalse(Compra.objects.exists())
        primeira = self.enviar()
        retry = self.enviar(ocorrida_em="2026-09-23T13:30:00Z")
        self.assertEqual((primeira.status_code, retry.status_code), (201, 200))
        self.assertEqual(primeira.json(), retry.json())

    def test_todos_campos_obrigatorios(self):
        for campo in self.payload():
            dados = self.payload()
            dados.pop(campo)
            resposta = APIClient().post("/api/v1/compras/", dados, format="json", HTTP_X_API_KEY=self.chave)
            with self.subTest(campo=campo):
                self.assert_erro(resposta, 400, "requisicao_invalida")
        self.assertFalse(Compra.objects.exists())

    def test_conflitos_409_nao_expoem_fatos_anteriores_nem_alteram_compra(self):
        self.enviar()
        antes = Compra.objects.values().get()
        for alteracoes in ({"cliente_cpf": self.outro_usuario.cpf}, {"valor": "200.00"},
                           {"ocorrida_em": (self.instante + timedelta(seconds=1)).isoformat()}):
            resposta = self.enviar(**alteracoes)
            self.assert_erro(resposta, 409, "idempotencia_conflitante")
            self.assertEqual(resposta.json(), {"erro": {
                "codigo": "idempotencia_conflitante",
                "mensagem": "Identificador externo já utilizado com dados diferentes.",
            }})
            self.assertEqual(Compra.objects.count(), 1)
            self.assertEqual(Compra.objects.values().get(), antes)

    def test_retry_outra_credencial_autorizada_preserva_criacao_e_origem(self):
        primeira = self.enviar()
        origem = Compra.objects.get().credencial_origem_id
        _, chave = self.emitir("LOJAS", [self.loja])
        desativar_credencial(self.request(), self.credencial.pk)
        retry = self.enviar(chave=chave)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json(), primeira.json())
        self.assertEqual(Compra.objects.get().credencial_origem_id, origem)

    def test_metodos_nao_disponiveis_405(self):
        for metodo in ("get", "put", "patch", "delete"):
            resposta = getattr(APIClient(), metodo)("/api/v1/compras/", HTTP_X_API_KEY=self.chave)
            self.assert_erro(resposta, 405, "metodo_nao_permitido")
        self.assertFalse(Compra.objects.exists())


class CompraOpenAPITests(SimpleTestCase):
    def test_schema_contrato_real_limites_e_autenticacao(self):
        resposta = self.client.get("/api/schema/", HTTP_ACCEPT="application/vnd.oai.openapi+json")
        self.assertEqual(resposta.status_code, 200)
        schema = json.loads(resposta.content)
        self.assertEqual(set(schema["paths"]), {"/api/v1/health/", "/api/v1/contexto/", "/api/v1/clientes/fidelidade/", "/api/v1/compras/simular/", "/api/v1/compras/", "/api/v1/resgates/simular/", "/api/v1/resgates/"})
        operacoes = schema["paths"]["/api/v1/compras/"]
        self.assertEqual(set(operacoes), {"post"})
        post = operacoes["post"]
        self.assertEqual(post["security"], [{"X-API-Key": []}])
        self.assertEqual(set(post["responses"]), {"200", "201", "400", "401", "403", "404", "409", "405"})
        referencia = post["requestBody"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
        entrada = schema["components"]["schemas"][referencia]
        self.assertEqual(set(entrada["required"]), {"loja_id", "identificador_externo", "cliente_cpf", "valor", "ocorrida_em"})
        self.assertEqual(entrada["properties"]["identificador_externo"]["maxLength"], 255)
        self.assertIn("9999999999.99", entrada["properties"]["valor"]["description"])
        self.assertIn("0.01", entrada["properties"]["valor"]["description"])
        self.assertEqual(entrada["properties"]["ocorrida_em"]["format"], "date-time")
        for status in ("200", "201"):
            referencia = post["responses"][status]["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
            saida = schema["components"]["schemas"][referencia]
            self.assertEqual(set(saida["properties"]), {"id", "identificador_externo", "loja", "cliente", "valor", "ocorrida_em", "criada_em", "fidelidade"})
