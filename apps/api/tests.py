import json
import secrets
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError as DomainValidationError
from django.core.signals import got_request_exception
from django.http import Http404
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from django.views.debug import SafeExceptionReporterFilter
from rest_framework.exceptions import ParseError, ValidationError
from rest_framework.test import APIClient, APIRequestFactory

from apps.empresas.models import CredencialIntegracao, Loja
from apps.empresas.services import desativar_credencial
from apps.empresas.test_integracoes import DadosIntegracoes

from .exceptions import exception_handler


ERRO_CREDENCIAL = {
    "erro": {"codigo": "credencial_invalida", "mensagem": "Credencial de integração inválida."},
}


class AutenticacaoAPITests(DadosIntegracoes, TestCase):
    def setUp(self):
        self.api = APIClient(enforce_csrf_checks=True)
        self.credencial, self.chave = self.criar()

    def contexto(self, chave=None, **extra):
        if chave is not None:
            extra["HTTP_X_API_KEY"] = chave
        return self.api.get("/api/v1/contexto/", **extra)

    def assert_invalida(self, resposta):
        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(resposta.json(), ERRO_CREDENCIAL)
        self.assertEqual(resposta["WWW-Authenticate"], "X-API-Key")
        self.credencial.refresh_from_db()
        self.assertIsNone(self.credencial.ultimo_uso_em)

    def test_sem_header_401(self):
        self.assert_invalida(self.contexto())

    def test_headers_malformados_mesmo_envelope_401(self):
        for chave in ("", "sem-separador", ".segredo", "identificador.", "a.b.c", "a.b,c.d",
                      f"Bearer {self.chave}", f" {self.chave}", "á.b", "a." + "b" * 129):
            with self.subTest(formato=chave.split(".")[0]):
                self.assert_invalida(self.contexto(chave))

    def test_identificador_inexistente_401(self):
        self.assert_invalida(self.contexto(f"{secrets.token_urlsafe(18)}.{secrets.token_urlsafe(32)}"))

    def test_segredo_incorreto_401(self):
        self.assert_invalida(self.contexto(f"{self.credencial.identificador}.{secrets.token_urlsafe(32)}"))

    def test_credencial_inativa_401(self):
        desativar_credencial(self.request(), self.credencial.pk)
        self.assert_invalida(self.contexto(self.chave))

    def test_credencial_valida_atualiza_ultimo_uso_somente_no_sucesso(self):
        primeiro = timezone.now() - timedelta(minutes=2)
        segundo = primeiro + timedelta(minutes=1)
        with patch("apps.empresas.services.timezone.now", return_value=primeiro):
            self.assertEqual(self.contexto(self.chave).status_code, 200)
        self.credencial.refresh_from_db()
        self.assertEqual(self.credencial.ultimo_uso_em, primeiro)
        with patch("apps.empresas.services.timezone.now", return_value=segundo):
            self.assertEqual(self.contexto(self.chave).status_code, 200)
        self.credencial.refresh_from_db()
        self.assertEqual(self.credencial.ultimo_uso_em, segundo)
        invalida = self.contexto(f"{self.credencial.identificador}.{secrets.token_urlsafe(32)}")
        self.assertEqual(invalida.status_code, 401)
        desativar_credencial(self.request(), self.credencial.pk)
        self.assertEqual(self.contexto(self.chave).status_code, 401)
        self.credencial.refresh_from_db()
        self.assertEqual(self.credencial.ultimo_uso_em, segundo)

    def test_request_auth_contem_credencial_sem_usuario_humano(self):
        resposta = self.contexto(self.chave)
        request = resposta.renderer_context["request"]
        self.assertIsNone(request.user)
        self.assertIsInstance(request.auth, CredencialIntegracao)
        self.assertEqual(request.auth.pk, self.credencial.pk)

    def test_sessao_web_basic_e_query_string_nao_autenticam_integracao(self):
        self.autenticar_admin(self.api)
        self.assert_invalida(self.contexto())
        self.assert_invalida(self.contexto(HTTP_AUTHORIZATION="Basic dXNlcjpwYXNz"))
        self.assert_invalida(self.api.get("/api/v1/contexto/", {"X-API-Key": self.chave}))

    def test_desativacao_web_revoga_chave_imediatamente(self):
        self.assertEqual(self.contexto(self.chave).status_code, 200)
        self.autenticar_admin()
        resposta = self.client.post(f"/gestao/integracoes/{self.credencial.pk}/desativar/")
        self.assertEqual(resposta.status_code, 302)
        resposta = self.contexto(self.chave)
        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(resposta.json(), ERRO_CREDENCIAL)

    def test_api_nao_exige_csrf_e_405_preserva_envelope(self):
        resposta = self.api.post("/api/v1/contexto/", {}, format="json", HTTP_X_API_KEY=self.chave)
        self.assertEqual(resposta.status_code, 405)
        self.assertEqual(resposta.json(), {
            "erro": {"codigo": "metodo_nao_permitido", "mensagem": "Método não permitido."},
        })
        self.assertIn("GET", resposta["Allow"])

    @override_settings(DEBUG=False)
    def test_segredo_filtrado_do_reporting_django(self):
        request = APIRequestFactory().get("/api/v1/contexto/", HTTP_X_API_KEY=self.chave)
        seguros = SafeExceptionReporterFilter().get_safe_request_meta(request)
        self.assertNotIn(self.chave, str(seguros))
        self.assertEqual(seguros["HTTP_X_API_KEY"], "********************")

    @override_settings(DEBUG=False)
    def test_erro_inesperado_preserva_500_signal_logging_e_nao_expoe_detalhes(self):
        recebidas = []

        def registrar(sender, request, **kwargs):
            recebidas.append(request.path)

        got_request_exception.connect(registrar)
        self.api.raise_request_exception = False
        try:
            with patch("apps.api.views.lojas_autorizadas", side_effect=RuntimeError("detalhe interno de teste")):
                with self.assertLogs("django.request", level="ERROR") as logs:
                    resposta = self.contexto(self.chave)
            self.assertEqual(resposta.status_code, 500)
            self.assertEqual(recebidas, ["/api/v1/contexto/"])
            self.assertTrue(any(registro.exc_info for registro in logs.records))
            self.assertNotIn(b"detalhe interno", resposta.content)
            self.assertNotIn(b"Traceback", resposta.content)
            self.assertNotIn(self.chave.encode(), resposta.content)
            self.assertNotIn(self.chave, "\n".join(logs.output))
        finally:
            got_request_exception.disconnect(registrar)


class ContextoAPITests(DadosIntegracoes, TestCase):
    def contexto(self, chave):
        return self.client.get("/api/v1/contexto/", HTTP_X_API_KEY=chave)

    def test_empresa_retorna_contrato_exato_somente_lojas_proprias(self):
        credencial, chave = self.criar()
        resposta = self.contexto(chave)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), {
            "credencial": {"identificador": credencial.identificador, "nome": "PDV"},
            "empresa": {"id": self.empresa.pk, "nome": "Empresa A"},
            "escopo": "EMPRESA",
            "lojas": [
                {"id": self.loja.pk, "nome": "Centro", "cidade": "Araras"},
                {"id": self.segunda.pk, "nome": "Shopping", "cidade": "Araras"},
            ],
        })
        self.assertIn("no-store", resposta["Cache-Control"])
        for privado in (credencial.segredo_hash, chave, "segredo_hash", "cnpj", "cpf"):
            self.assertNotIn(privado, resposta.content.decode())

    def test_empresa_inclui_loja_futura_ordenacao_por_nome_e_pk(self):
        credencial, chave = self.criar()
        nova = Loja.objects.create(empresa=self.empresa, nome="Centro", cidade="Limeira")
        ids = [loja["id"] for loja in self.contexto(chave).json()["lojas"]]
        self.assertEqual(ids, [self.loja.pk, nova.pk, self.segunda.pk])
        self.assertFalse(credencial.acessos_lojas.exists())

    def test_lojas_retorna_somente_relacionadas(self):
        _, chave = self.criar("LOJAS", [self.segunda])
        resposta = self.contexto(chave)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["escopo"], "LOJAS")
        self.assertEqual(resposta.json()["lojas"], [{"id": self.segunda.pk, "nome": "Shopping", "cidade": "Araras"}])

    def test_relacao_corrompida_nao_vaza_loja_de_outra_empresa(self):
        credencial, chave = self.criar("LOJAS", [self.loja])
        # Bypass deliberado para simular corrupção fora do fluxo normal.
        credencial.acessos_lojas.update(loja=self.externa)
        self.assertEqual(self.contexto(chave).json()["lojas"], [])

    def test_empresa_e_loja_em_query_string_nao_ampliam_escopo(self):
        _, chave = self.criar("LOJAS", [self.loja])
        resposta = self.client.get("/api/v1/contexto/", {
            "empresa_id": self.outra.pk, "loja_id": self.externa.pk,
        }, HTTP_X_API_KEY=chave)
        self.assertEqual(resposta.json()["empresa"]["id"], self.empresa.pk)
        self.assertEqual([loja["id"] for loja in resposta.json()["lojas"]], [self.loja.pk])


class APIContratoPublicoTests(SimpleTestCase):
    def test_health_publico_resposta_exata_sem_consulta_ao_banco(self):
        resposta = self.client.get("/api/v1/health/")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), {"status": "ok"})
        self.assertEqual(self.client.get("/api/v1/health/", HTTP_X_API_KEY="malformado").json(), {"status": "ok"})

    def test_health_metodo_nao_permitido_405(self):
        resposta = APIClient(enforce_csrf_checks=True).post("/api/v1/health/", {})
        self.assertEqual(resposta.status_code, 405)
        self.assertEqual(resposta.json(), {
            "erro": {"codigo": "metodo_nao_permitido", "mensagem": "Método não permitido."},
        })

    def test_404_dentro_da_api_tem_envelope_independente_de_csrf(self):
        api = APIClient(enforce_csrf_checks=True)
        for metodo in ("get", "post"):
            with self.subTest(metodo=metodo):
                resposta = getattr(api, metodo)("/api/v1/inexistente/")
                self.assertEqual(resposta.status_code, 404)
                self.assertEqual(resposta.json(), {
                    "erro": {"codigo": "nao_encontrado", "mensagem": "Recurso não encontrado."},
                })

    def test_schema_swagger_redoc_publicos(self):
        for caminho in ("/api/schema/", "/api/docs/", "/api/redoc/"):
            with self.subTest(caminho=caminho):
                self.assertEqual(self.client.get(caminho).status_code, 200)

    def test_schema_apenas_paths_reais_security_scheme_e_autenticacao_por_endpoint(self):
        resposta = self.client.get("/api/schema/", HTTP_ACCEPT="application/vnd.oai.openapi+json")
        self.assertEqual(resposta.status_code, 200)
        schema = json.loads(resposta.content)
        self.assertEqual(set(schema["paths"]), {"/api/v1/health/", "/api/v1/contexto/", "/api/v1/clientes/fidelidade/", "/api/v1/compras/simular/", "/api/v1/compras/", "/api/v1/resgates/simular/", "/api/v1/resgates/"})
        self.assertEqual(set(schema["components"]["securitySchemes"]), {"X-API-Key"})
        scheme = schema["components"]["securitySchemes"]["X-API-Key"]
        self.assertEqual((scheme["type"], scheme["in"], scheme["name"]), ("apiKey", "header", "X-API-Key"))
        self.assertIn("<identificador>.<segredo>", scheme["description"])
        health = schema["paths"]["/api/v1/health/"]["get"]
        contexto = schema["paths"]["/api/v1/contexto/"]["get"]
        self.assertFalse(health.get("security", schema.get("security", [])))
        self.assertEqual(contexto["security"], [{"X-API-Key": []}])
        self.assertNotIn("segredo_hash", json.dumps(schema))

    def test_swagger_aponta_para_schema_sem_persistir_autorizacao(self):
        resposta = self.client.get("/api/docs/")
        self.assertContains(resposta, "/api/schema/")
        self.assertContains(resposta, '"persistAuthorization": false')
        self.assertContains(self.client.get("/api/redoc/"), "/api/schema/")


class ExceptionHandlerTests(SimpleTestCase):
    def test_400_403_404_sem_vazar_detalhes_internos(self):
        for exc, status, codigo, mensagem in (
            (ParseError("detalhe interno"), 400, "requisicao_invalida", "Dados inválidos."),
            (PermissionDenied("detalhe interno"), 403, "acesso_negado", "Acesso negado."),
            (Http404("detalhe interno"), 404, "nao_encontrado", "Recurso não encontrado."),
        ):
            with self.subTest(status=status):
                resposta = exception_handler(exc, {})
                self.assertEqual(resposta.status_code, status)
                self.assertEqual(resposta.data, {"erro": {"codigo": codigo, "mensagem": mensagem}})

    def test_validacao_drf_e_dominio_usam_detalhes_no_envelope_400(self):
        for tipo in (ValidationError, DomainValidationError):
            resposta = exception_handler(tipo({"nome": ["Campo obrigatório."]}), {})
            self.assertEqual(resposta.status_code, 400)
            self.assertEqual(resposta.data, {"erro": {
                "codigo": "requisicao_invalida", "mensagem": "Dados inválidos.",
                "detalhes": {"nome": ["Campo obrigatório."]},
            }})

    def test_excecao_inesperada_delega_ao_framework(self):
        self.assertIsNone(exception_handler(RuntimeError("Falha interna"), {}))
